# Archivo de medios en Google Drive

> **Qué es esto:** las dos pasadas nocturnas que copian a Google Drive los medios de Postiz —un espejo del disco entero y un archivo ordenado de lo publicado—, y por qué están hechas así.
> **Relacionado:** [CONTENT_PIPELINE_NOTION_POSTIZ.md](./CONTENT_PIPELINE_NOTION_POSTIZ.md) §4.7 · [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md)

## 1. Por qué existe

Para lo que pasa por el pipeline, el máster vive en Notion y la copia de Postiz en el Seagate es caché. Aun así quedan tres huecos que Notion no cubre:

| Hueco | Consecuencia sin archivo |
|---|---|
| Una sola copia de cada máster | Si se archiva una fila en Notion, sus ficheros se van con ella |
| Notion no se puede recorrer | No hay forma de ver «todo lo de CITEM en 2026» |
| Lo publicado fuera de Notion no tiene fila | Su única copia es la del Seagate |

El tercero no es teórico: el 2026-08-04, 9 posts publicados desde la UI de Postiz ya habían perdido sus ficheros por la purga de la caché. Con `MEDIA_RETENTION_DAYS = 3650` la purga por antigüedad ya no alcanza lo publicado ([MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md)), pero eso sigue dejando una sola copia en un disco USB. Este archivo pone la segunda fuera del servidor.

## 2. Las dos pasadas

| | Espejo · **02:40** | Archivo curado · **02:55** |
|---|---|---|
| Script | `postiz-respaldo-drive.sh` | `postiz-archivo-drive.py` |
| Qué copia | **Todo** `/mnt/seagate/postiz-media`, tal cual | Lo que Postiz tiene como `PUBLISHED`, ordenado por cuenta y pieza |
| Para qué | Que exista una segunda copia. No se navega | Encontrar una pieza al cabo de un año |
| Destino | `#POSTIZ/Respaldo técnico/` | `#POSTIZ/Publicado/` |
| Nombres | Los del disco (`AAAA/MM/DD/<hex>.<ext>`) | `01.jpg`, `02.jpg`… + `post.txt` |
| Enlace en Notion | No | Sí, en `❌ drive_url` |

```
40 2 * * *  postiz-respaldo-drive.sh 2>>/var/log/postiz-archivo.log || alertar.sh postiz-respaldo …
55 2 * * *  (carga /opt/homeserver/.env; postiz-archivo-drive.py >/dev/null 2>>/var/log/postiz-archivo.log) || alertar.sh postiz-archivo …
```

- **Si una de las dos sale con error, cron llama a `alertar.sh`** (Instalar-Home-Server, `server/ops/`), que abre una incidencia en el bus: la diagnostica el triage, y solo avisa a Dustin si es grave.
- **El `>/dev/null` del archivador no es un descuido:** el script ya escribe él mismo en el log, y redirigir también su salida estándar duplicaría cada línea. El `stderr` se conserva.
- **Log común:** `/var/log/postiz-archivo.log`, con rotación semanal en `/etc/logrotate.d/postiz-archivo`.
- **Van antes que el backup diario (04:00) y que el sync de Notion (06:00)**, para no solaparse con ellos.

**Por qué en el host y no en n8n:** n8n corre en Docker sin `rclone`, y meterlo ahí acoplaría el orquestador a una herramienta de sistema para una tarea que puede fallar sin afectar a nada. Es la convención del servidor para este tipo de tareas: script en `/opt/homeserver/scripts/` más una línea de `crontab`.

## 3. El espejo

**Es tonto a propósito:** no decide qué merece guardarse, copia el disco entero. Un espejo selectivo depende de un diagnóstico, y el diagnóstico puede equivocarse: un análisis dio por «huérfanos» 11 ficheros de los que 10 eran la biblioteca de medios, usada a propósito ([MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md)).

> ### ⚠️ `rclone copy`, nunca `sync`
> `sync` borra en destino lo que falte en origen: con el Seagate desmontado, la fuente parecería vacía y se llevaría el respaldo entero. `copy` no borra nada, y conservar lo que se borró del disco es justo lo que permite recuperar un borrado accidental.

Antes de copiar nada, el script comprueba que el directorio de origen existe y tiene ficheros, y que el remoto responde y ve la carpeta destino. Si falla cualquiera de las tres, sale con código 1 sin copiar. Un cerrojo (`flock`) impide dos copias a la vez.

