# Plan — archivo de másters en Google Drive

> **Estado:** implementado y corriendo. Las dos piezas están en cron y han hecho su primera pasada real, verificada (§7). Sólo queda actualizar el manual de uso de Notion.
> **Fecha:** 2026-08-04
> **Relacionado:** [CONTENT_PIPELINE_NOTION_POSTIZ.md](./CONTENT_PIPELINE_NOTION_POSTIZ.md) §4.7 · §10.3 · [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md)

## 1. El problema, dicho con precisión

La premisa de partida —«los assets no se guardan en ningún sitio»— **es falsa para el
material que pasa por el pipeline**: Notion guarda el máster, y así está decidido
(«Notion es la fuente de verdad, incluidos los ficheros máster»). La copia del Seagate es
caché, y se purgaba a propósito.

Pero hay tres agujeros reales, y uno de ellos estaba activo:

| Agujero | Consecuencia |
|---|---|
| **Una sola copia de cada máster** | Se archiva una fila en Notion y los ficheros se van con ella. No hay red |
| **Notion no es navegable** | Los ficheros viven dentro de filas. No hay forma de recorrer «todo lo de CITEM en 2026» |
| **El material anterior al pipeline no tiene fila en Notion** | Su única copia *era* la caché, y se estaba borrando |

El tercero no era hipotético. Medido el 2026-08-04:

- **9 posts publicados desde la UI ya habían perdido sus ficheros.** Junio es la fecha
  de **subida** de esos ficheros, no la de publicación: dos de esas nueve piezas se
  publicaron ya en julio (2026-07-01 y 2026-07-03).
- **9 posts conservaban 201,0 MB** (191,7 MiB) en **18 ficheros distintos** —19
  referencias, porque un `.mov` lo comparten dos publicaciones—, cuya purga empezaba el
  **2026-08-05**.

> La cifra que daba antes este documento, **214,5 MB, era falsa por partida doble**:
> contaba dos veces el `.mov` compartido y etiquetaba MiB como MB.

> ### ⚠️ Y por debajo no había ninguna copia de seguridad
> `/opt/homeserver/backup/backup-daily.sh` (cron de las 04:00) hace **sólo volcados de
> bases de datos y configuración**. **Cero menciones a Postiz**: ni sus medios ni su base
> de datos entran en el backup. Ningún cron ni timer de systemd tocaba `/mnt/seagate` — los dos jobs de este plan (§7.1) son los primeros, y **sólo leen y copian**.
>
> Es decir: la caché no era «la copia menos importante», era la **única** copia de una
> parte del material, sin respaldo de ningún tipo, con un job nocturno borrándola.

**Ya aplicado: `MEDIA_RETENTION_DAYS = 3650`.** Para el 2026-08-05 no quedaba margen de
construir nada, así que primero se paró la hemorragia subiendo la retención — verificado
en el historial de Temporal, con la trampa que eso tiene documentada en
[MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md).

Eso **no resuelve el problema, compra tiempo**: sigue habiendo una sola copia, en un
disco USB, sin backup. Este plan es la solución de raíz.

## 2. Qué se construye

**Dos cosas distintas, con destinos distintos.** Mezclarlas fue el error de la primera
versión de este plan: un espejo y un archivo curado no se parecen en nada.

| | `Respaldo técnico/` | `Publicado/` |
|---|---|---|
| Qué copia | **Todo** el disco de medios, tal cual | Sólo lo publicado, ordenado por cuenta y pieza |
| Para qué | Que exista una segunda copia. No se navega | Encontrar una pieza dentro de un año |
| Estructura | La del disco (`AAAA/MM/DD/<hex>.<ext>`) | `<cuenta>/<AAAA-MM>/<fecha titulo>/` |
| Nombres | Los del disco, ilegibles | `01.jpg`, `02.jpg`… + `post.txt` |
| Enlace en Notion | No | **Sí** — `❌ drive_url` (§5) |
| Cómo se hace | `rclone copy` nocturno | Script que lee la base de Postiz (§6) |

