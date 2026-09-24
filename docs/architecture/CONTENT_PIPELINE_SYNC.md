# Pipeline de contenido — el sync de n8n: reconciliación, no cola

> **Qué es esto:** cómo el worker de n8n lleva cada fila de Notion a Postiz — sus disparadores, qué hace con una fila, cómo sube los ficheros, el margen de seguridad y qué pasa cuando un workflow falla.
> Lo que evita duplicados y huérfanos (cierre del bucle, borrar y recrear, identidad externa, retirada) está en [CONTENT_PIPELINE_RECONCILIACION.md](./CONTENT_PIPELINE_RECONCILIACION.md). El dibujo nodo a nodo, en [CONTENT_PIPELINE_DIAGRAMS.md](./CONTENT_PIPELINE_DIAGRAMS.md).
>
> **Parte de:** [CONTENT_PIPELINE_NOTION_POSTIZ.md](./CONTENT_PIPELINE_NOTION_POSTIZ.md), que tiene el mapa de todos los documentos del pipeline.

---

**Notion declara cómo deben ser los próximos 15 días. El sync hace que Postiz coincida.**

No hay cola que procesar ni estado que recordar. La consecuencia importante: **las ediciones en Notion se propagan solas.** No hace falta detectar qué cambió, ni comparar hashes, ni guardar `last_synced_at`. Cada pasada reescribe la ventana.

## 1. Un camino, dos disparadores

```
   cron 06:00 Europe/Madrid ──┐
                              ├──► turno ──► Notion: leer cola ──► pasada completa
   botón "Sync now" ──────────┘
```

**Por qué las 06:00 de España:** es una franja muerta en los dos mercados. En España es de madrugada; en LATAM es entre medianoche y las 2-3 de la mañana. Nunca se publica a esa hora, así que el cron nunca coincide con una publicación.

**Regla innegociable: nunca dos implementaciones.** El botón **no** manda una fila: su webhook desemboca en la **misma** consulta a Notion que el cron, y ambos releen la cola entera y hacen la pasada completa. Las propiedades que Notion adjunta al pulsar el botón **se descartan a propósito**. No hay un camino "de una fila" que pueda divergir del camino "de N filas", porque sólo hay uno; cuesta una consulta a Notion de más por pulsación, que es gratis.

**Cómo se configura el botón.** Es una propiedad de tipo **Botón** en el calendario ([NOTION_SCHEMA §8](./CONTENT_PIPELINE_NOTION_SCHEMA.md)), con la acción *Enviar webhook*. Hay dos URLs válidas y ambas desembocan en el mismo nodo:

| URL | Auth | Respuesta | |
|---|---|---|---|
| `…/webhook/` + `N8N_SYNC_IG_BUTTON_PATH` | el secreto va en la ruta | **`202` al instante** | **← la que usa el botón** |
| `…/webhook/postiz-sync-ig` | cabecera `X-Sync-Token` | `200` al terminar la pasada | para scripts y `curl`. Los del Beelink llaman a n8n en local, `http://127.0.0.1:5678/webhook/postiz-sync-ig`: Cloudflare corta con `524` una respuesta de más de 125 s, y una pasada larga o que espera turno los pasa aunque termine bien |

El apartado **«Contenido» del botón se deja vacío** — el workflow no lee el cuerpo, relee el calendario por su cuenta.

> ### ⚠️ El botón responde antes de trabajar
> Notion corta la petición del botón **mucho antes** que el túnel y muestra «no se pudo ejecutar el botón: se agotó el tiempo de espera». Medido: pasadas de 21 s pasaban, una de 37 s ya no; los 100 s del edge de Cloudflare ni se rozan, así que **no es Cloudflare**. Y como el botón descarta el cuerpo de la respuesta, esperar no aporta nada.
>
> El nodo del botón usa `responseMode: responseNode` y responde **`202`** en ~140 ms; la pasada sigue por detrás. El resultado autoritativo se escribe donde siempre: en la fila de Notion (`Status`, `❌ error_log`).
>
> **La ruta con cabecera es síncrona a propósito.** Los scripts y la batería de pruebas disparan y leen el resultado en la misma llamada. No rompe la regla de «nunca dos implementaciones»: los dos webhooks entran al **mismo** turno y a la misma `Notion: leer cola`, y hacen exactamente el mismo trabajo — lo que difiere es el contrato de transporte de cada llamante.