## 4. El archivo curado

### Qué entra

Todo post de Postiz con `state = 'PUBLISHED'` y sin `parentPostId` (los comentarios no son piezas), de cualquier integración: tenga fila en Notion o no. Un post sin ficheros se salta.

### De dónde salen los bytes: del Seagate, nunca de Notion

1. **Notion no tiene todo el material:** lo publicado fuera del pipeline y la biblioteca de medios no tienen fila.
2. **Leer de Notion ataría el archivo a lo que protege:** si alguien archiva una fila antes de la pasada, el máster desaparecería de los dos sitios a la vez.
3. **Las URLs de Notion caducan en 1 hora;** el disco es lectura local, sin API ni cuota.

Si un fichero ya no está en el disco, no se inventa nada: se anota en el log y en la sección `FICHEROS PERDIDOS` del `post.txt`.

### De dónde salen los metadatos: de la base de Postiz

| Dato | Origen |
|---|---|
| Ficheros y su **orden** | `Post.image` (JSON de `MediaDto[]`) |
| Nombre de la carpeta de cuenta | Mapa `integrationId` → nombre, en la cabecera del script |
| Línea `Cuenta:` de `post.txt` | `Integration.name`, completo |
| Copy | `Post.content` |
| Fecha | `Post.publishDate`, en hora de Madrid |

Notion aporta el título de la pieza (`Name`), el `Tipo` y el `first_comment`, y recibe el enlace de vuelta en `❌ drive_url`.

### Estructura

```
Publicado/
  CITEM/
    2026-08/
      2026-08-04 kinda chic/
        01.jpg  02.jpg  03.jpg  04.jpg  05.jpg
        post.txt
```

- **Carpeta de cuenta:** sale del mapa por `integrationId`, no de `Integration.name` ni de la propiedad `cuenta`. Si no, los posts hechos a mano y los del pipeline de una misma cuenta acabarían en dos carpetas distintas. El mapa incluye la integración de TikTok como `Dustin Calderón (TikTok)`, porque su nombre en Postiz es idéntico al de la cuenta de Instagram. Una integración que no esté en el mapa se archiva con su nombre recortado y deja un `AVISO` en el log para que se añada.
- **Título:** el `Name` de la fila de Notion; sin fila, las seis primeras palabras del copy; sin copy, la hora (`HHMM`). La cuenta se recorta a 40 caracteres y el título, a 70.
- **Ficheros numerados con ceros** (`01`…`10`), para que el orden del carrusel se vea en cualquier explorador. Los nombres originales van en `post.txt`.

### `post.txt`

```
Pieza:      kinda chic
Cuenta:     <Integration.name>
Publicado:  2026-08-04 20:40 (Europe/Madrid)
Instagram:  <permalink>
Tipo:       Carrusel                          ← solo con fila en Notion
Notion:     https://www.notion.so/<page_id>   ← solo con fila en Notion
Post ID:    <Post.id>

--- copy ---
--- primer comentario ---
--- ficheros, en orden de carrusel ---
01.jpg  145513 B  <-  <nombre original>
```

El `Post ID:` es lo que lee la guarda de colisión (abajo).

### Cómo sabe qué está ya archivado

- **Pieza con fila en Notion:** `❌ drive_url` con valor = archivada. Es a la vez el registro y el enlace de vuelta.
- **Pieza sin fila:** su `Post.id` en `/opt/homeserver/scripts/.postiz-archivo-web.json`. Se escribe de forma atómica (temporal en el mismo directorio, `fsync` y `os.replace`). Si no se puede leer, la pasada sale con código 2 y deja el fichero donde está: tratarlo como vacío volvería a subir todas las piezas y duplicaría carpetas en Drive.

**Para rearchivar una pieza** (por ejemplo, si alguien borra su carpeta en Drive): vaciar su `❌ drive_url`, o quitar su `Post.id` del registro local. La siguiente pasada la rehace.

### Guardas

Cada una cierra un camino en el que el script diría `OK` mientras pierde trabajo. Cuando salta una, esa pieza cuenta como fallo, las demás siguen y la pasada sale con código 1.