> ### El espejo es tonto a propósito
> No decide qué merece guardarse: copia el disco entero. Esa tontería es una virtud —y
> tiene precedente. Un análisis previo clasificó **11 ficheros como huérfanos
> permanentes**; **10 eran la biblioteca de medios**, usada a propósito y sin aparecer en
> ningún post (ver la corrección en
> [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md)). Un espejo selectivo,
> alimentado por aquel diagnóstico, habría dejado fuera justo lo que había que salvar.
>
> El curado sí decide, pero **no borra nada**: sólo elige qué copiar *además*, a otra
> carpeta.

### Estructura de `Publicado/`

```
Publicado/
  CITEM/
    2026-08/
      2026-08-04 kinda chic/
        01.jpg  02.jpg  03.jpg  04.jpg  05.jpg
        post.txt
  Dustin Calderón/
```

`AMORISMO VOL III` está en el mapa de cuentas (§7.1) y **no tiene carpeta**: no ha
publicado nada todavía. Una carpeta de cuenta sólo existe cuando hay una pieza dentro.

Numeración ordinal con ceros (`01`, `02`… `10`) para que **el orden del carrusel se vea
en cualquier explorador de ficheros**, que es el dato que se pierde primero. Los nombres
originales van dentro de `post.txt`.

### `post.txt`

```
Pieza:      kinda chic
Cuenta:     CITEM Conservatorio Iberoamericano de Teatro Musical
Publicado:  2026-08-04 20:40 (Europe/Madrid)
Instagram:  https://www.instagram.com/p/DboOxwfjuQO/
Tipo:       Carrusel
Notion:     https://www.notion.so/<page_id sin guiones>
Post ID:    <Post.id>

--- copy ---
Its kinda chic la verdad, que esperas para ser parte de CITEM?

--- primer comentario ---
(ninguno)

--- ficheros, en orden de carrusel ---
01.jpg  145513 B  <-  1.jpg
...
```

Dos detalles que no son descuidos. El `Cuenta:` lleva el **`Integration.name` completo**,
mientras que la carpeta lleva el nombre corto del mapa (§3, §7.1): el fichero documenta de
dónde salió la pieza, la carpeta agrupa. Y el **`Post ID:`** no está de adorno — es lo que
lee la guarda de colisión antes de escribir sobre una carpeta existente (§7.1).

## 3. De dónde salen los bytes

**Del Seagate. Nunca de Notion.** No es una preferencia de comodidad; es lo único que
resuelve el problema del §1. Razones, por orden de peso:

1. **Notion no tiene el material.** Los 18 posts anteriores al pipeline no tienen fila, y
   la biblioteca de medios de Postiz tampoco existe en Notion. Leer de Notion dejaría
   fuera precisamente lo que sólo tiene una copia.
2. **Leer de Notion haría que el archivo dependiera de la pieza de la que protege.** Si
   alguien archiva una fila antes del job nocturno, el máster desaparecería de los dos
   sitios a la vez. Un backup que se rompe con la misma acción que debía cubrir no es un
   backup.
3. **Las URLs firmadas de Notion caducan en 1 hora.** El disco es lectura local, sin
   caducidad, sin API y sin cuota.
4. **La copia del disco es fiel.** Verificado fichero a fichero en la primera publicación
   real: la copia de Postiz es **md5-idéntica** al original de Notion.

### Los metadatos salen de la base de Postiz, no de Notion

El curado necesita saber qué ficheros forman la pieza, en qué orden, de qué cuenta es y
qué se escribió. Todo eso está en Postiz y **cubre los 19 posts publicados**, con fila en
Notion o sin ella:

| Dato | Origen |
|---|---|
| Ficheros y su **orden** | `Post.image` (JSON de `MediaDto[]`) |
| Cuenta — **nombre de la carpeta** | Mapa `integrationId` → nombre, en la cabecera del script (§7.1). **No** `Integration.name` |
| Cuenta — línea `Cuenta:` de `post.txt` | `Integration.name`, completo y sin recortar |
| Copy y primer comentario | `Post.content` |
| Fecha de publicación | `Post.publishDate` |

**Notion aporta una sola cosa —el título de la pieza— y recibe otra: el enlace de vuelta**
(§5). Nada más.

