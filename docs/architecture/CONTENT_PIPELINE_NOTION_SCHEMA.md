# Pipeline de contenido — el lado de Notion: esquema y estados

> **Qué es esto:** la tabla de Notion de la que bebe el pipeline — qué propiedades lee y escribe, cómo se traduce cada una a la API de Postiz, qué valida el worker antes de enviar y la máquina de estados de `Status`.
>
> **Parte de:** [CONTENT_PIPELINE_NOTION_POSTIZ.md](./CONTENT_PIPELINE_NOTION_POSTIZ.md), que tiene el mapa de todos los documentos del pipeline.

---

## 1. Una sola tabla: el calendario que ya existe

**Todo vive en el calendario**, `collection://186a2405-a123-81dc-832f-000b82a65c0c`. No hay tabla propia del pipeline: se le añaden sus propiedades (§2).

Las demás propiedades del calendario (`Name`, `Brand`, `Plataforma`, `Tipo`, `Fecha`, `Notas`, `Content Series`, `🌐 Projects`, `URL`, `Agendada`, `Validación`…) cambian cuando el equipo reorganiza el calendario, y da igual: **el pipeline sólo mira las de abajo.** Tres alimentan el pipeline sin tocarlas:

| Propiedad existente | Uso |
|---|---|
| `Plataforma` | El worker **sólo mira filas que contienen Instagram**. Todo lo demás —LinkedIn, YouTube, ideas sin plataforma— le es invisible |
| `Tipo` | Historia → `post_type = story`; Post · Carrusel · Reel → `post` |
| `Fecha` | La fecha y hora de publicación. **Necesita hora** (§5) |

> ### ⚠️ Deuda conocida: una plataforma por fila
> `Plataforma` es multi-select. Mientras sólo se publique en Instagram no importa: si una fila tiene además TikTok, el worker publica en Instagram y el resto lo ignora.
>
> **Disparador para revisarlo:** el día que se quiera publicar en **dos plataformas desde la misma fila**. Instagram y YouTube necesitan copy distinto, formato distinto y devuelven IDs distintos — una fila no puede sostener ambos. Ese día hay que separar la cola a su propia tabla, o pasar `Plataforma` a single-select. Mientras sea sólo Instagram, la granularidad de planificar y la de publicar coinciden, y una segunda tabla sería trabajo sin beneficio.

## 2. Las propiedades del pipeline

**Una fila = un post en Postiz.** Cuando una pieza es compartida entre cuentas, **no son varios posts**: publica una cuenta y las demás van como **colaboradoras de Instagram** (§2.4). Un post, un ID, un estado.

| Propiedad | Tipo | Lo escribe | → API |
|---|---|---|---|
| `cuenta` | **Select** | equipo | `integration.id` (§2.1) |
| `colaboradores` | Multi-select | equipo | `settings.collaborators[].label` — **restricciones en §2.4** |
| `copy` | Text | equipo / agente | `value[0].content` |
| `media` | **Files** | equipo | `value[0].image[]` — **en orden** |
| `first_comment` | Text | equipo / agente | `value[1].content` (§3) |
| `modo` | Select: `borrador`·`programar` | equipo | **`type`** (§2.2) |
| `Status` | Select | equipo → n8n | ✗ — el estado del pipeline (§7) |
| `❌ postiz_post_id` | Text | **n8n** | — el post actual en Postiz |
| `❌ postiz_media` | Text | **n8n** | — JSON `[{id, path, src}]`, mismo orden que `media`; `src` es el id del fichero en Notion |
| `❌ error_log` | Text | **n8n** | — último error (§7.1) |
| `❌ release_url` | URL | **n8n** | — permalink de Instagram al publicar |

Y lo que **no** son propiedades del pipeline:

- **`post_type`** sale de `Tipo` (§1). Es obligatorio en la API (`@IsDefined()` en `InstagramDto`), pero no hace falta pedirlo dos veces.
- **`publish_at`** es `Fecha`, con hora (§5).
- **`URL`** es del equipo y tiene otro uso; por eso el permalink va en `❌ release_url` y no ahí. La réplica de carruseles sí la lee en las filas `Por replicar` (§7).
- **`❌ drive_url`** la escribe el archivador de Drive ([ARCHIVO_DRIVE.md](./ARCHIVO_DRIVE.md)), fuera del camino de publicación.