**Las pasadas van de una en una, en el orden en que llegan.** Con respuesta inmediata es fácil lanzar varias a la vez —Notion lanza la automatización **una vez por cada fila tocada**—, y dos pasadas a la vez deciden cada una con lo que leyeron al empezar: el `Error` de una puede pisar el resultado de otra posterior, y una edición hecha con otra pasada en marcha puede no llegar a Postiz. Por eso, antes de leer Notion, cada pasada pregunta al Beelink cuántas pasadas anteriores siguen en marcha ([`turno-sync.sh`](./scripts/turno-sync.sh)) y espera de 10 en 10 s mientras no sean 0.

- La consulta va **por la clave SSH restringida**, no por la API de n8n, para no guardar en n8n una clave que lo abre entero.
- El límite de concurrencia de n8n no sirve: es de toda la instancia.
- Una ejecución de más de 30 minutos no cuenta, para que una colgada no pare el sync para siempre.
- Si no se puede saber el turno, la pasada falla y avisa el bus (§5); no sigue a ciegas.

Duplicar tampoco puede, y no por el turno: el margen de seguridad (§3) cubre las filas que ya tienen `❌ postiz_post_id`, y la identidad externa ([RECONCILIACION §3](./CONTENT_PIPELINE_RECONCILIACION.md)) hace que la segunda creación de una fila nueva devuelva el post de la primera.

> El secreto en la ruta acaba en los logs de ejecución de n8n y del túnel; en una cabecera, no, y la UI de Notion **sí** admite encabezados personalizados. Cambiarlo es editar la automatización del botón. Sobre HTTPS la ruta no viaja en claro.

**Cómo se distingue una pulsación del botón en n8n:** la petición llega con `user-agent: NotionAutomation` y un cuerpo `{"source":{"type":"automation","automation_id":…}}`. El cron, en cambio, no pasa por ningún nodo webhook.

## 2. Qué hace el subflow con una fila

| Situación | Acción |
|---|---|
| `Plataforma` no contiene Instagram | Invisible para el worker |
| `Status` vacío | No crear nada — **la retirada lo borra de Postiz si existía** ([RECONCILIACION §4](./CONTENT_PIPELINE_RECONCILIACION.md)) |
| `Status` = `Publicado` | **No tocar jamás** |
| Dentro del margen de seguridad **y ya tiene `❌ postiz_post_id`** (§3) | **Saltar** — se reporta en la ejecución, **no** se escribe en `❌ error_log` (ver nota) |
| `❌ postiz_post_id` vacío | Crear |
| Tiene `❌ postiz_post_id`, aún no publicado | **Borrar y recrear** ([RECONCILIACION §2](./CONTENT_PIPELINE_RECONCILIACION.md)) |
| `❌ postiz_media` con los mismos ficheros, en el mismo orden | No re-subir los assets |
| `Fecha` sin hora | `Error` — nunca se adivina la hora |
| `Fecha` ya pasó y nunca se sincronizó | `Error` + motivo |

> ⚠️ La segunda fila **no es "ignorar y seguir"**. Sin la retirada, vaciar `Status` de una fila ya sincronizada deja el post programado en Postiz y **sale publicado igual**. Las dos partes son una sola.

> ### ⚠️ El orden de las puertas importa: primero la hora, después la ventana
> Notion devuelve una fecha sin hora como `2026-08-10` a secas, y `new Date('2026-08-10')` la interpreta como **medianoche UTC**. Si el margen se evalúa antes que la comprobación de hora, esa fila puede caer dentro del margen y salir como «saltar» — es decir, **la fila sin hora nunca llega a `Error`**, que es justo lo contrario de la regla.
>
> El orden implementado es: **validaciones estructurales** (hora, offset, cuenta, copy, media, colaboradores) → y sólo con una fecha válida, **ventana → pasado → margen**. Cómo se escribe `Fecha` por API: [NOTION_SCHEMA §5](./CONTENT_PIPELINE_NOTION_SCHEMA.md).