> ### ⚠️ Se descarta el camino de reserva a Notion
> La primera versión de este plan proponía: si el fichero ya se purgó del disco, bajarlo
> de Notion. **Ya no aplica.** Con `MEDIA_RETENTION_DAYS = 3650` un fichero publicado no
> se purga, así que esa rama **nunca se ejecutaría**: sería código no probado esperando a
> ser el único que corre el día que algo vaya mal. Se elimina del diseño.
>
> Lo que sí queda es el caso sin salida: si un fichero **no está en el disco**, se anota
> como `PERDIDO` en el log y no se inventa nada.

```
¿está en /mnt/seagate/postiz-media?
  sí → rclone copy → Drive
  no → anotar como PERDIDO en el log
```

## 4. Dónde corre, y con qué cuenta de Drive

`n8n` va en Docker y **no tiene `rclone` dentro**. Meter rclone en esa imagen sería
acoplar el orquestador a una herramienta de sistema para una tarea que, por diseño, debe
poder fallar sin que nadie se entere.

El archivador es un **script en el host**, siguiendo la convención que ya usa el
servidor para este tipo de tareas (`/opt/homeserver/scripts/*` + `crontab`):

| | | Estado |
|---|---|---|
| Script | `/opt/homeserver/scripts/postiz-archivo-drive.py` | **✅ Instalado** |
| Cron | `40 2` (espejo) y `55 2` (archivador) — antes del backup diario (04:00) y del sync de Notion (06:00) | **✅ Instalado** (§7.1) |
| Log | `/var/log/postiz-archivo.log` | **✅ Instalado**, con rotación semanal |
| Remoto rclone | **`gdrive-work`** | **✅ Configurado y verificado** |

### La cuenta importa: `gdrive-work`, no `gdrive`

| Remoto | Cuenta | Sirve |
|---|---|---|
| **`gdrive-work`** | **`dustin@dustincalderon.com`** (Workspace) | **Sí.** 0,73 TB usados de 2,20 TB |
| `gdrive` (antiguo) | `dustin.calderonparedes@gmail.com` | **No.** No ve las carpetas de Workspace — HTTP **404** |

El remoto antiguo **se deja intacto**: no lo usa ninguna tarea automatizada y borrarlo no
aporta nada. Pero no sirve para esto, y el modo en que falla es traicionero: no da un
error de permisos, da un **404**, que se lee como «esa carpeta no existe» en vez de como
«esta cuenta no la ve».

### Carpetas destino, con sus IDs

`Mi unidad / #Areas / #Dustin Calderon / 03. Contenido RRSS / #POSTIZ /`

| Carpeta | ID |
|---|---|
| `03. Contenido RRSS` (contenedor) | `1VVXxoeBeASaTCGN8LSVMC63goH0unqLE` |
| `#POSTIZ / Publicado` | `1RkW1J4lc2X-qmOTqrRsJwQc1uuDMMN6G` |
| `#POSTIZ / Respaldo técnico` | `1RmJokTxS7zRGqAWh76J6EG7oY7grXh6A` |

**Se apunta el ID, no la ruta.** Renombrar o mover una carpeta en Drive cambia la ruta y
no el ID; un script que navegue por nombres se rompe en silencio el día que alguien
reorganice su unidad.

> **La escritura está probada de verdad**, no supuesta: se creó una carpeta, se subió un
> fichero, se releyó intacto y se borró. El `OK` de una API no demuestra que el byte esté
> al otro lado.

## 5. Cómo sabe qué está ya archivado

**Creada y poblada.** Una propiedad en Notion: **`❌ drive_url`** (tipo `url`), que hace
dos cosas a la vez:

- **Es el registro.** Con valor = archivado; sin valor = pendiente. Idempotente sin
  fichero de estado ni consultas a Drive.
- **Es el enlace de vuelta.** Desde la fila se llega a la carpeta de másters en un clic,
  que es la mitad del valor del archivo.

Para rearchivar algo (por ejemplo si alguien borra la carpeta en Drive): se vacía la
propiedad y la siguiente pasada lo rehace.

El **espejo técnico no necesita registro**: `rclone copy` es idempotente por naturaleza
—compara y sólo sube lo que falta—, así que no hay nada que anotar en ningún sitio.

> ### ⚠️ Añadir la propiedad tiene un riesgo conocido
> Un `PATCH /v1/databases` puede **borrar las descripciones** de otras propiedades — ya
> pasó una vez y no se puede deshacer por API. El paso se hace con captura de todas las
> descripciones antes, y comprobación una a una después.