Los campos `❌` son **territorio exclusivo de n8n**. Si alguien se ve editándolos a mano, algo se ha roto.

> **No hay aviso de error por correo.** María revisa las publicaciones, y lo que falla en una fila se ve en la vista *⚠️ Averías* (§8).

> ### ⚠️ Renombrar una propiedad rompe el worker
> Los workflows buscan las propiedades **por su nombre exacto**, acentos y emoji incluidos. Renombrar una en Notion y no tocar n8n tiene dos desenlaces, ninguno bueno:
>
> - `Plataforma` o `Status` → el sync falla entero y **no publica nada**. Al menos se nota.
> - Cualquier otra → el sync sigue corriendo pero **deja de ver ese campo**, y la fila acaba en `Error` con un motivo engañoso («sin cuenta» con la cuenta puesta).
>
> **Se puede renombrar**, pero hay que actualizar los cuatro workflows en el mismo movimiento. Las propiedades libres —las que ningún workflow toca— son `Brand`, `Notas`, `Content Series`, `🌐 Projects`, `Agendada` y `Validación`, y cualquier otra que se añada. `Name` sólo se usa para etiquetar la ejecución en n8n: renombrarla es cosmético.

> ### ⚠️ No basta con la URL: `MediaDto` exige `id` **y** `path`
> Mandar sólo la URL en `value[0].image[]` devuelve **400**. Por eso `❌ postiz_media` guarda el objeto entero que devuelve la subida, no una lista de URLs. El detalle de los validadores: [API_POSTIZ §2](../reference/CONTENT_PIPELINE_API_POSTIZ.md).

> ### `Status` es un *select*, y es la única propiedad de estado
> Tiene que ser *select* y no del tipo *status* de Notion: **al tipo *status* la API de Notion no le puede añadir opciones**, así que no habría forma de meterle `Listo`, `Programado` ni `Error` desde un script. Con *select*, si algún día hace falta vocabulario de producción (`Sin empezar`, `En progreso`), se añade por API.
>
> Y es **una sola**, para el equipo y para el pipeline: un ciclo de producción aparte hacía convivir dos vocabularios que se pisaban («Borrador» y «Publicado» con sentidos distintos en cada propiedad), y el calendario es casi entero de Instagram.

> ### Por qué `cuenta` y no reutilizar `Brand`
> `Brand` es multi-select y sirve para planificar. Si el worker dependiera de que tenga exactamente un valor, sería **una convención que la máquina necesita y no puede verificar**. Además no coinciden: `Brand` tiene marcas sin Instagram en Postiz, y AMORISMO VOL III es una cuenta pero no una marca. Una propiedad explícita cuesta menos que ese riesgo, y `Brand` sigue sin restricciones.

### 2.1 `cuenta` — una opción, un canal de Postiz

Cada opción del select equivale a una integración de Postiz (`instagram-standalone`, [POSTIZ_FORK §9](./CONTENT_PIPELINE_POSTIZ_FORK.md)). **La correspondencia vive en un nodo de configuración de n8n**, no en una tabla de Notion — son valores fijos que cambian una vez al año:

```
"Dustin Calderón"  → cmqjq77hg0001mw7y2xf6bg86
"CITEM"            → cmqjqapu00003mw7yrudcwklj
"AMORISMO VOL III" → cmqjqfvnw0005mw7yoywgo6he
```

Añadir una cuenta es una línea aquí, una opción en el select y, si el webhook de Postiz filtra por integración, marcarla allí ([OPERACION §5](../guides/CONTENT_PIPELINE_OPERACION.md)).

> Se guarda el ID, no el nombre. Resolver por nombre contra `GET /public/v1/integrations` parece más cómodo, pero se rompe **en silencio** el día que alguien renombre un canal en Postiz.

### 2.2 `modo` — borrador o programar

Va directo al campo `type` de `POST /public/v1/posts`:

| `modo` | `type` | Qué hace Postiz |
|---|---|---|
| `programar` | `schedule` | Queda programado y se publica solo |
| `borrador` | `draft` | Se crea en Postiz y **no se publica nunca** |

Por defecto, `programar`.

`borrador` sirve para el **dry-run** editorial y para revisar una pieza en la vista real de Postiz antes de soltarla. Cambiar de `borrador` a `programar` lo recoge el sync en la siguiente pasada, o al pulsar el botón.

