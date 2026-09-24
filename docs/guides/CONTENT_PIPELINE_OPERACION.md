# Pipeline de contenido — operarlo

> **Qué es esto:** cómo se comprueba, se diagnostica y se mantiene el pipeline Notion → n8n → Postiz → Instagram: la batería de pruebas, qué hacer si Notion falla, dónde está el historial de errores, cómo rotar credenciales y cómo está dado de alta el webhook de Postiz.
> Dónde vive cada pieza y cada secreto: [INVENTARIO](../reference/CONTENT_PIPELINE_INVENTARIO.md).
>
> **Parte de:** [CONTENT_PIPELINE_NOTION_POSTIZ.md](../architecture/CONTENT_PIPELINE_NOTION_POSTIZ.md), que tiene el mapa de todos los documentos del pipeline. Si el pipeline «no hace nada», antes que nada: [ARRANQUE_Y_SUPERVISION.md](../architecture/ARRANQUE_Y_SUPERVISION.md).

---

## 1. La batería de pruebas

**Comprobaciones contra producción sin publicar nada en Instagram.** El script es [`suite-pruebas-postiz.py`](../architecture/scripts/suite-pruebas-postiz.py), con copia viva en `/opt/homeserver/n8n-workflows/` ([INVENTARIO §2](../reference/CONTENT_PIPELINE_INVENTARIO.md)). Se ejecuta en el Beelink con el entorno del servidor cargado:

```
set -a; . /opt/homeserver/.env; set +a; python3 /opt/homeserver/n8n-workflows/suite-pruebas-postiz.py
```

Las reglas del trial reel tienen su propia prueba, [`prueba-trial-reels.py`](../architecture/scripts/prueba-trial-reels.py) ([NOTION_SCHEMA §2.3](../architecture/CONTENT_PIPELINE_NOTION_SCHEMA.md)). Y el convertidor, la suya: [`test_normalizar-media.sh`](../architecture/scripts/test_normalizar-media.sh) fabrica un fichero de cada caso que Instagram no publica tal cual (HEIC, WebP, AVIF, GIF, PNG grande con transparencia, WebM, 120 fps, audio PCM, más de 300 MB, un fichero ilegible), lo pasa por la copia viva, mide lo que llega a Postiz y lo borra, también del disco. Se lanza tras cambiar el script: `bash /opt/repos/postiz-fork/docs/architecture/scripts/test_normalizar-media.sh`.

> Al cargar el `.env` sale `line 103: {client_id:: command not found`. **Es inocuo y no hay que arreglarlo**: `GOOGLE_API_CREDENTIALS` es un JSON sin comillas, así que el shell lo parte en el primer espacio y esa variable queda vacía. El pipeline no la usa, y su consumidor real (`calcom`) la recibe entera porque docker-compose no usa semántica de shell. Ponerle comillas arreglaría el aviso y podría romper `calcom`.

**Qué cubre:** seguridad de los tres disparadores; las validaciones que deben acabar en `Error` **con el motivo nombrando la propiedad tal y como se llama hoy**; el camino completo de un carrusel; la regresión del margen ([SYNC §3](../architecture/CONTENT_PIPELINE_SYNC.md)); **que las pasadas van de una en una** ([SYNC §1](../architecture/CONTENT_PIPELINE_SYNC.md)); el reintento que reutiliza los medios **y que vuelve a subirlos si son otros ficheros**; la retirada; **la pieza aplazada a más de 15 días**; **la ruta de error de la subida**; **el rechazo de Postiz con el motivo en limpio** ([NOTION_SCHEMA §7.1](../architecture/CONTENT_PIPELINE_NOTION_SCHEMA.md)); la identidad externa, con grupo de control ([RECONCILIACION §3](../architecture/CONTENT_PIPELINE_RECONCILIACION.md)); **la pieza aprobada tarde** ([RECONCILIACION §1](../architecture/CONTENT_PIPELINE_RECONCILIACION.md)); el estado en reposo y la limpieza de sus propios ficheros.