## 6. El material anterior al pipeline

Los 18 posts publicados desde la UI **no tienen fila en Notion**: no hay `cuenta`, ni
título, ni `❌ drive_url` donde anotar nada. Se archivan enteramente desde los datos de
Postiz (§3), que es justo lo que hace viable esta parte:

```
Publicado/<cuenta del mapa>/<AAAA-MM>/<AAAA-MM-DD titulo>/
```

La cuenta sale del mapa por `integrationId` (§7.1) igual que en el resto del archivo, y a
falta de título en Notion se usan **las primeras palabras del copy**. La hora (`HHMM`)
sólo entra como último recurso, si el copy está vacío: **ninguna de las 18 carpetas reales
la usa**.

Su registro no puede vivir en Notion, así que vive en un fichero local:
`/opt/homeserver/scripts/.postiz-archivo-web.json` — la lista de `Post.id` ya archivados.

**Esta parte es una pasada única**, no trabajo recurrente: todo lo nuevo pasa ya por
Notion y tiene su fila. De los 18, **9 son irrecuperables** —sus ficheros se borraron en
junio— y **9 conservan los suyos**, ya fuera de peligro desde que la retención subió a
3650.

## 7. Orden de ejecución

| Fase | Qué | Estado |
|---|---|---|
| **0** | **Parar la purga**: `MEDIA_RETENTION_DAYS = 3650`, terminando y relanzando el workflow en Temporal | **✅ Hecho** — verificado en el historial |
| **1** | **Destino en Drive**: remoto `gdrive-work`, las dos carpetas y sus IDs, con escritura probada | **✅ Hecho** (§4) |
| **2** | **Espejo técnico**: `rclone copy` del disco a `Respaldo técnico/` + entrada de cron | **✅ Hecho** — 54/54 ficheros, verificado con `rclone check` (hashes, 0 diferencias) |
| **3** | Propiedad `❌ drive_url` en Notion, con la comprobación de descripciones | **✅ Hecho** — creada; las 10 descripciones existentes, intactas |
| **4** | El archivador curado + su modo `--seco` | **✅ Hecho** — `postiz-archivo-drive.py` |
| **5** | Primera pasada real sobre `kinda chic`, verificada fichero a fichero | **✅ Hecho** — 5/5 md5-idénticos y en orden; el enlace de Notion responde 200 |
| **6** | Pasada única del material anterior al pipeline (§6) | **✅ Hecho** — 18 posts; 9 con ficheros, 9 con el `post.txt` documentando la pérdida |
| 7 | Documentación: manual de Notion | **Pendiente** |

**El orden cambió respecto a la primera versión de este plan.** Allí la fase 0 era
rescatar a mano los 201,0 MB, porque era lo único con fecha de caducidad. Subir la
retención **eliminó esa fecha**, y con ella la urgencia: ahora el espejo puede ir antes
que el curado, que es el orden correcto —primero que exista una segunda copia de todo,
después que se pueda encontrar—.

## 7.1 Lo que quedó instalado

| Fichero | Qué es |
|---|---|
| `/opt/homeserver/scripts/postiz-respaldo-drive.sh` | El espejo. `rclone copy` del disco entero |
| `/opt/homeserver/scripts/postiz-archivo-drive.py` | El archivador curado. Admite `--seco` |
| `/opt/homeserver/scripts/.postiz-archivo-web.json` | Registro de los posts sin fila en Notion |
| `/var/log/postiz-archivo.log` | Log común de los dos, con rotación semanal |

**Los dos scripts están versionados en [`scripts/`](./scripts/)**, al lado de este
documento. A diferencia de los workflows de n8n, **no llevan ningún secreto dentro** —
leen `NOTION_API_KEY` del entorno—, así que sí pueden vivir en el repositorio. Y deben:
`/opt/homeserver/scripts/` no entra en ningún backup, así que una copia en ese mismo
disco no habría servido de nada. Al tocarlos, actualizar las dos copias.

```
40 2 * * *  postiz-respaldo-drive.sh
55 2 * * *  postiz-archivo-drive.py   >/dev/null 2>>/var/log/postiz-archivo.log
```