> **No contradice "nunca se aprueba en Postiz"** ([NOTION_POSTIZ §5](./CONTENT_PIPELINE_NOTION_POSTIZ.md)). Se aprueba siempre en Notion: una fila en `Listo` con `modo = programar` está aprobada, y una en `borrador` se aprueba pasando `modo` a `programar` —así se aprueban las réplicas (§7)—. `Status` no aprueba un borrador. Nadie promueve un draft desde la UI de Postiz — si lo hiciera, la siguiente pasada del sync lo revertiría.

> ### ⚠️ Un borrador **no pasa por la validación del servidor**
> Postiz sólo valida los `schedule` ([POSTIZ_FORK §5](./CONTENT_PIPELINE_POSTIZ_FORK.md)): un `borrador` entra con lo único que se mira siempre, que no esté vacío del todo.
>
> Consecuencia: una pieza que en `borrador` se crea sin quejarse puede **fallar al pasarla a `programar`**. El dry-run editorial no es un dry-run técnico. Las validaciones de n8n ([SYNC §2](./CONTENT_PIPELINE_SYNC.md)) sí corren en ambos casos, y son las que atrapan casi todo.

### 2.3 Ajustes opcionales de Instagram

Se añaden a la tabla el día que se necesiten. Añadir una propiedad en Notion cuesta diez segundos; lo que importa es que el mapeo esté escrito.

| Campo Notion | Tipo | → API | Restricción |
|---|---|---|---|
| `is_trial_reel` | Checkbox | `settings.is_trial_reel` | **Exactamente 1 media, debe ser vídeo, y `Tipo` ≠ `Historia`** — ver abajo dónde se comprueba cada una |
| `graduation_strategy` | Select | `settings.graduation_strategy` | `MANUAL`·`SS_PERFORMANCE`. Sólo con trial reel |
| `thumbnail_seconds` | Number | `image[].thumbnailTimestamp` | **No declarado en `MediaDto`** — sobrevive porque el ValidationPipe no usa `whitelist` (`useGlobalPipes` en `apps/backend/src/main.ts`). Frágil ante merges. Tampoco se envía en stories |

> **`audio_id` no está en la lista a propósito.** Con `instagram-standalone` el parámetro se descarta en silencio ([POSTIZ_FORK §9](./CONTENT_PIPELINE_POSTIZ_FORK.md)). Exponerlo en Notion sería ofrecer un botón que no hace nada.

> ### ⚠️ Las tres reglas del trial reel no se comprueban en el mismo sitio
> Leer sólo el código de Postiz lleva a la conclusión equivocada. `checkValidity` de `instagram.standalone.provider.ts` valida **dos**: `'Trial Reels can only have one video'` y `'Trial Reels must be a video'`. La tercera **no está ahí**: `trialParams`, en `post()` de `instagram.provider.ts`, añade `trial_params` aunque `isStory` sea `true`, sin guarda.
>
> Quien la comprueba es **el subflow de n8n**, antes de llegar a Postiz, con el motivo `trial reel: no puede ser una Historia`. Las tres las cubre [`prueba-trial-reels.py`](./scripts/prueba-trial-reels.py).
>
> La consecuencia práctica: para una fila que venga de Notion las tres dan `Error` legible, pero **un post creado directamente contra la API de Postiz se saltaría la tercera**. Es otra razón para no publicar sin pasar por Notion.

### 2.4 Colaboradores — y sus dos restricciones duras

Una pieza compartida entre cuentas es **un solo post**: publica `cuenta` y las demás se invitan como colaboradoras. Eso mantiene el modelo 1:1 con Postiz —un post, un ID, un estado— y evita cualquier fan-out.

`post()` de `instagram.provider.ts` manda a Meta los `label` como usernames:

```ts
const collaborators =
  firstPost?.settings?.collaborators?.length && !isStory
    ? `&collaborators=${JSON.stringify(...map(p => p.label))}` : ``;
```

