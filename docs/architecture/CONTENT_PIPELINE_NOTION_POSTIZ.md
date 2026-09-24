# Pipeline de contenido — Notion → n8n → Postiz → Instagram

> **Qué es esto:** la arquitectura del pipeline que publica en Instagram desde Notion —qué hace cada pieza y **por qué** es así—, y el mapa de los documentos que la detallan.
> **Ámbito:** Instagram, **3 cuentas** (`instagram-standalone`), desde una sola tabla de Notion.
>
> ### ⚠️ Si el pipeline «no hace nada», mira primero si el backend está vivo
> Una API caída detrás de un contenedor que se declara `healthy` se parece desde fuera a un fallo del pipeline. **→ [ARRANQUE_Y_SUPERVISION.md](./ARRANQUE_Y_SUPERVISION.md)** cubre esa capa: cómo arrancan los tres procesos, quién los vigila y cómo comprobar en un comando que un arranque fue bien.

## Mapa de documentos

| Documento | De qué se ocupa |
|---|---|
| **Este** | La decisión de arquitectura, quién manda sobre qué, las reglas innegociables, los riesgos y lo que se decidió no hacer |
| [CONTENT_PIPELINE_DIAGRAMS.md](./CONTENT_PIPELINE_DIAGRAMS.md) | **Cómo encaja todo**, en dibujos: los workflows nodo a nodo, la máquina de estados, un día cualquiera y qué pasa cuando algo falla. Si sólo vas a leer uno para operar el sistema, ése |
| [CONTENT_PIPELINE_POSTIZ_FORK.md](./CONTENT_PIPELINE_POSTIZ_FORK.md) | Lo que el fork de Postiz impone al pipeline, y lo que le añade |
| [CONTENT_PIPELINE_NOTION_SCHEMA.md](./CONTENT_PIPELINE_NOTION_SCHEMA.md) | La tabla de Notion: propiedades, validaciones, zona horaria y la máquina de estados de `Status` |
| [CONTENT_PIPELINE_SYNC.md](./CONTENT_PIPELINE_SYNC.md) | El sync de n8n: disparadores, qué hace con una fila, la subida de ficheros, el margen de seguridad y los fallos |
| [CONTENT_PIPELINE_RECONCILIACION.md](./CONTENT_PIPELINE_RECONCILIACION.md) | Cierre del bucle, borrar y recrear, identidad externa y retirada: sin duplicados ni huérfanos |
| [CONTENT_PIPELINE_API_POSTIZ.md](../reference/CONTENT_PIPELINE_API_POSTIZ.md) | El cuerpo exacto de `POST /public/v1/posts` y lo que responde cada llamada |
| [CONTENT_PIPELINE_INVENTARIO.md](../reference/CONTENT_PIPELINE_INVENTARIO.md) | Dónde vive cada pieza fuera del código: workflows de n8n, puntos de entrada, configuración y secretos |
| [CONTENT_PIPELINE_OPERACION.md](../guides/CONTENT_PIPELINE_OPERACION.md) | Operarlo: la batería de pruebas, el historial de errores, rotar credenciales, el webhook de Postiz |

**Relacionados:** [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md) · [ARCHIVO_DRIVE.md](./ARCHIVO_DRIVE.md) · [VIDEO_FORMAT_SUPPORT.md](./VIDEO_FORMAT_SUPPORT.md) · la réplica de carruseles, en `Instalar-Home-Server/docs/architecture/CARRUSEL-IG-TRADUCIDO.md`.

---

## 1. Decisión de arquitectura

Tres herramientas, todas con UI, ninguna que obligue al equipo a programar.

**Notion es la fuente de verdad (SSoT) — incluidos los ficheros máster.** El equipo no sale de Notion: planifica, escribe el copy, arrastra el vídeo a la fila y marca `Status = Listo`.

La restricción que gobierna todo el diseño es que **Notion no sirve URLs públicas estables** (enlaces firmados con 1 hora de caducidad, §4) e **Instagram exige una URL alcanzable desde internet** ([POSTIZ_FORK §1](./CONTENT_PIPELINE_POSTIZ_FORK.md)). Por tanto los bytes tienen que acabar en un host público en el momento de publicar.

Eso **no** rompe el SSoT. SSoT y hosting son trabajos distintos:

- **SSoT** = quién dice la verdad sobre qué se publica, cuándo y con qué fichero → **Notion**
- **Hosting** = quién sirve los bytes a Meta cuando toca → **Postiz** (copia derivada, desechable)

## 2. Las tres autoridades