**La ruta de error de la subida** se prueba con una fila de dos assets donde uno es ilegible para ffprobe. Es el único fallo del pipeline que puede ser *invisible* —la fila se queda en `Listo`, sin `error_log`, con medios huérfanos vivos ([SYNC §2](../architecture/CONTENT_PIPELINE_SYNC.md))—, y por tanto el único que ningún otro check caza. Afirma las dos caras del huérfano a propósito: que el asset bueno **llegó a subirse** (si no, la segunda afirmación pasaría sin haber probado nada) y que **no queda ninguno vivo**.

**Mejor cuando nadie está pulsando `Sync now`.** Sus pasadas son pasadas completas del sync sobre las filas reales: se ponen en fila con las de quien esté trabajando, que esperan detrás, y todas gastan del mismo límite de creaciones de Postiz ([POSTIZ_FORK §3](../architecture/CONTENT_PIPELINE_POSTIZ_FORK.md)). Lo que espera a que acabe una pasada lo llama en local, sin Cloudflare; por la URL pública solo prueba que el camino público rechaza y que el botón responde.

Tres cosas que hay que respetar al tocarla, porque las tres dan un resultado falso:

- **`User-Agent` obligatorio.** Cloudflare bloquea `Python-urllib` en este dominio ([POSTIZ_FORK §1](../architecture/CONTENT_PIPELINE_POSTIZ_FORK.md)) y devuelve `403` sin que la petición llegue a n8n. Los checks que *esperan* `403` entonces **pasan por el motivo equivocado** — por eso comprueban además que el cuerpo sea de n8n y no una página de Cloudflare.
- **Fechas relativas a hoy, nunca fijas.** Una fecha escrita a mano se sale de la ventana de 15 días con el tiempo y el sync la ignora con razón; se lee como una avería del pipeline.
- **La fila del margen usa `modo = borrador` a propósito.** Su fecha cae dentro de 40 minutos: en `programar` saldría publicada de verdad si la limpieza fallara. El margen se evalúa en `Planificar`, antes de que `modo` importe, así que la regresión se prueba igual con riesgo cero.

## 2. Si Notion falla

**Se para el pipeline entero a la vez**: los tres workflows que leen Notion por su cuenta —sync, retirada y receptor— dan error y el subflow no llega a ejecutarse. Avisa el bus de incidencias ([SYNC §5](../architecture/CONTENT_PIPELINE_SYNC.md)). Lo ya programado en Postiz sigue en pie; lo editado ese día no llega hasta la siguiente pasada o el botón. El mensaje dice cuál de las dos averías es:

- **`API token is invalid` (401):** el token está revocado. Se crea uno nuevo y se rota (§4).
- **404 que nombra la integración:** el token vale, pero la integración perdió el acceso a la base. Se arregla añadiéndola en *··· → Conexiones* de la base. **Mover la base de sitio puede quitarle la conexión: si se mueve, compruébala.**

## 3. El historial de errores

`❌ error_log` sólo guarda el último error de cada fila y el sync lo vacía al salir bien, así que el historial vive en otros sitios:

| Qué | Dónde | Cómo se lee |
|---|---|---|
| Cada error escrito en una fila, y cada workflow que falló entero (token, red) | Ejecuciones de n8n: las de los últimos **90 días** (`EXECUTIONS_DATA_MAX_AGE=2160` en el `docker-compose.yml` de Instalar-Home-Server), sin tope por número (`EXECUTIONS_DATA_PRUNE_MAX_COUNT=0`): un tope es de todos los workflows a la vez, y uno que fallara en bucle desplazaría el historial de los demás | [`errores-pipeline.py`](../architecture/scripts/errores-pipeline.py) en el Beelink: una línea por error, sin las filas de la batería |
| Los fallos al publicar | Tabla `Errors` de Postiz (`postiz_db`) | `SELECT "createdAt", platform, message FROM "Errors" ORDER BY 1;` |
| El archivo en Drive | `/var/log/postiz-archivo.log`, 8 semanas de rotación | [ARCHIVO_DRIVE.md](../architecture/ARCHIVO_DRIVE.md) |
| Cada pasada de la réplica de carruseles, con las filas que mandó a `Error` | `~/.local/state/carrusel-ig/replicar.log` en el Beelink | `tail` del log; lo escribe `replicar.sh` |