> **Sobre el margen y `❌ error_log`:** saltar por el margen de seguridad no es un error, es el sistema funcionando. Escribirlo en `❌ error_log` dejaría un mensaje de avería en una fila sana y acabaría entrenando al equipo a ignorar ese campo. Se reporta en la ejecución de n8n; la fila se recoge sola en la siguiente pasada.

Superadas las puertas, cada fila es **un solo post**, así que el subflow es lineal:

```
1. valida  ≤10 items · reglas de NOTION_SCHEMA §4
           colaboradores ⇒ ni carrusel ni story
2. resuelve `cuenta` ──► integration.id                  (NOTION_SCHEMA §2.1)
3. si tiene ❌ postiz_post_id y no está publicado ──► DELETE primero
4. si `❌ postiz_media` no es de estos mismos ficheros, en este orden:
      pide a Notion la URL FRESCA de cada fichero   ← nunca una guardada
      SSH al host ──► normalizar-media.sh <url>
        ├─ mide con ffprobe (~2 s, sin descargar)
        ├─ clasifica imagen/video por LÍNEA DE TIEMPO
        │    duration ≥ 1 s o nb_frames ≥ 2 ⇒ video; si no, imagen
        ├─ lo que Instagram publica tal cual: upload-from-url
        │    foto JPEG o PNG de hasta 8 MiB; video MOV/MP4, H.264/HEVC,
        │    23-60 fps, AAC ≤48 kHz, ≤1080×1920, ≤12 Mbps, ≤300 MB
        ├─ lo demás: descarga → convierte → re-mide → multipart
        │    foto (HEIC, WebP, AVIF, GIF, >8 MiB) → JPEG ≤1440 px de
        │      ancho, la transparencia sobre blanco
        │    video → MP4 H.264, fps a 23-60, AAC 48 kHz, el bitrate
        │      que cabe en 300 MB (como mucho 8 Mbps); nunca amplía
        │    lo que ffprobe no abre se prueba con heif-convert (HEIC)
        ├─ las dos subidas por 127.0.0.1:4007, sin Cloudflare
        ├─ los bytes NO pasan por n8n en ningún caso
        └─ si el script falla (exit≠0): el nodo SSH NO lanza error —
           devuelve {code,stdout,stderr}— así que el veredicto de cada
           asset es su `code`. Se agrega en «Recolectar media» y el IF
           mira el agregado, no cada item (ver recuadro abajo).
      └──► ESCRIBE ❌ postiz_media                      [write 1]
5. POST /public/v1/posts                  (cuerpo exacto: API_POSTIZ)
      type                        = modo
      posts[0].externalId         = id de la página de Notion
      value[0].content            = copy
      value[0].image[]            = ❌ postiz_media
      value[1].content            = first_comment        (si lo hay)
      settings.collaborators[]    = colaboradores        (si los hay)
      └──► ESCRIBE ❌ postiz_post_id                        [write 2]
           Status = Programado           si modo = programar
           Status = En Postiz (borrador) si modo = borrador

   si el paso 5 falla:
      Status = Error · ❌ error_log = motivo
      y si el media se subió EN ESTA pasada:
        DELETE /public/v1/media/:id  +  vaciar ❌ postiz_media
```

El cuerpo exacto del `POST`, con los campos que dan 400 si se olvidan: [API_POSTIZ](../reference/CONTENT_PIPELINE_API_POSTIZ.md).

Las dos escrituras van separadas: guardar `❌ postiz_media` en cuanto sube hace el proceso **reanudable a mitad**, y evita volver a subir un reel en cada resincronización.