| Formato | ¿Admite colaboradores? | Origen |
|---|---|---|
| Post de imagen única | ✅ Sí | — |
| Reel | ✅ Sí | — |
| **Carrusel** | ❌ **No** | Postiz los manda en cada lámina y Meta los rechaza ahí (`handleErrors` de `instagram.provider.ts` traduce el error). La referencia de Meta (`IG User Media`, parámetro `collaborators`) sí los admite en carruseles, en el contenedor del carrusel |
| **Story** | ❌ **No** | El código los omite (`!isStory`) |

> ### ⚠️ Un carrusel o una story compartidos son filas separadas
> No hay forma de compartir un carrusel vía colaboradores. Si un carrusel tiene que salir en tres cuentas, son **tres filas** con su propia `cuenta` cada una — y ahí sí son tres posts independientes.
>
> El worker lo valida **antes** de enviar: `colaboradores` con más de un asset o con `post_type = story` → `Error` con el motivo, sin gastar la llamada.

**Los colaboradores son usernames de Instagram, no canales de Postiz.** No hace falta que esas cuentas estén conectadas a Postiz ni que existan en la tabla de §2.1.

**Cuántos, y qué pasa después.** La referencia de publicación (IG User Media, parámetro `collaborators`) admite hasta **3**; la del objeto publicado (IG Media Collaborators) dice 5. El manual pide como mucho 3, y el worker no lo valida. A cada cuenta le llega una **invitación que tiene que aceptar**: la API la da como `Pending` o `Accepted` (`invite_status`).

## 3. El primer comentario

`value` es un **array** (`PostContent[]`, mínimo 1). `value[0]` es el post; **`value[1..n]` son comentarios**, cada uno con su `content`, sus `image[]` y un `delay` opcional. Publicar un primer comentario es mandar un segundo elemento en `value`: crea un `Post` hijo con `parentPostId` y la misma `publishDate`.

`first_comment` es un campo propio y no parte de `copy` porque es una decisión editorial distinta y conviene poder verla y editarla por separado.

> - **Las imágenes de un comentario se ignoran en Instagram.** `comment()` de `instagram.provider.ts` sólo manda `message=` a `/comments`. Un comentario con ficheros publica sólo el texto.
> - **`delay` está en minutos**, no en segundos ni ms: `post.workflow.v1.0.6.ts` hace `sleep(60000 * delay)`.

## 4. Reglas de validación previas al envío

El worker las comprueba antes de gastar una llamada. Son las de **`instagram-standalone`**, que valida mucho menos que el provider normal ([POSTIZ_FORK §9](./CONTENT_PIPELINE_POSTIZ_FORK.md)):

| Regla | ¿La para Postiz? | Dónde |
|---|---|---|
| Al menos 1 media | ✅ Sí\* | `checkValidity` de `instagram.standalone.provider.ts` |
| Trial reel: 1 media y vídeo | ✅ Sí\* | `checkValidity` de `instagram.standalone.provider.ts` |
| **Máximo 10 medias** | ❌ **No** | El provider normal sí, el standalone **no**. Llega a Meta |
| **Carrusel: mínimo 2 medias** | ❌ No | Error de Instagram, traducido en `handleErrors` de `instagram.provider.ts` |
| **Colaboradores en carrusel** | ❌ No | Error de Meta porque Postiz los manda en cada lámina (§2.4), traducido en `handleErrors` de `instagram.provider.ts` |
| **Colaboradores en story** | ❌ No | Se **descartan en silencio** (`!isStory`, sin error) |
| **Audio** | ❌ No | Se **descarta en silencio**: exige `graph.facebook.com` ([POSTIZ_FORK §9](./CONTENT_PIPELINE_POSTIZ_FORK.md)) |

> **\* Sólo con `modo = programar`.** Con `borrador`, Postiz se salta `checkValidity` entero ([POSTIZ_FORK §5](./CONTENT_PIPELINE_POSTIZ_FORK.md)), así que **ninguna** de las siete la para: son 7 de 7 a cargo de n8n.

> ### ⚠️ Cinco de estas siete no dan error, o lo dan tarde
> **n8n es la única validación real.** Lo que no compruebe el worker, o lo rechaza Meta a mitad de la publicación, o —peor— se aplica a medias sin avisar.
>
> Las dos de "silencio" son las peligrosas: pones colaboradores en una story o un audio en un reel, la publicación sale **correcta pero sin eso**, y nadie se entera. El worker debe rechazarlas explícitamente.

