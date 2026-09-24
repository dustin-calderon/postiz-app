# Pipeline de contenido — dónde vive cada pieza

> **Qué es esto:** el inventario de lo que forma el pipeline fuera del código de este repo — workflows y credenciales de n8n, puntos de entrada, configuración de producción y secretos. **La mayor parte no vive en git**: conviene saber dónde mirar antes de auditar.
> Lo que el fork cambia en el código: [POSTIZ_FORK §10](../architecture/CONTENT_PIPELINE_POSTIZ_FORK.md). Lo que vive en Notion (propiedades, botones, vistas): [NOTION_SCHEMA](../architecture/CONTENT_PIPELINE_NOTION_SCHEMA.md).
>
> **Parte de:** [CONTENT_PIPELINE_NOTION_POSTIZ.md](../architecture/CONTENT_PIPELINE_NOTION_POSTIZ.md), que tiene el mapa de todos los documentos del pipeline.

---

## 1. n8n · `auto.dustincalderon.com`

| Objeto | ID | Qué es |
|---|---|---|
| **Sync Instagram desde Notion** (cron 06:00 + botón) | `eKxZPM4zjwhNb3vf` | [SYNC §1](../architecture/CONTENT_PIPELINE_SYNC.md) |
| **Sync IG — SUBFLOW (una fila)** | `A0XMq6dLdAWvwMPv` | [SYNC §2](../architecture/CONTENT_PIPELINE_SYNC.md) |
| **Retirada y recuperación (IG)** (cron 06:20 y dentro de cada pasada del sync) | `rxVcGlxSZjzzI5ez` | [RECONCILIACION §4](../architecture/CONTENT_PIPELINE_RECONCILIACION.md) |
| **Receptor de estado (webhook) → Notion** | `VMezjZaMTIU5dIUz` | [RECONCILIACION §1](../architecture/CONTENT_PIPELINE_RECONCILIACION.md) |
| **Carruseles · Replicar (IG)** (cron 05:00 + botón «Replicar») | `w4GOMzxTXzd26ybD` | Solo lanza por SSH `/opt/apps/carrusel-ig/replicar.sh`, que vuelve al instante; todo lo demás está en `Instalar-Home-Server/docs/architecture/CARRUSEL-IG-TRADUCIDO.md` |
| Credencial Postiz | `h6bGMcfTHiZUD0dy` | API key de la organización `CITEM` (`30c506a6…`), la única que ve las cuentas |
| Credencial Notion | `5rCv9a6s5FyI0swq` | Token de la integración `Notion SM - Postiz` (§2) |
| Credencial webhook | `4jg5NXem2BvjFtFO` | `X-Sync-Token` (§2) |

**Puntos de entrada:**

| Ruta | Auth | Responde | Para qué |
|---|---|---|---|
| `POST /webhook/postiz-sync-ig` | `X-Sync-Token` | `200` al terminar | Sync a demanda (scripts, curl) |
| `POST /webhook/postiz-sync-<secreto>` | **el secreto va en la ruta** | **`202` al instante** | El botón `Sync now` de Notion ([SYNC §1](../architecture/CONTENT_PIPELINE_SYNC.md)) |
| `POST /webhook/postiz-retirada-ig` | `X-Sync-Token` | `200` al terminar | Retirada/recuperación a demanda |
| `POST /webhook/postiz-status-<secreto>` | **el secreto va en la ruta** | `200` al terminar | Destino del webhook de Postiz |

Los secretos de ruta viven en `/opt/homeserver/.env` como `N8N_SYNC_IG_BUTTON_PATH`, `N8N_POSTIZ_WEBHOOK_PATH` y `N8N_REPLICAR_BUTTON_PATH` (el botón «Replicar»).

> ### Por qué el receptor lleva el secreto en la URL y no en una cabecera
> `sendWebhooks` (`post.activity.ts`) manda el webhook con **una sola cabecera**, `Content-Type`. No hay firma, ni HMAC, ni campo de secreto en el modelo `Webhooks` (id, name, url, organizationId). Con un emisor que no puede autenticarse, meter el secreto en la ruta es la única opción; sobre HTTPS la ruta no viaja en claro.

**Copia durable:** en `/opt/homeserver/n8n-workflows/` (modo `600`), los cuatro workflows del pipeline como `postiz-<id>.json` y el de la réplica como `carruseles-<id>.json`. Al cambiar un workflow en n8n se vuelve a exportar su copia. **No van a este repositorio**: el receptor lleva su ruta secreta dentro, y esto es un fork de un proyecto público (§2).

> **Convención: todo va por `httpRequest`, no por nodos de integración.** Ningún workflow de esta instancia usa el nodo de Notion; se llama a la API directamente. Un nodo de tercero añade una dependencia que se actualiza sola y puede cambiar de comportamiento bajo los pies.

**La API de Notion:** todos los nodos de Notion de estos workflows, y los scripts del pipeline, van con `Notion-Version: 2025-09-03`, y las consultas a `/v1/data_sources/186a2405-a123-81dc-832f-000b82a65c0c/query`, la fuente de datos del calendario. Con la versión `2022-06-28` las consultas a `/databases/…/query` fallarían en cuanto la base tuviera una segunda fuente de datos (guía oficial de Notion para `2025-09-03`).