> ### ⚠️ Por la puerta pasa todo el media, y no sabe qué le llega
> El subflow manda un asset por invocación **sin saber qué es**, así que el script clasifica. Si clasificara mal, cada foto saldría convertida en un MP4 de **un fotograma** y se publicaría como video. **El único discriminador fiable es la línea de tiempo**: `duration ≥ 1 s` o `nb_frames ≥ 2`. Lo que **no** sirve:
>
> | Señal | Por qué falla |
> |---|---|
> | El contenedor | MOV/MP4 es también el de un HEIC |
> | `avg_frame_rate` | vale `25/1` hasta en un PNG |
> | El códec | `hevc` es un video H.265 y también una foto HEIC |
> | `nb_frames == 1` | en PNG y JPEG es `N/A`, no `1` |
> | `duration` a secas | `N/A` en PNG/WebP pero **0,04 s** en JPEG — hacen falta las dos |
>
> La `duration` se pide al **contenedor**, no al stream: el demuxer de imagen le inventa al stream un fotograma nominal de 0,04 s.
>
> **Se convierte solo lo que Instagram no publica tal cual**, contra la referencia de Meta (IG User Media), y una medida ausente cuenta como que no cumple: un video demasiado pesado no llega a publicarse ([NOTION_POSTIZ §6](./CONTENT_PIPELINE_NOTION_POSTIZ.md)). El ffmpeg de Ubuntu (6.1) no abre un HEIC de iPhone, así que lo que ffprobe no abre se prueba con `heif-convert` (paquete `libheif-examples`); si tampoco lo reconoce, se **aborta** con el motivo. La conversión deja la foto derecha según su orientación (comprobado con un JPEG y un HEIC de iPhone girados) y no copia sus metadatos.
>
> **PNG sube tal cual** aunque la referencia diga «Format: JPEG»: Instagram publica PNG con normalidad (son las láminas de todos los carruseles replicados). Las demás fotos se convierten: la referencia solo admite JPEG, y Meta rechaza un formato que no admite con el error 2207005.
>
> Lo que exige decidir a una persona —la duración de un video, la proporción de una foto— no se convierte: lo rechaza Postiz al crear el post ([POSTIZ_FORK §5](./CONTENT_PIPELINE_POSTIZ_FORK.md)). La prueba del script es [`test_normalizar-media.sh`](./scripts/test_normalizar-media.sh) ([OPERACION §1](../guides/CONTENT_PIPELINE_OPERACION.md)).

> ### ⚠️ El veredicto es de la fila, no de cada asset
> Un IF **por item** con 10 assets y 2 correctos partiría la ejecución en dos ramas vivas: n8n ejecuta primero la buena, y una excepción ahí mata la ejecución antes de que la rama de error escriba nada. La fila se quedaría en `Listo`, con `❌ error_log` vacío y medios huérfanos — un fallo invisible desde Notion, que es peor que el fallo.
>
> Por eso la agregación va **antes** del IF: `Recolectar media` recibe los N items del SSH, no lanza nunca, y emite **un solo item** con `n_fallos`, el `media_json` y los `media_ids` que sí se subieron. El IF mira `n_fallos == 0`. Un carrusel a medias no se publica, así que el veredicto no puede ser por asset.
>
> Ese agregado es además lo que hace **reclamable el huérfano parcial**: lo subido en una pasada que fracasa entra en `media_ids` y lo borra la cadena de limpieza de abajo.

> ### Por qué el worker borra su propio media al fallar
> La limpieza automática sólo hace candidato lo que aparece en un post **publicado** ([POSTIZ_FORK §7](./CONTENT_PIPELINE_POSTIZ_FORK.md)). Un fichero subido y nunca publicado **no lo recoge nadie**. Sin este paso, cada fila abandonada tras un fallo dejaría un reel de 150 MB en el Seagate para siempre.
>
> **Sólo se borra lo subido en esa misma pasada.** Si el media venía reutilizado de un intento anterior ([NOTION_SCHEMA §7.1](./CONTENT_PIPELINE_NOTION_SCHEMA.md)), borrarlo dejaría `❌ postiz_media` apuntando a la nada. Y cuando se borra, se vacía también `❌ postiz_media`, para que el reintento vuelva a subir. Usa `DELETE /public/v1/media/:id`, que el fork añadió a la API pública ([POSTIZ_FORK §10](./CONTENT_PIPELINE_POSTIZ_FORK.md)).

> **No hay fan-out.** Una pieza compartida entre cuentas es un post con colaboradores ([NOTION_SCHEMA §2.4](./CONTENT_PIPELINE_NOTION_SCHEMA.md)), no N posts. Eso mantiene el 1:1 con Postiz —un ID, un estado, un `❌ release_url`— y elimina cualquier necesidad de estados parciales o de una tabla intermedia. Los carruseles y stories compartidos, que Instagram no permite compartir, son filas independientes, y cada una sigue siendo un post.