| Actor | Manda sobre | Naturaleza |
|---|---|---|
| **Notion** | Qué se publica, cuándo, con qué texto y con qué fichero. Los másters. | **Autoridad.** Si se pierde, se pierde todo. |
| **Postiz** | Nada. Recibe órdenes, publica, devuelve IDs. Aloja una copia pública temporal. | **Ejecutor + caché.** Reconstruible desde Notion. |
| **n8n** | Nada. Ejecuta y reporta. Único con permiso de escritura en dos sistemas. | **Orquestador.** Sin estado propio. |

Postiz es el último eslabón y el más tonto, a propósito: eso es lo que permite sustituirlo sin rehacer nada más.

**Nextcloud queda fuera del pipeline.** Sigue existiendo para lo que ya hace (llevar ficheros del móvil a algún sitio). Nada automático depende de él.

**El Seagate es donde Postiz guarda los medios.** `/uploads` es un bind mount a `/mnt/seagate/postiz-media`. Para lo que pasa por el pipeline, esa copia es **derivada**, reconstruible desde Notion: el disco es la caché, no el original. Para lo publicado desde la UI de Postiz, no ([POSTIZ_FORK §7](./CONTENT_PIPELINE_POSTIZ_FORK.md)).

## 3. Flujo

```
   EQUIPO ── escribe copy · arrastra el fichero · marca "Listo" ──────┐
                                                                      ▼
                                        ╔═══════════════════════════════════╗
                                        ║  NOTION              ★ SSoT       ║
                                        ║  una tabla · ficheros incluidos   ║
                                        ║  único sitio de aprobación        ║
                                        ╚═══════════════════════════════════╝
                                             │ lee "Listo"            ▲
                                             │ + URL fresca           │ write-back
                                             ▼                        │
                                   ┌──────────────────────┐           │
                                   │  n8n   ORQUESTADOR   │───────────┘
                                   │  cron · sin LLM      │
                                   └──┬────────────────▲──┘
                      upload-from-url │                │  media_url + post_id
                    (Postiz descarga) ▼                │  + webhook al publicar
                                   ┌──────────────────────┐
                                   │  POSTIZ    ejecutor  │
                                   │  ✗ no se aprueba aquí│
                                   └──────────┬───────────┘
                                              ▼
                                         INSTAGRAM
```

El sync reescribe cada día los próximos 15 días de Postiz a partir de Notion ([SYNC](./CONTENT_PIPELINE_SYNC.md)); la reconciliación retira lo que sobra y cierra el bucle al publicar ([RECONCILIACION](./CONTENT_PIPELINE_RECONCILIACION.md)).

## 4. Restricciones reales de Notion