> **Las stories no admiten carrusel.** Si `post_type = story` con varios ficheros, Postiz **publica cada media como una story independiente**. No es un error, es el comportamiento — pero sorprende a quien esperaba una sola pieza.

> **Orden de los ficheros en un carrusel:** el orden de la propiedad `Files` de Notion es el orden de publicación. Es responsabilidad de quien sube los ficheros, y no hay forma de validarlo automáticamente. Es el único punto del sistema donde el orden depende de una persona.

## 5. Zona horaria: siempre con offset

`writePost` de `posts.repository.ts` persiste con:

```ts
publishDate: dayjs(date).toDate()
```

`dayjs(string)` sin offset explícito parsea en la **zona local del proceso backend**, no en UTC. Y el DTO sólo exige `@IsDateString()` (campo `date` de `create.post.dto.ts`), que acepta tanto `2026-08-10T19:00:00` como `2026-08-10T19:00:00+02:00`.

El contenedor de Postiz corre en **UTC** (`TZ` vacío) y `dayjs(date).toDate()` **respeta el offset explícito**: enviado `2027-01-15T10:00:00+01:00`, almacenado `2027-01-15 09:00:00`. La columna guarda UTC.

**n8n manda siempre offset explícito.** Una fecha sin zona se interpretaría como UTC —en horario de verano de Madrid publicaría **dos horas tarde**— y dependería del `TZ` del contenedor, que cambia si algún día se recrea con otra configuración.

Lo que se **ve** en Notion es el literal escrito, así que toda escritura de `Fecha` por API manda `{"start": "<hora local sin offset>", "time_zone": "Europe/Madrid"}`: Notion la normaliza al offset correcto (DST incluido) y el validador del sync la acepta. En UTC, una fila mostraría «11:40» para un instante que en Madrid son las 13:40, y confunde a quien aprueba.

## 6. Carruseles: el ratio manda el primero

Instagram recorta todos los elementos de un carrusel al ratio del **primer** elemento. Si los slides no comparten proporción, del segundo en adelante salen recortados.

No se resuelve con código: se resuelve exportando los slides de un carrusel con la misma proporción. Es una convención del equipo, no una validación del worker.

Lo que sí se valida es el rango: cada foto del feed, carruseles incluidos, tiene que estar entre 4:5 y 1,91:1, o Meta no la publica (error 2207009). Lo rechaza Postiz al crear el post ([POSTIZ_FORK §5](./CONTENT_PIPELINE_POSTIZ_FORK.md)). Una foto vertical de iPhone es 3:4 y queda fuera.

## 7. Máquina de estados

Las opciones de la propiedad `Status` (§2):

```
                                      modo = programar
  (vacío) ─────► Listo ══╦══════════► Programado ══► Publicado
      ▲            ▲     ║                 ║             ║
      │            │     ║                 ╚═► Error ◄═══╝
      │            │     ║                       │
      │            │     ╚═► En Postiz (borrador)
      │            │              modo = borrador
      └────────────┴───────────────────┴─────────┘
              se corrige y se devuelve a Listo

   ──►  lo mueve una persona        ══►  lo escribe n8n
```

**El equipo sólo escribe `Listo`** (y `Por replicar`, abajo). Vaciar la propiedad retira el post de Postiz ([RECONCILIACION §4](./CONTENT_PIPELINE_RECONCILIACION.md)). Todo lo demás es del worker.

A partir de `Listo` nadie vuelve a tocar `Status` — pero **sí se puede seguir editando el contenido**: el sync propaga los cambios mientras el post no se haya publicado ([SYNC](./CONTENT_PIPELINE_SYNC.md)).

`Programado → Publicado` y `Programado → Error` los escribe n8n al recibir el webhook de Postiz ([RECONCILIACION §1](./CONTENT_PIPELINE_RECONCILIACION.md)).

**Con `modo = borrador`** (§2.2) la fila sincronizada no va a `Programado` sino a **`En Postiz (borrador)`**. Es un estado propio a propósito: si reutilizara `Programado`, alguien daría por hecho que va a salir y no saldría nunca. Desde ahí se pasa a `Programado` cambiando `modo`, no la propiedad `Status`.

**Postiz no se entera de que la pieza existe hasta que `Status = Listo`.** El borrador *editorial* vive en Notion y no sale de ahí.