> **El `>/dev/null` no es descuido.** El script ya escribe él mismo en el log; si además
> se redirige su salida estándar al mismo fichero, **cada línea aparece dos veces**. Lo
> destapó la prueba real con cron. El `stderr` sí se conserva, para que un fallo
> inesperado deje rastro.

Elegidas a las 02:40 y 02:55 para no solaparse con nada: el backup de CastRadar va a
las 03:30, el `backup-daily.sh` a las 04:00 y el sync de Notion a las 06:00.

> ### ⚠️ El espejo usa `copy`, nunca `sync`
> `sync` borra en destino lo que falte en origen. **Si `/mnt/seagate` no estuviera
> montado, la fuente parecería vacía y `sync` se llevaría por delante el respaldo
> entero.** Con `copy` eso no puede pasar, y además conservar lo que se borró del disco
> es justo lo que permite recuperar un borrado accidental.
>
> Aun así el script comprueba, **antes de copiar nada**, que el directorio exista, que
> tenga ficheros y que el remoto responda. Un fallo de montaje tiene que fallar a las
> claras, no traducirse en un respaldo que «funciona» y no copia nada.

**Cómo rearchivar una pieza** (por ejemplo si alguien borra su carpeta en Drive): vaciar
`❌ drive_url` en su fila de Notion, o quitar su `Post.id` del registro local si es de
las que no tienen fila. La siguiente pasada la rehace.

> **Los nombres de carpeta de cuenta salen de `integrationId`, no de `Integration.name`
> ni de la propiedad `cuenta`.** La primera pasada en seco lo destapó: los posts hechos
> a mano daban `CITEM Conservatorio Iberoamericano…` y los del pipeline `CITEM`, con lo
> que el archivo de una misma cuenta quedaba partido en dos carpetas. El mapa de ids
> está en la cabecera del script y es el mismo que usa el nodo `Planificar`. Una
> integración que no esté en el mapa se archiva igual, con el nombre recortado, y **deja
> un aviso en el log** para que se añada.
>
> **Había una cuarta integración fuera del mapa**, y era la peligrosa:
> `cmqjs6xnx0001q07q9aohapuv`, de **TikTok**, se llama exactamente `Dustin Calderón` —
> igual que la de Instagram—. Un cross-post entre las dos habría producido **la misma
> carpeta**. Está añadida como `Dustin Calderón (TikTok)`.

### Cuatro guardas que salieron de auditar el script ya en marcha

Ninguna venía de un fallo observado en producción: las cuatro son caminos en los que el
script habría dicho `OK` mientras perdía trabajo.

**1 · Colisión de nombres de carpeta.** La ruta **no es única por construcción**: dos
piezas de la misma cuenta, publicadas el mismo día y con títulos que truncan igual a 70
caracteres, dan exactamente la misma carpeta, y `rclone copyto` **sobrescribía los
másters de la primera sin devolver ningún error**. Ahora, antes de copiar, se lee el
`Post ID:` del `post.txt` que ya haya en la carpeta y, si es de otra pieza, la pasada
**aborta**. Probado disparándolo de verdad con una pieza sintética. La salida a mano es
renombrar una de las dos piezas en Notion.

**2 · La verificación posterior mira también lo que sobra.** Comprobaba sólo los ficheros
que faltaban. Si una pasada anterior dejó 6 ficheros y la nueva sube 3, los tres viejos se
quedaban dentro, mezclados con los nuevos, y nadie lo detectaba: la carpeta pasaba la
verificación entera.

**3 · Un fallo al escribir en Notion cuenta como fallo.** La pieza se sumaba a `hechos`
*antes* de tocar Notion, así que un error escribiendo `❌ drive_url` sólo dejaba un
`AVISO`: el resumen decía **`0 fallos`** mientras la pieza quedaba sin marcar y se
resubía entera cada noche.

**4 · La integración de TikTok fuera del mapa** (arriba), que habría hecho colisionar dos
cuentas distintas en la misma carpeta.

## 7.2 Lo que está probado, y lo que no

Distinguirlo importa: lo de la izquierda tiene evidencia; lo de la derecha es confianza
razonada.