> ### ⚠️ Por qué `upload-from-url` y no multipart desde n8n
>
> `postiz.dustincalderon.com` está detrás de un **Cloudflare Tunnel**, y el edge de Cloudflare corta los **cuerpos de petición** a 100 MB. Medido variando sólo el tamaño, con el mismo host, la misma cabecera y el mismo path:
>
> | Cuerpo | Resultado |
> |---|---|
> | 5 MB | `401` — llega al origen |
> | 90 MB | `401` — llega al origen |
> | **100 MB** | **`413`** · `server: cloudflare` |
> | **150 MB** | **`413`** tras aceptar 1,7 MB |
>
> No llega al Beelink: lo corta el edge. Nada que ver con R2 ([POSTIZ_FORK §2](./CONTENT_PIPELINE_POSTIZ_FORK.md)): es el túnel, no el disco.
>
> Con `upload-from-url` el cuerpo que entra son ~100 bytes de JSON y **es Postiz quien sale a internet** a por el fichero; la salida no tiene ese límite. Y desde el host, por `127.0.0.1:4007`, ni siquiera pasa por el túnel. Beneficios en cadena: no hay tope de 100 MB, los bytes **no pasan por n8n** (sin riesgo de memoria en n8n) y es un viaje en vez de dos. Medido de punta a punta: reel de 150 MB de Notion a Postiz en **9 s**, con `md5` idéntico en destino y `206` para `facebookexternalhit/1.1`.
>
> ### `upload-from-url` va por streaming: memoria constante
>
> Este proceso **también corre el orchestrator**, así que una subida que cargara el fichero entero en memoria se llevaría por delante la publicación programada. El tipo se detecta con `fileType.stream()` —lee la cabecera y sigue emitiendo todos los bytes— y se vuelca a disco con `pipeline()`. Medido: un fichero de 672 MB movió la memoria de Postiz de 2130 MB a 2132 MB, en 8 s y con `md5` idéntico (los 2,1 GB son la línea base de los tres procesos).
>
> El único límite es **`MAX_URL_UPLOAD_BYTES`** (1 GiB en producción), y existe para que una URL equivocada no llene el disco — no para acotar la RAM. Un fichero de 1,4 GB da `400` con mensaje legible y **sin dejar fichero parcial**. **n8n no tiene sonda de tamaño propia**: el límite vive en un solo sitio, el que puede aplicarlo, y si Postiz lo rechaza su mensaje llega tal cual a `❌ error_log`.
>
> `uploadStream` es **opcional** en `IUploadProvider`: quien no pueda streamear —R2 necesitaría multipart— no lo implementa y el llamante cae al camino con buffer.

## 3. El margen de seguridad — obligatorio

**No se borra y recrea ninguna fila cuyo `publish_at` esté dentro de los próximos 5 minutos.**

Borrar y recrear abre una ventana en la que el post no existe en Postiz. Hacerlo cerca de la hora de publicación es una carrera contra el orchestrator, con dos finales malos: el post se pierde, o se recrea con una fecha ya pasada y el comportamiento deja de ser predecible.

> **Este guardarraíl vive en el subflow, no en el horario del cron.** La hora del cron ya garantiza que **el cron** nunca colisione con una publicación. Pero **el botón se dispara cuando alguien lo pulsa**, y antes o después alguien va a tocar un post minutos antes de que salga. El guardarraíl existe por el botón.

> ### Por qué 5 minutos
> La ventana real que protege el margen es de **~2 segundos** (el hueco DELETE→POST) más la duración de una pasada (~11 s medidos). Un margen de horas no protege más y tiene un coste diario: reprogramar algo dentro del margen exige cirugía manual (borrar el post por API y limpiar el puntero). Con 5 min, una edición en Notion se propaga casi hasta la hora de publicar, y si el create falla tras el delete, la rama de error del subflow lo escribe en `❌ error_log`.

Si una fila cae dentro del margen, el sync **no hace nada** y lo anota. Si hay que cambiar algo a menos de 5 minutos de publicar, se hace a mano en Postiz — es la única excepción a "nunca se aprueba en Postiz", y es una excepción de emergencia.