> **`Por replicar`.** Una opción previa a `Listo` para la réplica de carruseles: una persona la escribe con el post ajeno en `URL` y la cuenta que lo publicó en `cuenta origen`, y la réplica la prepara (workflow `Carruseles · Replicar`, [INVENTARIO §1](../reference/CONTENT_PIPELINE_INVENTARIO.md)). **El sync no la lee**: lee `Listo`, `Programado` y `En Postiz (borrador)`, y la recuperación, `Programado`. La retirada reclama el post de toda fila con `Status` puesto, `Por replicar` incluida: el de una fila que se rehace sigue en Postiz hasta que el sync lo sustituye al terminar la réplica. **La réplica la deja en `Listo` siempre con `modo = borrador`, y la aprueba una persona —María— cambiando `modo` a `programar`**: un LLM no aprueba su propia salida. El proceso vive en `Instalar-Home-Server/docs/architecture/CARRUSEL-IG-TRADUCIDO.md`.

### 7.1 El camino de vuelta desde `Error`

`Error` **no es un sumidero**. Se corrige lo que falló y se devuelve `Status` a `Listo`; el sync vacía `❌ error_log` cuando la pasada sale bien. **Si la `Fecha` ya pasó, hay que poner otra**: sin `❌ postiz_post_id` la fila vuelve a `Error` por la fecha; con él el sync la ignora, y la recuperación dice qué fue de su post ([RECONCILIACION §1](./CONTENT_PIPELINE_RECONCILIACION.md)).

**Qué dice `❌ error_log`, y de quién es el fallo.** Lo lee una persona, así que dice el porqué y qué hacer; el detalle técnico (el JSON de Postiz, el stack de axios) se queda en la ejecución de n8n.

| Lo escribe | Forma | El fallo es de |
|---|---|---|
| `Planificar` (sync) | los motivos de la validación, separados por `·` («sin copy · sin media») | la fila |
| `Recolectar media` (subflow) | «Subiendo los assets a Postiz: `<fichero>`: `<motivo>`», con el motivo de `normalizar-media.sh` o el mensaje con el que Postiz rechazó el fichero | casi siempre el fichero |
| `Formatear error` (subflow), si Postiz contesta con `provider` | «Postiz rechazó la pieza: `<mensaje de Postiz>`. Corrígelo en la fila…» | la fila: es la validación del contenido (`PostValidationException`, [POSTIZ_FORK §5](./CONTENT_PIPELINE_POSTIZ_FORK.md)) |
| `Formatear error`, cualquier otra respuesta | «Postiz respondió `<código>`: `<mensaje>`. No es un fallo de la fila…» | el sistema (la petición, la API key, el límite) |
| `Formatear error`, sin respuesta | «Postiz no respondió (`<error de red>`). No es un fallo de la fila…» | el sistema |
| `Formatear error de subida`, si el SSH falla | «n8n no pudo ejecutar la subida en el servidor…» | el sistema |
| `Interpretar payload` (receptor) | «Postiz dio error al publicar: `<cause.failure.message>`…» | Instagram o Postiz, al publicar |
| `Reconciliar` (recuperación), con la `Fecha` ya pasada | «Postiz dio error al publicar, pero su aviso con el motivo no llegó…» o «Postiz ya no tiene este post…»: el motivo no viaja en `GET /posts` | Instagram o Postiz, al publicar |
| `Reconciliar`, si en Postiz seguía el borrador | «La Fecha pasó y en Postiz seguía como borrador…» | la aprobación, que llegó sin tiempo |
| `planificar.py` (réplica de carruseles, en Instalar-Home-Server), en una fila `Por replicar` | «URL tiene que ser el enlace de un post de Instagram…» o «cuenta origen tiene que ser el nombre de la cuenta…» | la fila |

Los nodos viven en n8n, no en git; `planificar.py`, en Instalar-Home-Server. `❌ error_log` sólo guarda el último error de cada fila; dónde está el historial: [OPERACION §3](../guides/CONTENT_PIPELINE_OPERACION.md).

Al reintentar, el worker **reutiliza `❌ postiz_media` si son los mismos ficheros en el mismo orden**: compara el `src` guardado de cada uno con el id del fichero que hay hoy en `media`, que va en la ruta de su URL de Notion (la firma cambia en cada lectura; la ruta no). Si se sustituye o se reordena una lámina, los vuelve a subir todos. Así no se vuelve a mover un reel de 100 MB por un fallo que ocurrió después de la subida, sin publicar nunca un fichero viejo. Sin un id reconocible (un enlace externo) no reutiliza nunca.