| Probado contra la realidad | Cómo |
|---|---|
| El espejo copia íntegro | `rclone check`: **54/54 por hash, 0 diferencias** |
| El archivo respeta el orden del carrusel | Los 5 de `kinda chic`, **md5 idéntico** al disco, uno a uno |
| El enlace de Notion funciona | Petición HTTP real → **200** |
| No duplica al repetirse | Segunda pasada: *«0 archivados · 19 ya estaban»* |
| **Cron los ejecuta de verdad** | Entradas temporales a dos minutos vista, confirmadas en `syslog` y en el log. Prueba el **mecanismo**, no el horario real (ver abajo) |
| **La guarda de colisión aborta** | Disparada de verdad con una pieza sintética que apuntaba a una carpeta ajena: la pasada falla y no sobrescribe |
| El cerrojo impide el solape | Cogido desde otro proceso: la pasada sale limpia sin tocar nada |
| La rotación del log es válida | `logrotate -d` sin errores |
| El `PATCH` de Notion no rompió nada | Las 10 descripciones existentes, intactas |

| Sin probar | Riesgo |
|---|---|
| **El horario real de los crons (02:40 y 02:55)** | **No han disparado ni una vez.** Lo verificado fueron entradas temporales a dos minutos vista: confirman el mecanismo, no la hora. Un error en el campo horario no se vería hasta la primera noche |
| **La paginación de Notion** | Escrita, pero con una sola fila el bucle nunca da la segunda vuelta. Se ejercitará sola al pasar de 100 |
| **Los caminos de fallo** (Drive caído, Notion caído) | Por diseño: la pieza se anota como fallo y se reintenta a la noche siguiente. No reproducido |
| **Una pieza nueva de punta a punta** | El camino es el mismo que recorrió `kinda chic`. Se verá en la próxima publicación real |

> ### ⚠️ Dos veces di por bueno un resultado que no lo era
> Al probar el cron, el bucle de espera dejó de mirar en cuanto vio arrancar el trabajo,
> y concluí que el espejo no había corrido. Había corrido: **tarda 35 s en escribir su
> primera línea** porque antes comprueba el remoto y cuenta el destino. La misma
> impaciencia hizo que la primera prueba del cerrojo no probara nada, porque la pasada
> terminaba antes de que la segunda arrancara.
>
> Esperar al **final** de la operación, nunca al principio. Y si una prueba de
> concurrencia no llega a solaparse, no ha probado nada.

## 8. Lo que este plan **no** hace

| No hace | Por qué |
|---|---|
| Tocar el camino de publicación | El archivo no puede retrasar ni romper una publicación. Si falla, sólo se pierde una noche |
| Borrar nada, en ningún lado | Ni en el disco ni en Drive. Copia y punto. La limpieza del disco es de otro sistema ([MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md)) |
| Leer de Notion los bytes | Descartado con motivo (§3). Notion sólo aporta el título y recibe el enlace |
| Archivar borradores ni cancelados **en `Publicado/`** | Sólo `Status = Publicado`: el archivo curado refleja lo que existe públicamente. El espejo, en cambio, se lleva todo |
| Sustituir a Notion como máster | Drive es **copia**. Para lo que pasa por el pipeline, Notion sigue siendo la fuente de verdad |
| Volver a bajar la retención | No mientras Drive no tenga la copia. Ese día se puede discutir; hoy sería quitar la única red |
| Rescatar los 9 posts de junio | Sus ficheros ya no están en disco. No hay de dónde sacarlos |

## 9. Riesgos