> ### ⚠️ El margen sólo se aplica a lo que ya está en Postiz
>
> La condición es `dentro del margen` **Y** `❌ postiz_post_id` no vacío. Sin la segunda mitad el guardarraíl se vuelve del revés y **come filas nuevas**: una fila aprobada a minutos de su hora cae en el margen y se salta; en la siguiente pasada la fecha está **más cerca**, así que se vuelve a saltar; nunca se crea, y cuando la fecha pasa termina en `Error` con el motivo equivocado.
>
> Una fila sin `❌ postiz_post_id` no tiene nada que borrar: crearla es una sola operación atómica y no hay carrera posible. Aplicarle el margen no protege nada y rompe el caso más común — aprobar algo para hoy mismo.

> ### La hora programada es cuándo *empieza* a publicar, no cuándo aparece
>
> Temporal despierta el workflow al segundo exacto, pero publicar en Instagram no es una llamada: Postiz crea un contenedor por imagen y **sondea el estado de cada uno hasta que Meta los da por procesados** (`waitForContainer` de `instagram.provider.ts`). Los contenedores se crean en paralelo, así que manda el más lento.
>
> - El sondeo pregunta cada 30 s y **devuelve en cuanto Meta responde `FINISHED`** (o `PUBLISHED`). `ERROR`, `EXPIRED` o una respuesta sin `status_code` lanzan un error legible: no se publica a ciegas.
> - Está **acotado a 8 minutos**. `postSocial` corre en una actividad Temporal con `startToCloseTimeout` de 10 min: sin tope, un contenedor lento agotaría el plazo, Temporal reintentaría y **el vídeo se subiría a Instagram por segunda vez**.
> - Medido con un reel de 19 s y 28 MB: programado a las `14:00:00Z`, Instagram lo sella a las `14:00:32Z` y Postiz lo marca `PUBLISHED` a las `14:00:38`. Un reel pesado tarda más: manda el tiempo que Meta tarde en procesar.
>
> Un rate limit de Meta (`code 4`, «Application request limit reached») llega marcado **`is_transient: true`**, y `handleErrors` honra ese flag y reintenta: 3 reintentos de 5 s. Reduce las pérdidas, **no las elimina**.
>
> Consecuencia práctica: si la pieza tiene que estar visible a una hora concreta, la `Fecha` de Notion se pone unos minutos antes. Y no hay que dar por fallida una publicación hasta pasados unos minutos de su hora.

## 4. La ventana de 15 días

Un post programado para dentro de 20 días **no existe en Postiz todavía**, y eso es correcto: nada se crea antes de tiempo. Entra en la ventana cuando le toca.

El equipo debe saberlo para que nadie se alarme al no encontrar en Postiz algo que sí está en Notion. **Notion es la verdad; Postiz sólo refleja los próximos 15 días.**

## 5. Cuando un workflow falla

Un fallo que el propio workflow maneja se ve en Notion: la fila pasa a `Error` con su `❌ error_log` ([NOTION_SCHEMA §7.1](./CONTENT_PIPELINE_NOTION_SCHEMA.md)). Uno que **no** maneja (Notion no contesta a la consulta de las 06:00, un nodo de código que revienta) para la ejecución entera, y de ese se encargan los reintentos y el aviso:

- **Reintentos.** Todo nodo HTTP que llama a Notion o a Postiz se reintenta 3 veces, con 5 s entre intentos. `POST /public/v1/posts` también: lleva el `externalId` de la fila ([RECONCILIACION §3](./CONTENT_PIPELINE_RECONCILIACION.md)), así que si la primera llegó y solo se perdió la respuesta, la segunda devuelve el mismo post y no lanza otra publicación. En un nodo con salida de error, n8n agota los intentos antes de tomarla. La subida por SSH **no** se reintenta: repetirla subiría el fichero dos veces. La consulta del turno por SSH, que solo lee, sí.
- **Aviso.** Los workflows del pipeline (sync, subflow, retirada, receptor y réplica de carruseles) tienen de *error workflow* «Bus de incidencias · fallos de n8n y caídas de Kuma». Ese workflow encola el fallo en el bus del Beelink por la clave SSH restringida, con origen `n8n-<workflow>`, el nodo y el error. El triage lo diagnostica, y solo avisa a Dustin si es grave. Qué puede pedir esa clave, en [`n8n-ssh-wrapper.sh`](./scripts/n8n-ssh-wrapper.sh).