- **Colisión de carpeta.** Dos piezas de la misma cuenta, del mismo día y con títulos que truncan igual dan la misma ruta, y `rclone copyto` sobrescribiría los másters de la primera. Si la carpeta ya tiene un `post.txt` con otro `Post ID:`, no se toca. La salida es renombrar una de las dos piezas en Notion.
- **Verificación después de copiar.** Se relee la carpeta en Drive: faltar un fichero es un fallo, y **sobrar** también, porque indica restos de otra pieza o de otra pasada.
- **La escritura en Notion se relee.** Si `❌ drive_url` no quedó guardado, la pieza cuenta como fallo; si no, se volvería a subir cada noche sin que nadie lo viera.
- **Un cerrojo** (`/var/lock/postiz-archivo.lock`) impide dos pasadas a la vez.

La consulta a Notion pagina, así que no tiene límite de filas.

`--seco` hace la pasada completa sin escribir en Drive ni en Notion:

```bash
set -a && . /opt/homeserver/.env && set +a && python3 /opt/homeserver/scripts/postiz-archivo-drive.py --seco
```

**Latido opcional.** `latido()` avisa a un monitor Push de Uptime Kuma al terminar cada pasada, solo si existe `POSTIZ_ARCHIVO_PING_URL` en `/opt/homeserver/.env`. Sin esa variable no hace nada. `--seco` no late: una pasada de prueba no debe dar el monitor por sano.

## 5. Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Los dos scripts | `/opt/homeserver/scripts/` en el Beelink, y copia en [`scripts/`](./scripts/). **Al tocar uno, se actualizan las dos copias** y se comparan con `md5sum`: `/opt/homeserver/scripts/` no entra en el backup diario |
| Registro de piezas sin fila | `/opt/homeserver/scripts/.postiz-archivo-web.json` |
| Log | `/var/log/postiz-archivo.log` |
| Remoto de rclone | **`gdrive-work`** = `dustin@dustincalderon.com` (Workspace) |

**La cuenta importa.** El remoto antiguo `gdrive` (cuenta de Gmail) no ve las carpetas de Workspace y responde **404**, que se lee como «la carpeta no existe» y no como «esta cuenta no la ve».

**Carpetas destino**, en `Mi unidad / #Areas / #Dustin Calderon / 03. Contenido RRSS / #POSTIZ /`:

| Carpeta | ID |
|---|---|
| `03. Contenido RRSS` (contenedor) | `1VVXxoeBeASaTCGN8LSVMC63goH0unqLE` |
| `#POSTIZ / Publicado` | `1RkW1J4lc2X-qmOTqrRsJwQc1uuDMMN6G` |
| `#POSTIZ / Respaldo técnico` | `1RmJokTxS7zRGqAWh76J6EG7oY7grXh6A` |

**Los scripts apuntan al ID, no a la ruta:** mover o renombrar una carpeta en Drive cambia la ruta y no el ID.

## 6. Lo que no hace

| No hace | Por qué |
|---|---|
| Tocar el camino de publicación | Si falla, sólo se pierde una noche de archivo |
| Borrar nada, en el disco ni en Drive | Copia y nada más. La limpieza del disco es de [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md) |
| Leer bytes de Notion | §4 |
| Sustituir a Notion como máster | Drive es copia. Para lo que pasa por el pipeline, Notion sigue siendo la fuente de verdad |
| Rescatar los ficheros que la purga borró antes de subir la retención | Ya no están en el disco; su `post.txt` lo documenta en `FICHEROS PERDIDOS` |

## 7. Decisiones

| Decisión | Valor | Quién |
|---|---|---|
| Retención de la caché | `MEDIA_RETENTION_DAYS = 3650` | Usuario, 2026-08-04 |
| Cuenta de Drive | `gdrive-work` (Workspace) | 2026-08-04 |
| Destino | `#Areas/#Dustin Calderon/03. Contenido RRSS/#POSTIZ/`, con `Publicado/` y `Respaldo técnico/` | Usuario, 2026-08-04 |
| Estructura del curado | `Publicado/<cuenta>/<AAAA-MM>/<fecha titulo>/` | Usuario, 2026-08-04 |
| Alcance del curado | Solo lo publicado | Usuario, 2026-08-04 |
| Alcance del espejo | El disco entero, sin selección | 2026-08-04 |
| Origen de los bytes | Seagate, sin reserva a Notion | 2026-08-04 |
| Origen de los metadatos | Base de Postiz; Notion solo pone el título | 2026-08-04 |