| Hecho | Valor | Fuente |
|---|---|---|
| Caducidad de la URL de un fichero | **1 hora** (enlace firmado) | [Retrieving files](https://developers.notion.com/docs/retrieving-files) |
| Cómo refrescarla | Volver a pedir la página | idem |
| Tamaño máximo por fichero (plan de pago) | **5 GiB** | [Working with files](https://developers.notion.com/docs/working-with-files-and-media) |
| Almacenamiento total | Sin límite en planes de pago | idem |

De aquí sale la regla más importante de toda la implementación:

> ### ⚠ Nunca se almacena una URL de Notion en ningún sitio.
> Se pide **fresca** en el momento de publicar, siempre. Una URL de Notion guardada es una bomba de relojería de una hora: funciona en la prueba manual y falla en el cron de las 6 AM.

## 5. Reglas innegociables

- ✗ **Postiz nunca escribe en Notion.** Quien cierra el bucle es n8n. Dos escritores = ninguna verdad.
- ✗ **Nunca se aprueba dentro de Postiz.** Dos sitios de aprobación = ninguno fiable en tres semanas.
- ✗ **Nunca se publica saltándose Notion** —ni desde la API de Postiz, ni con su CLI o su MCP—: las validaciones que Postiz no hace sólo las aplica el sync ([NOTION_SCHEMA §4](./CONTENT_PIPELINE_NOTION_SCHEMA.md)).
- ✗ **Nunca hay un LLM dentro del camino de publicación.** La creatividad ocurre antes, en Notion: lo que genera contenido con un agente —la réplica de carruseles, o redactar copy por el MCP de Notion— escribe filas, y **una persona las aprueba**. Un LLM no aprueba su propia salida.
- ✗ **Nunca se editan a mano** `❌ postiz_post_id`, `❌ postiz_media`, `❌ release_url` ni `Status = Programado`.
- ✓ **El `❌ postiz_post_id` dice la verdad, no el `Status`.** El estado es para las personas; el ID es para la máquina: si los dos se contradicen, manda el ID.
- ✓ **Una fila = un post = una integración.**

## 6. Riesgos y límites conocidos

### El tamaño de los ficheros importa, pero para Meta, no para Postiz

A Postiz le da igual: con `upload-from-url` los bytes van de Notion a Postiz directamente y se **streamean a disco** con memoria constante ([SYNC §2](./CONTENT_PIPELINE_SYNC.md)). Su único tope, `MAX_URL_UPLOAD_BYTES` = 1 GiB, protege el disco: Notion admite ficheros de hasta 5 GiB.

**Quien tiene que descargarse el fichero es Meta**, del Beelink y por el túnel, y ahí el tamaño manda. El 2026-08-06 dos Trial Reels de 2160×3840 a 38 Mbps (585 MB) no se publicaron nunca: Meta no terminó de descargarlos, el contenedor se quedó en `IN_PROGRESS`, saltó el `startToCloseTimeout` de 10 min de la actividad, Temporal reintentó 3 veces **volviendo a servir los 585 MB** y eso agotó el rate limit de la app; su firma en la tabla `Errors` de Postiz es `activity StartToClose timeout`. Un clip de 1080×1920 a 8 Mbps (18 MB) del mismo día publicó sin problema.

**Lo publicable es ≤1080×1920 y ≲12 Mbps** — Instagram admite hasta 25 Mbps y 300 MB en un reel, pero eso es lo que *acepta*, no lo que nuestro uplink *entrega a tiempo*. Hay dos capas: el sync convierte en el host, con `normalizar-media.sh`, lo que se arregla convirtiendo ([SYNC §2](./CONTENT_PIPELINE_SYNC.md)), y Postiz rechaza al crear el post lo que exige decidir a una persona ([POSTIZ_FORK §5](./CONTENT_PIPELINE_POSTIZ_FORK.md)), también si se sube por la UI. El pipeline de clips de Instalar-Home-Server aplica la misma normalización en su Paso 5.

### ⚠️ El Seagate es USB y `/uploads` es un bind mount

Si `/mnt/seagate` se desmonta, Docker sirve el bind desde un directorio vacío del disco de sistema: **toda la biblioteca de medios desaparece en caliente** —404 en cada imagen— y las subidas nuevas llenan el disco del Beelink en silencio. Es un riesgo de infraestructura, no de este pipeline, pero el pipeline lo hereda.

### Notion es un punto único de fallo

Es la contrapartida de que sea SSoT de verdad. Si no responde, el sync se para entero y avisa el bus ([OPERACION §2](../guides/CONTENT_PIPELINE_OPERACION.md)); si se perdiera el workspace, se perdería todo. La mitigación razonable es una exportación periódica del workspace.

### Rate limits en cascada

`API_LIMIT` = 300 creaciones/hora en Postiz (nuestro, [POSTIZ_FORK §3](./CONTENT_PIPELINE_POSTIZ_FORK.md)) + 100 publicaciones/24 h en Instagram (suyo, innegociable, **por cuenta**).

Con el modelo de colaboradores, **una pieza compartida entre las tres cuentas es una sola fila**. A 3-5 piezas por semana, la ventana de 15 días contiene **~7-11 filas**, más las que sean carrusel o story compartidos, que sí se desdoblan ([NOTION_SCHEMA §2.4](./CONTENT_PIPELINE_NOTION_SCHEMA.md)). Digamos **10-20**. Cada pasada las borra y recrea todas: **~20 creaciones sobre un techo de 300**, que deja margen para las pulsaciones del botón y los reintentos del mismo día.

Crece de forma lineal con ventana × frecuencia, y **por plataforma nueva**: YouTube no se comparte con colaboradores, así que cada pieza que vaya a YouTube es una fila más. Al añadirlo, rehacer esta cuenta **antes**, no después.

> Es el precio de "reescribir siempre en vez de detectar cambios". A esta escala compensa de largo: la alternativa —hashes o `last_edited_time`— es estado que mantener y sincronizar. Si algún día no compensara, el arreglo es comparar antes de recrear, y sólo entonces ([POSTIZ_FORK §3](./CONTENT_PIPELINE_POSTIZ_FORK.md) dice cuándo).

### Marca de agua de CapCut

Algunas plantillas y efectos la añaden al exportar. Publicando a mano se ve; publicando en automático, no. Revisar el máster la primera vez que se use una plantilla nueva.

### Límites conocidos

Lo que el sistema **no** cubre, para que nadie lo descubra a base de sorpresa:

| Límite | Consecuencia |
|---|---|
| **Colaboradores en `graph.instagram.com`** | Se envían ([POSTIZ_FORK §9](./CONTENT_PIPELINE_POSTIZ_FORK.md)), pero no está comprobado que Meta los acepte en la API de Instagram Login: comprobarlo exige publicar de verdad en una cuenta real. Deuda aceptada; se despejará sola en la primera publicación con colaboradores |
| **Más de 100 filas accionables en el sync** | La consulta del sync no pagina: **falla a las claras** si `has_more` es `true`, en vez de sincronizar media cola en silencio. Lee solo los estados vivos, que no se acumulan. La de la retirada, que sí crece, pagina ([RECONCILIACION §4](./CONTENT_PIPELINE_RECONCILIACION.md)) |
| **Notion caído a la hora del cron** | Tras 3 intentos la pasada se detiene y avisa el bus ([OPERACION §2](../guides/CONTENT_PIPELINE_OPERACION.md)) |

## 7. Lo que se decidió NO hacer

Esta sección existe para que el plan no vuelva a crecer. Cada línea fue considerada y descartada.

| Descartado | Por qué |
|---|---|
| Biblioteca en `/srv/media` (Seagate) | Para un equipo es peor: exige LAN o Nextcloud sincronizado por persona. Notion es un login web. |
| Watchers de directorios | Serían el único componente que podría romper algo **en silencio** (escribir sobre un punto de montaje desmontado y llenar el disco del Beelink). |
| Archivo de material en bruto (raw), o tres niveles raw / master / delivery | Es un proyecto legítimo, pero **es otro proyecto**. Archivar no tiene nada que ver con publicar; mezclarlos hace que ninguno arranque. |
| MinIO o cualquier S3 propio | Imposible: el endpoint de R2 está hardcodeado ([POSTIZ_FORK §2](./CONTENT_PIPELINE_POSTIZ_FORK.md)). |
| Hacer configurable el endpoint de S3 | `local` funciona y R2 queda como salida de emergencia. Sería código sin usuario. |
| Mover los medios a R2 | El 403 que parecía motivarlo era el bloqueo de crawlers de IA de Cloudflare, no una limitación real: Meta obtiene 200 desde `local` ([POSTIZ_FORK §1](./CONTENT_PIPELINE_POSTIZ_FORK.md)). |
| Subir los ficheros por multipart desde n8n | Choca con el límite de 100 MB del Cloudflare Tunnel, y ningún reel real pasa ([SYNC §2](./CONTENT_PIPELINE_SYNC.md)). |
| **Modelo de cola** (procesar una vez y congelar) | No propaga las ediciones: se edita el copy en Notion y no pasa nada. Se usa reconciliación ([SYNC](./CONTENT_PIPELINE_SYNC.md)). |
| Quitar la pasada de recuperación y fiarlo todo al webhook | La entrega del webhook es best-effort y sin reintento ([RECONCILIACION §1](./CONTENT_PIPELINE_RECONCILIACION.md)). |
| `type: 'update'` de Postiz | Delete+create tiene semántica inequívoca y es seguro ([RECONCILIACION §2](./CONTENT_PIPELINE_RECONCILIACION.md)). |
| Añadir aprobación o campañas **a Postiz** | Es reconstruir Notion, peor y con código. Rompería además que Postiz sea sustituible (§2). |
| Derivar el margen de seguridad del horario del cron | Falso sentido de seguridad: el botón dispara a cualquier hora ([SYNC §3](./CONTENT_PIPELINE_SYNC.md)). |
| Un índice único para evitar duplicados | El borrado blando de Postiz lo convierte en una forma de impedir crear ([RECONCILIACION §3](./CONTENT_PIPELINE_RECONCILIACION.md)). |

## 8. Fuentes

**Código de este repositorio** (autoridad para todo lo relativo a Postiz):
`upload.factory.ts` · `cloudflare.storage.ts` · `local.storage.ts` · `upload.interface.ts` · `app.module.ts` · `throttler.provider.ts` · `instagram.provider.ts` · **`instagram.standalone.provider.ts`** · `instagram.media.rules.ts` · `instagram.dto.ts` · `create.post.dto.ts` · `media.dto.ts` · **`valid.url.path.ts`** · `has.extension.ts` · `custom.upload.validation.ts` · `get.posts.dto.ts` · `posts.service.ts` · `posts.repository.ts` · `media.repository.ts` · `webhooks.repository.ts` · `webhooks.controller.ts` · `post.activity.ts` · **`post.workflow.v1.0.6.ts`** · `public.integrations.controller.ts` · `schema.prisma`

**Fuera del repositorio:** los workflows de n8n, exportados en `/opt/homeserver/n8n-workflows/` ([INVENTARIO §1](../reference/CONTENT_PIPELINE_INVENTARIO.md)), y el calendario de Notion, `collection://186a2405-a123-81dc-832f-000b82a65c0c`.

**Externas:**
- [Notion — Retrieving existing files](https://developers.notion.com/docs/retrieving-files) (caducidad de 1 h)
- [Notion — Working with files and media](https://developers.notion.com/docs/working-with-files-and-media) (5 GiB por fichero)
- [Meta — IG User Media reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/)

> **Sobre la documentación pública de Postiz:** describe un Postiz distinto al que corremos. Los límites de rate, el comportamiento de `upload-from-url` y la existencia de webhooks **no coinciden** con este fork. Ante una discrepancia, manda el código.