**La base de n8n** está en `postgres_core` y se llama **`n8n_db`**, no `n8n`. Cómo leer de ella el historial: [OPERACION §3](../guides/CONTENT_PIPELINE_OPERACION.md).

## 2. Producción: configuración y secretos

| Fichero | Qué lleva el pipeline |
|---|---|
| `/opt/homeserver/postiz/postiz.env` | `API_LIMIT=300` ([POSTIZ_FORK §3](../architecture/CONTENT_PIPELINE_POSTIZ_FORK.md)) · `STORAGE_PROVIDER=local` y `CLOUDFLARE_BUCKET_URL` sin barra final ([POSTIZ_FORK §2](../architecture/CONTENT_PIPELINE_POSTIZ_FORK.md)) · `TZ` vacío ([NOTION_SCHEMA §5](../architecture/CONTENT_PIPELINE_NOTION_SCHEMA.md)) · `MAX_URL_UPLOAD_BYTES=1073741824`, 1 GiB ([SYNC §2](../architecture/CONTENT_PIPELINE_SYNC.md)) · `MEDIA_RETENTION_DAYS=3650` ([POSTIZ_FORK §7](../architecture/CONTENT_PIPELINE_POSTIZ_FORK.md); cambiarla no basta con reiniciar el contenedor: [MEDIA_CLEANUP_PIPELINE.md](../architecture/MEDIA_CLEANUP_PIPELINE.md)) |
| `/opt/homeserver/.env` | `NOTION_API_KEY` · `N8N_SYNC_IG_TOKEN` y `POSTIZ_SYNC_TOKEN` · las rutas secretas de §1 |
| Google Drive | Remoto rclone **`gdrive-work`** (cuenta de Workspace) + dos carpetas destino → [ARCHIVO_DRIVE.md](../architecture/ARCHIVO_DRIVE.md) |

> ### 🔑 Dónde vive cada secreto
>
> | Secreto | Dónde | Quién lo lee |
> |---|---|---|
> | **Token de Notion** — integración interna **`Notion SM - Postiz`** del espacio *DC Brand*, conectada a la base *Calendario Social Media* y al *Manual de uso — Social Media* | **Credencial de n8n** `5rCv9a6s5FyI0swq` (cabecera `Authorization: Bearer …`), cifrada | Sync, retirada y receptor |
> | | **`NOTION_API_KEY`** en `/opt/homeserver/.env`, mismo valor | Archivador de Drive, [`scripts/`](../architecture/scripts/) de pruebas y la réplica de carruseles (`Instalar-Home-Server`) |
> | **`X-Sync-Token`** de los webhooks con cabecera | **Credencial de n8n** `4jg5NXem2BvjFtFO` | Los webhooks del sync y de la retirada |
> | | `/opt/homeserver/.env`, **con dos nombres y el mismo valor**: `N8N_SYNC_IG_TOKEN` y `POSTIZ_SYNC_TOKEN` | Los scripts de pruebas leen el primero; `replicar.sh` (Instalar-Home-Server), el segundo |
> | **API key de Postiz** | Credencial de n8n `h6bGMcfTHiZUD0dy` | Los cuatro workflows del pipeline |
>
> Cada secreto que vive en dos sitios se rota en los dos a la vez, o la mitad del pipeline se queda con uno muerto: [OPERACION §4](../guides/CONTENT_PIPELINE_OPERACION.md).
>
> **Nunca en este repositorio.** Es un fork de un proyecto público: basta un push al remoto equivocado para filtrar un secreto. Van al `.env` del servidor o al gestor de credenciales de la herramienta que los usa — jamás a git, ni siquiera en un repo privado.

**Scripts del pipeline con copia viva en el servidor.** Viven versionados en [`docs/architecture/scripts/`](../architecture/scripts/) y **si se toca una copia hay que actualizar la otra** (se comparan con `md5sum`; los de `/opt/homeserver/postiz/` los compara además cada despliegue):

| Script | Copia viva | Qué es |
|---|---|---|
| `suite-pruebas-postiz.py`, `prueba-trial-reels.py` | `/opt/homeserver/n8n-workflows/` | La batería de pruebas ([OPERACION §1](../guides/CONTENT_PIPELINE_OPERACION.md)). Leen los valores sensibles de `os.environ` y no llevan ninguna ruta secreta dentro |
| `normalizar-media.sh` | `/opt/homeserver/postiz/` | La puerta por la que pasa todo el media ([SYNC §2](../architecture/CONTENT_PIPELINE_SYNC.md)). No lleva secretos: el `ORG` es un id y la `apiKey` la lee de la base al ejecutarse. Necesita en el host `ffmpeg`, `jq` y `heif-convert` (paquete `libheif-examples`) |
| `n8n-ssh-wrapper.sh` | `/opt/homeserver/postiz/` | El comando forzado (`authorized_keys`) de la clave SSH de n8n: decide qué puede ejecutar n8n en el host si sus credenciales caen. Lo que permite, y por qué, lo dice su cabecera |
| `turno-sync.sh` | `/opt/homeserver/postiz/` | La consulta de solo lectura con la que el sync espera su turno ([SYNC §1](../architecture/CONTENT_PIPELINE_SYNC.md)) |

`errores-pipeline.py`, `rotar-token-notion.sh` y `test_normalizar-media.sh` no tienen copia: se ejecutan desde el clon del Beelink, `/opt/repos/postiz-fork`.