Para consultar las ejecuciones a mano: la base de n8n en `postgres_core` se llama **`n8n_db`**, no `n8n` —con el nombre obvio psql responde `database "n8n" does not exist` y parece que no hay historial—:

```
docker exec postgres_core psql -U postgres -d n8n_db -c "SELECT w.name, e.mode, e.status, e.\"startedAt\" FROM execution_entity e JOIN workflow_entity w ON w.id=e.\"workflowId\" WHERE w.name LIKE 'Postiz%' ORDER BY 4 DESC LIMIT 20;"
```

## 4. Rotar credenciales

Dónde vive cada una: [INVENTARIO §2](../reference/CONTENT_PIPELINE_INVENTARIO.md).

- **Token de Notion.** Con [`rotar-token-notion.sh`](../architecture/scripts/rotar-token-notion.sh), que escribe los dos sitios y comprueba que los dos leen la base; el uso está en su cabecera. Rotar solo uno deja la mitad del pipeline con un token muerto.
- **`X-Sync-Token`.** Si se rota en la credencial de n8n, se rota el mismo día en `/opt/homeserver/.env`, en sus dos nombres (`N8N_SYNC_IG_TOKEN` y `POSTIZ_SYNC_TOKEN`).
- **API key de Postiz.** El botón *Rotate Key* de *Settings → Developers* invalida la clave que usa la credencial `h6bGMcfTHiZUD0dy`. Rompería **los cuatro workflows a la vez** y en silencio: no se notaría hasta la pasada de las 06:00. Si se rota, se actualiza la credencial de n8n el mismo día.

> El resto de la pantalla *Settings → Developers* —CLI, skill del agente, MCP de Postiz, nodo comunitario de n8n— **no se usa a propósito**: todo eso publica *directamente en Postiz*, saltándose Notion ([NOTION_POSTIZ §5](../architecture/CONTENT_PIPELINE_NOTION_POSTIZ.md)). Lo que escriba contenido con un agente lo hace por el **MCP de Notion**, no por el de Postiz.

## 5. El webhook de Postiz

**Se da de alta a mano en la UI de Postiz**, que es la única vía: `POST /webhooks` vive en la API con sesión (`webhooks.controller.ts`), no en la pública, y con la API key devuelve `401`.

| Campo | Valor |
|---|---|
| Nombre | `n8n sync Instagram` |
| URL | `https://auto.dustincalderon.com/webhook/` + `N8N_POSTIZ_WEBHOOK_PATH` |
| Integraciones | las conectadas: las 3 de Instagram y el TikTok |

> ### ⚠️ Elegir integraciones concretas es una trampa a futuro
> El filtro de `sendWebhooks` (`post.activity.ts`) es `f.integrations.length === 0 || f.integrations.some(...)`. Con integraciones concretas **sólo entrega cuando el `integrationId` coincide**.
>
> **Al conectar una cuenta nueva hay que añadirla aquí a mano, o sus avisos no llegarán y no lo dirá nadie.** Con la opción «todas las integraciones» eso no pasa; al conectar la próxima cuenta, conviene pasar a esa opción.
>
> Dos de los caminos previos al bucle («No Post») no conocen la integración y pasan `''`, así que no entregan. No se pierde nada: ahí el post no existe y el cuerpo sería `[]` igualmente.
>
> Que TikTok esté incluido es inocuo: el receptor busca en Notion una fila que reclame el post y, al no encontrarla, lo ignora sin escribir.