| Riesgo | Mitigación |
|---|---|
| El `PATCH` de Notion borra descripciones | Captura antes, comprobación después (§5) |
| Se archiva de una caché, no del original | Probado md5-idéntico contra Notion (§3). Y para el material antiguo la caché **es** el original |
| El script falla en silencio meses | **Mitigado a medias (2026-08-05).** El script llama a `latido()` en sus tres finales posibles, con `status=up` o `down`. Está **inerte hasta que exista `POSTIZ_ARCHIVO_PING_URL`** — ver «Activar el aviso» abajo. Mientras no se cree el monitor, el riesgo sigue tal cual |
| **El registro local se corrompe** | **Arreglado (2026-08-05).** Se escribe a un temporal en el mismo directorio con `fsync` y `os.replace`, que es atómico. Y al leerlo se distingue «no existe» (primera ejecución, `{}`) de «no se puede leer»: lo segundo aborta con código 2 y **deja el fichero donde está**, para que cada pasada vuelva a avisar hasta que una persona lo repare. Apartarlo sólo retrasaba el problema un día: sin fichero, la pasada siguiente vuelve a ser «primera ejecución» y duplica carpetas igual |
| **El script escribe en el remoto equivocado** | `gdrive` responde **404**, no un error de permisos, y un 404 se lee como «la carpeta no existe». El script referencia carpetas **por ID** y debe fallar en vez de crearlas |
| Drive se llena | 0,73 TB usados de 2,20 TB. El ritmo actual son ~200 MB/mes. Margen de años |
| Alguien borra la carpeta en Drive | Vaciar `❌ drive_url` la reconstruye. El espejo se rehace solo en la siguiente pasada |
| **El Seagate se desmonta y el espejo copia un directorio vacío** | `rclone copy` no borra en destino, así que no destruiría el archivo — pero conviene comprobar el montaje antes de correr |

### Activar el aviso — 3 pasos, y hace falta la UI de Kuma

El código ya está; falta crear el monitor, que requiere entrar en Uptime Kuma
(`127.0.0.1:3001`, ya corriendo en el servidor).

1. En Kuma: **Add New Monitor** → tipo **Push**. Nombre `Postiz · archivo Drive`,
   *Heartbeat Interval* **86400** (24 h) y *Retries* **1**. Kuma da una URL del
   tipo `http://localhost:3001/api/push/<token>`.
2. En `/opt/homeserver/.env`, añadir esa URL:
   ```
   POSTIZ_ARCHIVO_PING_URL=http://localhost:3001/api/push/<token>
   ```
   El cron de las 02:55 ya hace `set -a; . /opt/homeserver/.env`, así que no hay
   que tocar el `crontab`.
3. Elegir en Kuma a dónde va el aviso (correo, Telegram, lo que ya uses).

Comprobación, sin esperar a la noche:

```bash
set -a && . /opt/homeserver/.env && set +a && python3 /opt/homeserver/scripts/postiz-archivo-drive.py --seco
```

> `--seco` **no late a propósito** —una pasada de prueba no debe marcar el
> monitor como sano—, así que para verificar el latido hay que hacer una pasada
> normal, o un `curl` a mano a la URL del punto 1 y mirar que Kuma se pone en
> verde.

**Por qué un monitor Push y no un chequeo activo:** un Push se cae solo cuando
*deja* de recibir el latido. Eso cubre el caso que de verdad no se detectaba —que
el cron ni siquiera se ejecute—, y no sólo el de que se ejecute y falle. El
script ya salía con código distinto de cero al fallar; el problema era que el
cron manda la salida a `/dev/null`.

## 10. Decisiones tomadas

| Decisión | Valor | Quién |
|---|---|---|
| Retención de la caché | **`MEDIA_RETENTION_DAYS = 3650`**, aplicada y verificada | Usuario, 2026-08-04 |
| Cuenta de Drive | **`gdrive-work`** = `dustin@dustincalderon.com` (Workspace). El `gdrive` antiguo no vale | Verificado, 2026-08-04 |
| Destino | `#Areas/#Dustin Calderon/03. Contenido RRSS/#POSTIZ/`, con `Publicado/` y `Respaldo técnico/` | Usuario, 2026-08-04 |
| Estructura del curado | `Publicado/<cuenta>/<AAAA-MM>/<fecha titulo>/` | Usuario, 2026-08-04 |
| Alcance del curado | Sólo `Status = Publicado` | Usuario, 2026-08-04 |
| Alcance del espejo | El disco entero, sin criterio de selección | Decidido, 2026-08-04 |
| Origen de los bytes | **Seagate, sin reserva a Notion** — la reserva se descartó (§3) | Decidido, 2026-08-04 |
| Origen de los metadatos | **Base de datos de Postiz.** Notion sólo pone el título | Decidido, 2026-08-04 |
| Dónde corre | Script en el host + cron, no n8n | Propuesta |
| Registro del curado | Propiedad `❌ drive_url` en Notion | Propuesta |