**Si una pieza ya programada pasa a `Error` por una edición que no valida** (la hora borrada al cambiar la `Fecha`, sin media…), la versión anterior sigue en Postiz y sale a su hora: la fila en `Error` sigue reclamando su post ([RECONCILIACION §4](./CONTENT_PIPELINE_RECONCILIACION.md)). Se corrige la fila, o se vacía `Status` si no debe salir. **Si en cambio falla después de validar** —al subir los ficheros, o Postiz rechaza o no contesta el `POST`—, no queda nada programado: el subflow borra el post anterior antes de subir y crear el nuevo.

## 8. Botones, vistas y descripciones

**2 propiedades de tipo botón**, las dos *Enviar webhook*: `Sync now` ([SYNC §1](./CONTENT_PIPELINE_SYNC.md)) y `Replicar`, que lanza la réplica de carruseles. **Sólo se crean desde la UI**: la API de Notion (`2022-06-28` y `2025-09-03`) rechaza el tipo `button`. Exigen plan de pago de Notion.

**3 vistas del pipeline**, en la base (el manual de uso manda a ellas por su nombre):

| Vista | Filtro | Columnas | Orden |
|---|---|---|---|
| `▶ Publicar en IG` | `Plataforma` contiene `Instagram` | `Name`, `Fecha`, `cuenta`, `Tipo`, `Status`, **`modo`**, `Sync now`, `copy`, `media`, `colaboradores`, `first_comment`, `❌ error_log` | `Fecha` ascendente |
| `⚠️ Averías` | `Status` es `Error` | `Name`, `Fecha`, `cuenta`, `Status`, `❌ error_log`, `❌ postiz_post_id` | `Fecha` ascendente |
| `🔁 Por replicar` | `Status` es `Por replicar` | `Name`, `URL`, `cuenta`, `Fecha`, `Status`, `❌ error_log` | `Fecha` ascendente |

De las tres, `▶ Publicar en IG` es la que enseña `modo`, y es donde el manual manda a aprobar un borrador (§2.2).

**2 propiedades más de la réplica:** `cuenta origen` (texto), la cuenta de Instagram del post ajeno de una fila `Por replicar`, y `plantilla` (1, 2 o 3), la plantilla de CITEM que le tocó. Ningún workflow del pipeline las lee: las lee y escribe la réplica. `cuenta origen` existe porque un enlace `/p/…` no dice de quién es el post y la Graph API no lo resuelve sin revisión de Meta; `plantilla`, porque la siguiente de la rueda sale de la última declarada.

`Fecha` muestra la hora, en 24 h (`time_format: "H:mm"`).

> **Para comprobar vistas y botones:** la API REST no los expone; el conector de Notion sí —`fetch` sobre la base devuelve `<views>` y el esquema con `"Sync now": {"type": "button"}`—. Lo que no expone ninguno de los dos es la **acción** de un botón: que envíe el webhook se comprueba pulsándolo y buscando la ejecución en n8n con `user-agent: NotionAutomation` ([SYNC §1](./CONTENT_PIPELINE_SYNC.md)).

> ### ⚠️ Las descripciones de propiedad no se escriben por la API REST — y se borran solas
>
> - `PATCH /v1/databases` **rechaza** cualquier cuerpo que incluya `description` en una propiedad (400, en `2022-06-28` y en `2025-09-03`, y también en `/v1/data_sources`).
> - Un `PATCH` que reenvía el **tipo** de la propiedad —aunque mande las opciones con sus mismos `id`— **deja la descripción vacía**.
>
> Es decir: son de sólo lectura por la API REST y **frágiles ante cualquier cambio de esquema automatizado. Antes de tocar el esquema con un script, apunta las descripciones.**
>
> **Con el conector MCP de Notion sí se escriben**, y es como se reponen: `update-data-source` con `ALTER COLUMN "<propiedad>" SET SELECT(…) COMMENT '…'`. La misma sentencia **sin** `COMMENT` la vacía, así que el `COMMENT` va siempre en la sentencia que toca la propiedad.
