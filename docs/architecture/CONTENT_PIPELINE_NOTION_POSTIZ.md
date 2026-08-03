# Pipeline de contenido — Notion → n8n → Postiz → Instagram

> **Estado:** Fases 0, 2 y 3a cerradas. Fase 3b **a medias**: planificador montado y probado contra datos reales; falta la mitad que escribe (§10).
> **Fecha:** agosto 2026
> **Ámbito:** Instagram — **3 cuentas** (`instagram-standalone`, §4.9). Una sola tabla de Notion; ver la deuda conocida en §7.1
> **Relacionado:** [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md)

---

## 1. Decisión de arquitectura

Tres herramientas, todas con UI, ninguna que obligue al equipo a programar.

**Notion es la fuente de verdad (SSoT) — incluidos los ficheros máster.** El equipo no sale de Notion: planifica, escribe el copy, arrastra el vídeo a la fila y marca `publicación = Listo`.

La restricción que gobierna todo el diseño es que **Notion no sirve URLs públicas estables** (enlaces firmados con 1 hora de caducidad) e **Instagram exige una URL alcanzable desde internet**. Por tanto los bytes tienen que acabar en un host público en el momento de publicar.

Eso **no** rompe el SSoT. SSoT y hosting son trabajos distintos:

- **SSoT** = quién dice la verdad sobre qué se publica, cuándo y con qué fichero → **Notion**
- **Hosting** = quién sirve los bytes a Meta cuando toca → **Postiz** (copia derivada, desechable)

## 2. Las tres autoridades

| Actor | Manda sobre | Naturaleza |
|---|---|---|
| **Notion** | Qué se publica, cuándo, con qué texto y con qué fichero. Los másters. | **Autoridad.** Si se pierde, se pierde todo. |
| **Postiz** | Nada. Recibe órdenes, publica, devuelve IDs. Aloja una copia pública temporal. | **Ejecutor + caché.** Reconstruible desde Notion. |
| **n8n** | Nada. Ejecuta y reporta. Único con permiso de escritura en dos sistemas. | **Orquestador.** Sin estado propio. |

Postiz está degradado a propósito. Hoy es la herramienta principal; aquí es el último eslabón y el más tonto. Eso es lo que permite sustituirlo dentro de un año sin rehacer nada más.

**Nextcloud queda fuera del pipeline.** Sigue existiendo para lo que ya hace (llevar ficheros del móvil a algún sitio). Nada automático depende de él.

**El Seagate no queda fuera: es donde Postiz guarda los medios.** `/uploads` es un bind mount a `/mnt/seagate/postiz-media` (§10, Fase 0). Lo que se descartó fue montar una **biblioteca paralela** en `/srv/media` con watchers y ffmpeg (§13) — no el disco.

| | Antes de este pipeline | Después |
|---|---|---|
| Máster de un fichero | La copia de Postiz en el Seagate **es la única** | **Notion** |
| Copia en el Seagate | Única copia | **Derivada**, reconstruible desde Notion |

Es decir: el Seagate pasa de ser el original a ser la caché. Eso es una mejora de resiliencia, no una retirada del disco.

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
                    descarga bytes    │                │  media_url + post_id
                    sube multipart    ▼                │  + webhook al publicar
                                   ┌──────────────────────┐
                                   │  POSTIZ    ejecutor  │
                                   │  ✗ no se aprueba aquí│
                                   └──────────┬───────────┘
                                              ▼
                                         INSTAGRAM
```

---

## 4. Restricciones reales de Postiz (verificadas en este fork)

Todo lo de esta sección está comprobado contra el código de `custom/postiz-dc`, no contra la documentación pública. La documentación pública describe otro Postiz.

### 4.1 La URL pública es obligatoria de verdad

`instagram.provider.ts:615-629` construye la llamada a Meta pasando la ruta tal cual:

```ts
? `video_url=${m.path}&media_type=REELS&thumb_offset=${...}`
: `image_url=${m.path}`
```

Meta hace **fetch** de esa URL desde sus servidores. Si no es alcanzable desde internet, falla siempre — aunque subir a mano desde la UI funcione.

### 4.2 Storage: sólo `local` o `cloudflare`

`upload.factory.ts` no admite nada más, y `cloudflare.storage.ts:45` **hardcodea** el endpoint `https://${accountID}.r2.cloudflarestorage.com`. No hay hueco para MinIO ni para otro S3 compatible: no es que falte soporte, es que no hay dónde ponerlo.

**Decisión: `local`.** Verificado que Meta alcanza las URLs del dominio (§10, Fase 0). Los medios viven en el Seagate vía bind mount, no hace falta almacenamiento externo.

> Hay un bucket de R2 configurado y con credenciales válidas en `postiz.env`, **inactivo**. Queda como salida disponible si algún día el uplink de casa se convierte en el cuello de botella al servir reels a Meta — cambiar `STORAGE_PROVIDER` sería suficiente.

### 4.3 El rate limit no es el que dice la documentación pública

`app.module.ts:35-43` → `API_LIMIT` o **90 por hora**, TTL 3600 s.
`throttler.provider.ts:10-16` → sólo se aplica a `POST /public/v1/posts`:

```ts
if (method === 'POST' && url.includes('/public/v1/posts')) return super.canActivate(context);
return true;
```

Consecuencias:

- **Los uploads no están limitados.** No existe ninguna cuota de "30 uploads/hora".
- El único límite es sobre **creaciones de post**, contado **por organización** (`getTracker` usa `req.org.id`), no por IP.
- El default del código es 90. En producción estaba en **30**; se subió a **300** el 2026-08-03 (§10, Fase 0).

> ### Por qué se subió a 300
>
> La pasada nocturna borra y recrea **todas** las filas de la ventana: ~10-20 creaciones (§12). Con el techo en 30 quedaba poco margen para pulsaciones del botón y reintentos el mismo día.
>
> **Aplicado: `API_LIMIT` = 300.** Es nuestra instancia, con una sola organización y una API key que es nuestra; el throttle existe para proteger un SaaS multi-inquilino, no este caso.
>
> La alternativa estructural —comparar antes de recrear, con un `GET` (no throttleado) y sólo borrar+crear si algo cambió— ahorraría casi todas esas llamadas. Es mejor ingeniería, pero **no hace falta todavía**.

El batching del worker existe por el límite de **Instagram** (100 publicaciones / 24 h) y por no saturar el orchestrator, **no** por cuota de Postiz.

### 4.4 Postiz tiene webhooks

`post.activity.ts:315` (`sendWebhooks`) se dispara desde el workflow del orchestrator (`post.workflow.v1.0.5.ts:272`) con el post completo en el body, filtrable por integración.

**Matiz crítico:** hoy sólo dispara **en éxito**. Si se agotan los reintentos, el workflow sale antes de llamarlo.

Hay **tres** `return false` en el bucle de `post.workflow.v1.0.5.ts`, y **no todos dejan el post en `ERROR`**:

| Salida | ¿`changeState('ERROR')` antes? |
|---|---|
| `:232` — refresh de token fallido | ✅ Sí, en `:231` |
| `:260` — `bad_body` | ✅ Sí, en `:240` |
| **`:267` — reintentos agotados** | ❌ **No** |

El tercero es alcanzable con el post **todavía en `QUEUE`**: si en las cinco iteraciones el error es siempre `refresh_token` y el refresh funciona, se ejecuta `continue` (`:236`) sin tocar el estado, y al agotarse el bucle se sale por `:267`.

> **Impacto en la Fase 3a:** añadir `sendWebhooks` "en los `return false`" dando por hecho que el estado ya es `ERROR` **no se sostiene en ese camino**. El cambio tiene que poner `changeState('ERROR')` también ahí, o el webhook saldrá diciendo `QUEUE`.
>
> Además hay fallos **anteriores al bucle** (`:86`, `:91`, `:108`, `:123`, `:143`) que tampoco están cubiertos por ese rango.

### 4.4.1 ⚠️ El webhook se dispara hoy con el cuerpo vacío

`post.workflow.v1.0.5.ts:272-276` llama a `sendWebhooks(postsResults[0].postId, …)`. Ese `postId` es **el ID de la red social** (`mediaId` de Instagram), no el `Post.id` interno — véase `updatePost(postsList[i].id, postsResults[i].postId, …)` en `:196-200`, que los usa como cosas distintas.

Pero `getPostByForWebhookId` (`posts.repository.ts:869-875`) busca por `where: { id: postId }`, es decir **por el id interno**. Con el ID de Instagram no encuentra nada y `findMany` devuelve `[]`.

**Resultado: el webhook llega con `[]` como cuerpo.** Se dispara, pero no dice de qué post habla ni en qué estado quedó.

> Todo el cierre reactivo del §9.4 depende de que ese payload traiga el post. **Sin arreglarlo, el diseño no funciona.** Corregido en la `v1.0.6` (§10, Fase 3a).

### 4.4.2 La entrega del webhook no está garantizada

`post.activity.ts:326-340` envuelve el `fetch` en `try { … } catch (e) { /**empty**/ }`. Si n8n está caído o hay timeout, **el fallo se traga sin log y sin reintento**, y el `Promise.all` no propaga nada al workflow.

Un `Publicado` perdido no se recupera solo. **Por eso no se puede eliminar el polling del todo** (§9.4).

### 4.8 Borrar un post termina su workflow

`posts.service.ts:660-677`: `deletePost` busca las ejecuciones de Temporal asociadas y las termina.

```ts
query: `postId="${post.id}" AND ExecutionStatus="Running"`
...
await workflow.terminate();
```

**Esta es la garantía que hace viable el modelo de reconciliación** (§9). Sin ella, borrar y recrear dejaría workflows zombis publicando posts borrados.

### 4.5 Postiz valida el post antes de crearlo

`instagram.provider.ts:48-57` rechaza >10 medias y exige al menos una. El API público ejecuta `validatePosts` antes de crear nada y devuelve un 400 legible. La validación en n8n sigue siendo buena idea (fallar antes es mejor), pero no es la última línea de defensa.

### 4.6 `createPost` devuelve un ID por integración

`posts.service.ts:927` → `[{ postId, integration }]`. De ahí la regla **una fila = un post**.

### 4.7 La limpieza de medios juega a favor

Según [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md):

- `MEDIA_RETENTION_DAYS` (default **30**)
- El filtro es **positivo**: sólo son candidatos los medias cuyo `path` aparece en un `Post` con `state='PUBLISHED'` y `publishDate` anterior a la retención
- Hard-delete **7 días** después del soft-delete

**Un asset subido hoy y programado para dentro de tres semanas no corre ningún riesgo**: no ha sido publicado, luego no es candidato. Y una vez publicado, la copia en Postiz se autolimpia a los ~37 días — que es exactamente lo que queremos, porque el original vive en Notion.

**No hay que tocar `MEDIA_RETENTION_DAYS`.** El default de 30 es correcto en esta arquitectura.

> Esto sólo es cierto porque Notion guarda el máster. Si algún día Postiz volviera a ser el único sitio donde vive el fichero, esta variable pasa a ser una bomba y hay que subirla.

---

### 4.9 ⚠️ Las 3 cuentas usan `instagram-standalone`, no `instagram`

Verificado en la base de datos de producción: las tres integraciones tienen `providerIdentifier = 'instagram-standalone'`.

| Integración | Cuenta |
|---|---|
| `cmqjq77hg0001mw7y2xf6bg86` | Dustin Calderón \| Compositor de Teatro Musical |
| `cmqjqapu00003mw7yrudcwklj` | CITEM Conservatorio Iberoamericano de Teatro Musical |
| `cmqjqfvnw0005mw7yoywgo6he` | AMORISMO VOL III |

*(Existe además una integración de TikTok, `cmqjs6xnx0001q07q9aohapuv`, fuera del alcance de este documento.)*

`instagram.standalone.provider.ts:180-193` delega `post()` al provider normal pero con **`graph.instagram.com`** en vez de `graph.facebook.com`. Consecuencias que cambian el diseño:

**1. `checkValidity` está sobreescrito y valida mucho menos** (`instagram.standalone.provider.ts:46-65`):

```ts
override async checkValidity(...) {
  if (!firstPost?.length) return 'Should have at least one media';
  if (settings?.is_trial_reel) { … }
  return true;
}
```

**No comprueba el máximo de 10 medias ni la regla del audio.** Todo lo que el provider normal rechazaría con un 400 legible, aquí llega hasta Meta. **La validación en n8n deja de ser un lujo y pasa a ser la única red** (§7.4).

**2. El audio nunca se aplica.** `instagram.provider.ts:649-654` exige `type === 'graph.facebook.com'`. Con `graph.instagram.com` la condición es falsa y el parámetro **se descarta en silencio**, sin error. No tiene sentido exponer `audio_id` en Notion.

**3. Los colaboradores sí se envían** — el bloque de `instagram.provider.ts:640-645` no distingue por `type`. Lo que **no está verificado** es que Meta los acepte en la API de Instagram Login. Se comprueba en la Fase 1, publicando uno de verdad.

> **Regla general para este documento:** ante cualquier afirmación sobre validación, manda `instagram.standalone.provider.ts`, no `instagram.provider.ts`. Sólo la lógica de publicación y `handleErrors` son compartidas.

## 5. Restricciones reales de Notion

| Hecho | Valor | Fuente |
|---|---|---|
| Caducidad de la URL de un fichero | **1 hora** (enlace firmado) | [Retrieving files](https://developers.notion.com/docs/retrieving-files) |
| Cómo refrescarla | Volver a pedir la página | idem |
| Tamaño máximo por fichero (plan de pago) | **5 GiB** | [Working with files](https://developers.notion.com/docs/working-with-files-and-media) |
| Almacenamiento total | Sin límite en planes de pago | idem |

De aquí sale la regla más importante de toda la implementación:

> ### ⚠ Nunca se almacena una URL de Notion en ningún sitio.
> Se pide **fresca** en el momento de publicar, siempre. Una URL de Notion guardada es una bomba de relojería de una hora: funciona en la prueba manual y falla en el cron de las 7 AM.

## 6. Reglas innegociables

- ✗ **Postiz nunca escribe en Notion.** Quien cierra el bucle es n8n. Dos escritores = ninguna verdad.
- ✗ **Nunca se aprueba dentro de Postiz.** Dos sitios de aprobación = ninguno fiable en tres semanas.
- ✗ **Nunca hay un LLM dentro del camino de publicación.** La creatividad ocurre antes, en Notion.
- ✗ **Nunca se editan a mano** `postiz_post_id`, `postiz_media`, `release_url` ni `publicación = Programado`.
- ✓ **El `postiz_post_id` dice la verdad, no el `status`.** El status es para las personas; el ID es para la máquina.
- ✓ **Una fila = un post = una integración.** Aunque hoy sólo haya Instagram.

---

## 7. Esquema de Notion — una sola tabla

**Todo vive en el calendario que ya existe**, `collection://186a2405-a123-81dc-832f-000b82a65c0c`. No se crea ninguna tabla nueva: se le añaden las propiedades del pipeline.

### 7.1 Lo que ya tiene y se aprovecha

`Name`, `Status`, `Brand` (4 marcas), `Plataforma` (5), `Tipo`, `Fecha`, `Notas`, `Content Series`, `🌐 Projects`, `URL`, `Compartido con`, `Marcadas`, `Validación`.

Dos alimentan el pipeline sin tocarlas:

| Propiedad existente | Uso |
|---|---|
| `Tipo` | Historia → `post_type = story`; Post · Carrusel · Reel → `post` |
| `Fecha` | La fecha y hora de publicación. **Necesita hora** (§7.5) |

El worker **sólo mira filas con `Plataforma` conteniendo Instagram**. Todo lo demás —LinkedIn, YouTube, ideas sin plataforma— le es invisible.

> ### ⚠️ Deuda conocida: una plataforma por fila
> `Plataforma` es multi-select. Hoy no importa porque sólo se publica en Instagram: si una fila tiene además TikTok, el worker publica en Instagram y el resto lo ignora.
>
> **Disparador para revisar esto:** el día que se quiera publicar en **dos plataformas desde la misma fila**. Instagram y YouTube necesitan copy distinto, formato distinto y devuelven IDs distintos — una fila no puede sostener ambos. Ese día hay que separar la cola a su propia tabla, o pasar `Plataforma` a single-select.
>
> Se acepta a sabiendas: mientras sea sólo Instagram, la granularidad de planificar y la de publicar coinciden, y una segunda tabla sería trabajo sin beneficio.

### 7.2 Las propiedades que se añaden

**Una fila = un post en Postiz.** Cuando una pieza es compartida entre cuentas, **no son varios posts**: publica una cuenta y las demás van como **colaboradoras de Instagram** (§7.2.4). Un post, un ID, un estado.

**Diez propiedades nuevas, ni una más.**

| Propiedad | Tipo | Lo escribe | → API |
|---|---|---|---|
| `cuenta` | **Select** | equipo | `integration.id` (§7.2.1) |
| `colaboradores` | Multi-select | equipo | `settings.collaborators[].label` — **restricciones en §7.2.4** |
| `content` | Text | equipo / agente | `value[0].content` |
| `assets` | **Files** | equipo | `value[0].image[]` — **en orden** |
| `first_comment` | Text | equipo / agente | `value[1].content` (§7.3) |
| `modo` | Select: `borrador`·`programar` | equipo | **`type`** (§7.2.2) |
| `publicación` | Select | equipo → n8n | ✗ — el estado del pipeline (§8) |
| `postiz_post_id` | Text | **n8n** | — el candado |
| `postiz_media` | Text | **n8n** | — JSON `[{id, path}]`, mismo orden que `assets`. Ver aviso |
| `error_log` | Text | **n8n** | — último error |

Y tres cosas que **no** son propiedades nuevas:

- **`post_type`** sale de `Tipo` (§7.1). Es obligatorio en la API (`@IsDefined()` en `InstagramDto`), pero no hace falta pedirlo dos veces.
- **`publish_at`** es `Fecha`, con hora (§7.5).
- **`release_url`** reutiliza la propiedad `URL` que ya existe. *(Si `URL` ya tiene otro uso, se añade una propia — pendiente de confirmar.)*

> **El aviso de error va al correo de quien creó la fila.** No hace falta propiedad: Notion expone `created_by` como metadato de página y n8n lo resuelve a email, con una dirección general de reserva (§10, Fase 3b).

Los tres campos de n8n (`postiz_post_id`, `postiz_media`, `error_log`) son **territorio exclusivo del worker**. Si alguien se ve editándolos a mano, algo se ha roto.

> ### ⚠️ No basta con la URL: `MediaDto` exige `id` **y** `path`
> `media.dto.ts:4-13` declara los dos campos como `@IsDefined()`:
>
> ```ts
> @IsString() @IsDefined()                     id: string;
> @IsString() @IsDefined() @Validate(ValidUrlPath) path: string;
> ```
>
> Mandar sólo la URL en `value[0].image[]` devuelve **400**. Por eso el campo guarda el objeto entero que devuelve `POST /public/v1/upload` (`public.integrations.controller.ts:92-97` → `mediaService.saveFile`), no una lista de URLs:
>
> ```json
> [{"id":"…","path":"https://postiz.dustincalderon.com/uploads/…"}]
> ```

> ### Por qué `publicación` y no ampliar `Status`
> Lo natural sería añadir `Listo`, `Programado` y `Error` al `Status` que ya tienes y tener un único ciclo. **Pero `Status` es de tipo *status* y el DDL de la API de Notion no permite añadirle opciones** — habría que hacerlo a mano.
>
> Además `Status` cubre LinkedIn y YouTube, donde esos estados no significan nada.
>
> Se crea `publicación` aparte para no bloquear el montaje. **Si prefieres un único campo, amplía `Status` a mano y se elimina `publicación`** — el worker sólo necesita saber qué propiedad mirar.

> ### Por qué `cuenta` y no reutilizar `Brand`
> `Brand` es multi-select y sirve para planificar. Si el worker dependiera de que tenga exactamente un valor, sería **una convención que la máquina necesita y no puede verificar** — justo lo que falla un martes cualquiera. Una propiedad explícita cuesta menos que ese riesgo, y `Brand` sigue sin restricciones nuevas.

### 7.2.1 `cuenta` — una opción, un canal de Postiz

Cada opción del select equivale a una integración de Postiz. **La correspondencia vive en un nodo de configuración de n8n**, no en una tabla de Notion — son tres valores fijos que cambian una vez al año:

```
"Dustin Calderón"  → cmqjq77hg0001mw7y2xf6bg86
"CITEM"            → cmqjqapu00003mw7yrudcwklj
"AMORISMO VOL III" → cmqjqfvnw0005mw7yoywgo6he
```

Añadir una cuenta es una línea aquí y una opción en el select.

> **Las opciones de `cuenta` no coinciden con `Brand`.** El calendario tiene Dustin Calderón, CITEM, Los Repertoristas y Vamp; las cuentas de Instagram conectadas son Dustin Calderón, CITEM y **AMORISMO VOL III**. Ni Los Repertoristas ni Vamp tienen Instagram en Postiz, y AMORISMO no es una opción de `Brand`. Otra razón para no reutilizar `Brand` como cuenta.

> Se guarda el ID, no el nombre. Resolver por nombre contra `GET /public/v1/integrations` parece más cómodo, pero se rompe **en silencio** el día que alguien renombre un canal en Postiz.

### 7.2.2 `modo` — borrador o programar

Va directo al campo `type` de `POST /public/v1/posts`:

| `modo` | `type` | Qué hace Postiz |
|---|---|---|
| `programar` | `schedule` | Queda programado y se publica solo |
| `borrador` | `draft` | Se crea en Postiz y **no se publica nunca** |

Por defecto, `programar`.

`borrador` sirve para dos cosas: el **dry-run** de las dos primeras semanas (§10, Fase 3b) y para revisar una pieza en la vista real de Postiz antes de soltarla. Cambiar de `borrador` a `programar` lo recoge el sync en la siguiente pasada, o al pulsar el botón.

> **No contradice "nunca se aprueba en Postiz" (§6).** La aprobación sigue siendo `publicación = Listo` en Notion. `modo` sólo decide qué hace Postiz con algo ya aprobado. Nadie promueve un draft desde la UI de Postiz — si lo hiciera, la siguiente pasada del sync lo revertiría.

### 7.2.3 Ajustes opcionales de Instagram

Se añaden a la tabla el día que se necesiten. Añadir una propiedad en Notion cuesta diez segundos; lo que importa es que el mapeo esté escrito.

| Campo Notion | Tipo | → API | Restricción |
|---|---|---|---|
| `is_trial_reel` | Checkbox | `settings.is_trial_reel` | **Exactamente 1 media, y debe ser vídeo** |
| `graduation_strategy` | Select | `settings.graduation_strategy` | `MANUAL`·`SS_PERFORMANCE`. Sólo con trial reel |
| `thumbnail_seconds` | Number | `image[].thumbnailTimestamp` | **No declarado en `MediaDto`** — sobrevive porque el ValidationPipe no usa `whitelist` (`main.ts:53-57`). Frágil ante merges. Tampoco se envía en stories |

> **`audio_id` no está en la lista a propósito.** Con `instagram-standalone` el parámetro se descarta en silencio (§4.9). Exponerlo en Notion sería ofrecer un botón que no hace nada.

### 7.2.4 Colaboradores — y sus dos restricciones duras

Una pieza compartida entre cuentas es **un solo post**: publica `cuenta` y las demás aparecen como colaboradoras. Eso mantiene el modelo 1:1 con Postiz —un post, un ID, un estado— y evita cualquier fan-out.

`instagram.provider.ts:640-645` manda a Meta los `label` como usernames:

```ts
const collaborators =
  firstPost?.settings?.collaborators?.length && !isStory
    ? `&collaborators=${JSON.stringify(...map(p => p.label))}` : ``;
```

| Formato | ¿Admite colaboradores? | Origen |
|---|---|---|
| Post de imagen única | ✅ Sí | — |
| Reel | ✅ Sí | — |
| **Carrusel** | ❌ **No** | Instagram lo rechaza (`instagram.provider.ts:376-381`) |
| **Story** | ❌ **No** | El código los omite (`!isStory`) |

> ### ⚠️ Un carrusel o una story compartidos son filas separadas
> No hay forma de compartir un carrusel vía colaboradores. Si un carrusel tiene que salir en tres cuentas, son **tres filas** con su propia `cuenta` cada una — y ahí sí son tres posts independientes.
>
> El worker lo valida **antes** de enviar: `colaboradores` con más de un asset o con `post_type = story` → `Error` con el motivo, sin gastar la llamada.

**Los colaboradores son usernames de Instagram, no canales de Postiz.** No hace falta que esas cuentas estén conectadas a Postiz ni que existan en la tabla de §7.2.1.

### 7.3 Los hashtags van en el primer comentario — gratis

`value` es un **array** (`PostContent[]`, mínimo 1). `value[0]` es el post; **`value[1..n]` son comentarios**, cada uno con su `content`, sus `image[]` y un `delay` opcional.

Es decir: publicar los hashtags como primer comentario —práctica estándar en Instagram— **no requiere ningún desarrollo**. Es mandar un segundo elemento en `value`.

Por eso `first_comment` es un campo propio y no parte de `content`: es una decisión editorial distinta y conviene poder verla y editarla por separado.

> **Dos precisiones verificadas:**
> - **Las imágenes de un comentario se ignoran en Instagram.** `instagram.provider.ts:820-860` sólo manda `message=` a `/comments`. Un comentario con ficheros publica sólo el texto.
> - **`delay` está en minutos**, no en segundos ni ms: `post.workflow.v1.0.5.ts:179-180` hace `sleep(60000 * delay)`.

### 7.4 Reglas de validación previas al envío

El worker las comprueba antes de gastar una llamada. Todas verificadas en `instagram.provider.ts`:

**Ojo: estas reglas son para `instagram-standalone` (§4.9), que valida mucho menos que el provider normal.**

| Regla | ¿La para Postiz? | Dónde |
|---|---|---|
| Al menos 1 media | ✅ Sí | `instagram.standalone.provider.ts:50-52` |
| Trial reel: 1 media y vídeo | ✅ Sí | `instagram.standalone.provider.ts:53-63` |
| **Máximo 10 medias** | ❌ **No** | El provider normal sí, el standalone **no**. Llega a Meta |
| **Carrusel: mínimo 2 medias** | ❌ No | Error de Instagram, traducido en `instagram.provider.ts:362-367` |
| **Colaboradores en carrusel** | ❌ No | Error de Instagram, traducido en `instagram.provider.ts:376-381` |
| **Colaboradores en story** | ❌ No | Se **descartan en silencio** (`!isStory`, sin error) |
| **Audio** | ❌ No | Se **descarta en silencio**: exige `graph.facebook.com` (§4.9) |

> ### ⚠️ Cuatro de estas siete no dan error, o lo dan tarde
> Con el provider standalone, **n8n es la única validación real**. Lo que no compruebe el worker, o lo rechaza Meta a mitad de la publicación, o —peor— se aplica a medias sin avisar.
>
> Las dos de "silencio" son las peligrosas: pones colaboradores en una story o un audio en un reel, la publicación sale **correcta pero sin eso**, y nadie se entera. El worker debe rechazarlas explícitamente.

> **Las stories no admiten carrusel.** Si `post_type = story` con varios ficheros, Postiz **publica cada media como una story independiente**. No es un error, es el comportamiento — pero sorprende a quien esperaba una sola pieza.

> **Orden de los ficheros en un carrusel:** el orden de la propiedad `Files` de Notion es el orden de publicación. Es responsabilidad de quien sube los ficheros, y no hay forma de validarlo automáticamente. Es el único punto del sistema donde el orden depende de una persona.

### 7.5 Zona horaria — decidir y probar

**Sí hay conversión, y ahí está la bomba.** `posts.repository.ts:527` persiste con:

```ts
publishDate: dayjs(date).toDate()
```

`dayjs(string)` sin offset explícito parsea en la **zona local del proceso backend**, no en UTC. Y el DTO sólo exige `@IsDateString()` (`create.post.dto.ts:110-112`), que acepta tanto `2026-08-10T19:00:00` como `2026-08-10T19:00:00+02:00`.

**Mandar siempre offset explícito.** Si n8n envía una fecha sin zona, el resultado depende del `TZ` del contenedor de Postiz — y cambia solo si algún día se recrea con otra configuración.

**✅ Verificado con un post real** (§9.8): enviado `10:00:00+01:00`, almacenado `09:00:00`. El contenedor corre en UTC y el offset se respeta. Sin offset publicaría dos horas tarde en verano.

### 7.6 Carruseles: el ratio manda el primero

Instagram recorta todos los elementos de un carrusel al ratio del **primer** elemento. Si los slides no comparten proporción, del segundo en adelante salen recortados.

No se resuelve con código: se resuelve exportando los slides de un carrusel con la misma proporción. Es una convención del equipo, no una validación del worker.

---

## 8. Máquina de estados

Las opciones de la propiedad `publicación` (§7.2):

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

**El equipo sólo escribe `Listo`.** Vaciar la propiedad retira el post de Postiz (§9.7). Todo lo demás es del worker.

El `Status` que ya tienes sigue siendo tuyo y describe la producción de la pieza —Borrador, En progreso, Publicado…— para todas las plataformas. **n8n no lo toca nunca.**

A partir de `Listo` nadie vuelve a tocar `publicación` — pero **sí se puede seguir editando el contenido**: el sync propaga los cambios mientras el post no se haya publicado (§9).

`Programado → Publicado` y `Programado → Error` los escribe n8n al recibir el webhook de Postiz. Ninguna de las dos transiciones necesita polling.

**Con `modo = borrador`** (§7.2.2) la fila sincronizada no va a `Programado` sino a **`En Postiz (borrador)`**. Es un estado propio a propósito: si reutilizáramos `Programado`, alguien daría por hecho que va a salir y no saldría nunca. Desde ahí se pasa a `Programado` cambiando `modo`, no la propiedad `publicación`.

**Postiz no se entera de que la pieza existe hasta que `publicación = Listo`.** El borrador *editorial* vive en Notion y no sale de ahí. Lo que Postiz recibe ya está aprobado; `modo` sólo decide si además queda programado o esperando.

### 8.1 El camino de vuelta desde `Error`

`Error` **no es un sumidero**. Se corrige lo que falló y se devuelve `publicación` a `Listo` vaciando `error_log`.

Al reintentar, el worker **reutiliza `postiz_media` si ya tiene valor** y sólo re-transfiere los ficheros si está vacío. Esto es lo que evita volver a mover un reel de 100 MB por un fallo que ocurrió después de la subida.

> Si el error fue **en el propio fichero** (se subió el vídeo equivocado), hay que **vaciar `postiz_media` a mano** además de cambiar los ficheros. Es la única excepción a "no se editan a mano los campos del worker", y conviene tenerla escrita.

## 9. El worker de n8n — reconciliación, no cola

**Notion declara cómo deben ser los próximos 15 días. El sync hace que Postiz coincida.**

No hay cola que procesar ni estado que recordar. La consecuencia importante: **las ediciones en Notion se propagan solas.** No hace falta detectar qué cambió, ni comparar hashes, ni guardar `last_synced_at`. Cada pasada reescribe la ventana.

### 9.1 Un subflow, dos disparadores

```
   cron 06:00 Europe/Madrid ──► ventana de 15 días ──┐
                                                     ├──► SUBFLOW SYNC (una fila)
   botón "Sincronizar ahora" ──► una fila ───────────┘
```

**Por qué las 06:00 de España:** es una franja muerta en los dos mercados. En España es de madrugada; en LATAM es entre medianoche y las 2-3 de la mañana. Nunca se publica a esa hora, así que el cron nunca coincide con una publicación.

**Regla innegociable: nunca dos implementaciones.** El cron le pasa N filas, el botón le pasa una. Si el botón hace algo distinto que el cron, divergen en tres semanas y se depura a ciegas.

El botón usa la acción **"Send webhook"** de Notion, que en botones de base de datos manda las propiedades de la fila automáticamente. Sólo POST, y sólo propiedades — nos vale, todo lo que necesitamos son propiedades.

### 9.2 Qué hace el subflow con una fila

| Situación | Acción |
|---|---|
| `Plataforma` no contiene Instagram | Invisible para el worker |
| `publicación` vacío | No crear nada — **la retirada (§9.7) lo borra de Postiz si existía** |
| `publicación` = `Publicado` | **No tocar jamás** |
| Dentro del margen de seguridad (§9.3) | **Saltar** + anotar en `error_log` |
| `postiz_post_id` vacío | Crear |
| Tiene `postiz_post_id`, aún no publicado | **Borrar y recrear** |
| `postiz_media` con valor | No re-subir los assets |
| `Fecha` sin hora | `Error` — nunca se adivina la hora (§10, Fase 2) |
| `Fecha` ya pasó y nunca se sincronizó | `Error` + motivo |

> ⚠️ La segunda fila **no es "ignorar y seguir"**. Si sólo se implementa esta tabla y no §9.7, vaciar `publicación` de una fila ya sincronizada deja el post programado en Postiz y **sale publicado igual**. Las dos partes son una sola.

Superadas las puertas, cada fila es **un solo post**, así que el subflow es lineal:

```
1. valida  ≤10 items · tamaño · reglas de §7.4
           colaboradores ⇒ ni carrusel ni story          (§7.2.4)
2. resuelve `cuenta` ──► integration.id                  (§7.2.1)
3. si tiene postiz_post_id y no está publicado ──► DELETE primero
4. si `postiz_media` está vacío:
      pide a Notion la URL FRESCA de cada fichero   ← nunca una guardada
      descarga los bytes
      sube multipart a POST /public/v1/upload
      └──► ESCRIBE postiz_media                      [write 1]
5. POST /public/v1/posts
      type                        = modo                 (§7.2.2)
      value[0].content            = content
      value[0].image[]            = postiz_media
      value[1].content            = first_comment        (si lo hay, §7.3)
      settings.collaborators[]    = colaboradores        (si los hay)
      └──► ESCRIBE postiz_post_id                        [write 2]
           publicación = Programado           si modo = programar
           publicación = En Postiz (borrador) si modo = borrador
```

> **No hay fan-out.** Una pieza compartida entre cuentas es un post con colaboradores (§7.2.4), no N posts. Eso mantiene el 1:1 con Postiz —un ID, un estado, un `release_url`— y elimina cualquier necesidad de estados parciales o de una tabla intermedia.
>
> La excepción son los **carruseles y stories compartidos**, que Instagram no permite compartir: ahí son filas independientes, y cada una sigue siendo un post. El modelo no cambia.

Las dos escrituras siguen separadas: guardar `postiz_media` en cuanto sube hace el proceso **reanudable a mitad**, y evita volver a mover un reel de 100 MB en cada resincronización.

### 9.3 El margen de seguridad — obligatorio

**No se toca ninguna fila cuyo `publish_at` esté dentro de las próximas 2 horas.**

Borrar y recrear abre una ventana en la que el post no existe en Postiz. Hacerlo cerca de la hora de publicación es una carrera contra el orchestrator, con dos finales malos: el post se pierde, o se recrea con una fecha ya pasada y el comportamiento deja de ser predecible.

> **Este guardarraíl vive en el subflow, no en el horario del cron.** La hora del cron (06:00 Europe/Madrid) ya garantiza que **el cron** nunca colisione con una publicación. Pero **el botón se dispara cuando alguien lo pulsa**, y antes o después alguien va a tocar un post veinte minutos antes de que salga. El guardarraíl existe por el botón, no por el cron. Son tres líneas en el subflow.

Si una fila cae dentro del margen, el sync **no hace nada** y lo anota. Si hay que cambiar algo a 20 minutos de publicar, se hace a mano en Postiz — es la única excepción a "nunca se aprueba en Postiz", y es una excepción de emergencia.

### 9.4 Cierre del bucle: reactivo

Con el webhook de fallo añadido (§4.4, §10 Fase 3a), **publicado y fallido llegan por el mismo canal**:

```
Postiz publica (o falla) ──webhook──► n8n ──► status      = Published | Error
                                              release_url = permalink   (si publicó)
                                              error_log   = motivo      (si falló)
```

n8n mira el `state` del post que llega en el payload y escribe en Notion.

> ### ⚠️ El webhook es el camino rápido, no el único
> La entrega es best-effort y sin reintento (§4.4.1): si n8n está caído cuando Postiz publica, ese aviso **se pierde para siempre**.
>
> Por eso el cron de las 06:00 hace además una **pasada de recuperación**: para toda fila en `Programado` cuya `Fecha` ya pasó con margen, consulta el estado real en Postiz y corrige. Es barato —va incluido en el `GET` que ya hace la retirada (§9.7)— y es lo único que evita que una fila se quede en `Programado` para siempre.

> **`release_url` sólo puede venir de aquí.** `createPost` devuelve únicamente `[{postId, integration}]` (`posts.service.ts:927`); el permalink no existe hasta que el post sale de verdad, y lo escribe `updatePost` en el workflow. Si el webhook no está montado, ese campo se queda vacío para siempre.

### 9.5 Por qué borrar y recrear, y no actualizar

Semántica inequívoca: el resultado es el estado correcto sin importar qué cambió. Cuesta dos llamadas en vez de una, irrelevante frente a las 300/hora de `API_LIMIT`.

Es seguro por §4.8: `deletePost` termina el workflow de Temporal asociado.

Y **no pone en riesgo los assets** — pero por una razón distinta a la que parece:

- El **Step 2** de la limpieza cuenta los posts soft-deleted como prueba de uso, y eso **convierte el media en candidato a borrado**, no lo protege (`media.repository.ts:304-319`; el comentario del propio código lo dice).
- Quien **protege** es el **Step 3** (`media.repository.ts:338-350`), que exige `p."deletedAt" IS NULL`.

Un post recreado está vivo y sin borrar, luego protege sus ficheros. La conclusión se sostiene; **el razonamiento intuitivo es el contrario del que aplica el código**, y conviene tenerlo escrito para no equivocarse en el próximo cambio.

> **Consecuencia a saber:** `postiz_post_id` cambia en cada resincronización. Es "el post actual en Postiz", no un identificador estable en el tiempo. n8n lo reescribe cada vez, así que Notion siempre tiene el vigente.

### 9.6 El candado que evita duplicados

Crear sólo si `postiz_post_id` está vacío.

Escenario: n8n crea el post y justo antes del write-back se cae el contenedor. La fila queda sin ID. La siguiente pasada la vuelve a crear → **post duplicado en producción**.

El candado actual lo hace improbable, no imposible. La solución definitiva es `externalId` en Postiz (§10, Fase 3a): con un índice único por organización, el duplicado pasa a ser **imposible por construcción** y n8n deja de tener que acordarse de nada.

### 9.7 La pasada de retirada — sin ella el sync sólo sabe añadir

**Reconciliar no es sólo crear lo que falta: es también retirar lo que ya no debe existir.**

El subflow de §9.2 itera sobre las filas de Notion. Todo lo que desaparece de esa lista se vuelve invisible para él — y el post correspondiente **se queda programado en Postiz y se publica igual**. Tres formas de provocarlo, todas normales:

| Acción en Notion | Sin pasada de retirada |
|---|---|
| Se borra la fila | El post se publica igualmente |
| `publicación` vuelve de `Listo` a vacío | El post se publica igualmente |
| `publish_at` se mueve fuera de la ventana | Se publica en la fecha vieja |

El segundo es el más traicionero: la regla "`status` ∈ (Idea, Draft) → ignorar" hace exactamente lo contrario de lo que la gente espera. Alguien retira un post a borrador para repensarlo, y sale publicado.

**La pasada:** tras sincronizar la ventana, pedir a Postiz lo que tiene programado en ese mismo rango y **borrar todo lo que no tenga una fila viva detrás**.

```
GET /public/v1/posts?startDate=...&endDate=...   ← existe: GetPostsDto
   └─ FILTRAR por state en el propio n8n           ← ver aviso
   └─ para cada post aún no publicado en la ventana:
        ¿sigue habiendo una fila viva en Notion que lo reclame?
          (viva = publicación en Listo · Programado · En Postiz (borrador))
          no ──► DELETE /public/v1/posts/:id
```

> ### ⚠️ El endpoint no filtra por estado
> `posts.repository.ts:129-172` **no filtra por `state`**: devuelve también `PUBLISHED`, `ERROR` y `DRAFT`. Y con `intervalInDays` no nulo puede devolver posts **fuera de la ventana** (`:152-157`).
>
> Si la retirada borrase todo lo que no reconoce, **borraría posts ya publicados**. El filtro por estado lo tiene que hacer n8n.

El emparejamiento es por `postiz_post_id` mientras no exista `externalId`; en cuanto exista (Fase 3a), es directo y no depende de que Notion conserve el ID.

> Aplica el mismo margen de seguridad de §9.3: nada dentro de las próximas 2 horas se retira automáticamente.

### 9.8 El cuerpo exacto de `POST /public/v1/posts`

**✅ Ejecutado de punta a punta el 2026-08-03**, no sólo derivado de los DTOs. Se subió un fichero, se creó un post programado para 2027 y se borró. Resultados abajo.

Ejemplo real para una de las tres cuentas:

```json
{
  "type": "schedule",
  "shortLink": false,
  "date": "2026-08-14T08:00:00+02:00",
  "tags": [],
  "posts": [
    {
      "integration": { "id": "cmqjq77hg0001mw7y2xf6bg86" },
      "settings": {
        "__type": "instagram-standalone",
        "post_type": "post",
        "collaborators": [{ "label": "citem_oficial" }]
      },
      "value": [
        {
          "content": "El copy de la pieza…",
          "image": [
            { "id": "<id de /upload>", "path": "https://postiz.dustincalderon.com/uploads/2026/08/04/abc.jpg" }
          ]
        },
        { "content": "#hashtag1 #hashtag2", "image": [] }
      ]
    }
  ]
}
```

#### Los cinco campos que dan 400 si se olvidan

| Campo | Regla | Nota |
|---|---|---|
| `shortLink` | `@IsDefined() @IsBoolean()` | **No es opcional.** Omitirlo es 400 aunque no uses acortador |
| `tags` | `@IsDefined() @IsArray()` | Debe existir aunque sea `[]` |
| `date` | `@IsDefined() @IsDateString()` | **Con offset explícito** (§7.5) |
| `settings.__type` | `@IsIn(...)` | **`instagram-standalone`**, no `instagram` |
| `settings.post_type` | `@IsDefined()` | `post` o `story` |

> **`__type` decide qué provider resuelve.** `posts.service.ts:883-885` hace `getSocialIntegration(settings.__type)`. Poner `instagram` en una cuenta `instagram-standalone` resolvería el provider equivocado, con otras validaciones y otro host de Meta (§4.9).

> **`value[0].image[]` necesita `id` y `path`.** Sólo la URL da 400 (§7.2). El `id` sale de la respuesta de `POST /public/v1/upload`.

#### Respuestas reales medidas

| Llamada | Status | Cuerpo |
|---|---|---|
| `POST /upload` (multipart, campo `file`) | **201** | `{id, name, originalName, path, thumbnail, alt}` |
| `POST /posts` | **201** | `[{postId, integration}]` |
| `DELETE /posts/:id` | **200** | `{"error":true}` ⚠️ |

> ### ⚠️ `DELETE` devuelve `{"error":true}` aunque funcione
> Confirmado ejecutándolo: el post y su comentario quedaron correctamente soft-deleted, y aun así la respuesta fue `{"error":true}` con 200. `posts.service.ts:681` devuelve eso siempre.
>
> **n8n no puede usar el cuerpo como señal de éxito.** Si necesita certeza, tiene que releer el estado; en la práctica basta con no tratar esa respuesta como fallo.

#### Zona horaria — resuelta con una medición

Enviado `"date": "2027-01-15T10:00:00+01:00"` → almacenado `2027-01-15 09:00:00`.

El contenedor de Postiz corre en **UTC** (`TZ` vacío) y `dayjs(date).toDate()` **respeta el offset explícito**. La columna guarda UTC.

> **Consecuencia:** mandar la fecha **sin offset** la interpretaría como UTC. En horario de verano de Madrid (+02:00) eso publicaría **dos horas tarde**. n8n debe enviar siempre el offset.

#### El comentario funciona

`value[1]` creó un `Post` hijo con `parentPostId` no nulo y **la misma `publishDate`**. Los hashtags en primer comentario (§7.3) están confirmados en la práctica, no sólo en el código.

### 9.9 La ventana de 15 días

Un post programado para dentro de 20 días **no existe en Postiz todavía**, y eso es correcto: nada se crea antes de tiempo. Entra en la ventana cuando le toca.

El equipo debe saberlo para que nadie se alarme al no encontrar en Postiz algo que sí está en Notion. **Notion es la verdad; Postiz sólo refleja los próximos 15 días.**

---

## 10. Plan por fases

### Fase 0 — Desbloquear · **EJECUTADA Y VERDE**

Estado real del contenedor `postiz` en el Beelink:

```
STORAGE_PROVIDER=local
UPLOAD_DIRECTORY=/uploads
MAIN_URL=FRONTEND_URL=https://postiz.dustincalderon.com
CLOUDFLARE_BUCKET_URL=…r2.dev/      ← ANTES; se le quitó la barra final. Inactivo
API_LIMIT=30                        ← ANTES del cambio; hoy 300 (ver más abajo)
```

Con `local`, la URL pública es `FRONTEND_URL + /uploads + /YYYY/MM/DD/<32 hex>.<ext>` (`local.storage.ts:76,109`).

**Prueba de alcance externo — y el falso positivo que generó:**

La primera medición dio 403 al pedir `/uploads/…` desde fuera, y de ahí se concluyó que el WAF bloqueaba IPs de datacenter (la clase de origen desde la que hace fetch Meta). **Esa conclusión era falsa.** El control correcto es variar el user-agent desde una IP fija:

| Desde el Beelink · misma IP · mismo path | Resultado |
|---|---|
| UA vacío | **200** |
| `python-requests/2.31` | **200** |
| `facebookexternalhit/1.1` | **200** |
| `ClaudeBot/1.0` | **403** |

El discriminante es **el user-agent, no la IP**. El `robots.txt` del dominio sirve la política de Content Signals de Cloudflare: **bloquea crawlers de IA**. El 403 original era el bloqueo del propio agente que hacía la comprobación, no una limitación de la infraestructura.

> ### ⚠️ Lección metodológica
> Una sola medición variaba **dos** cosas a la vez (origen y user-agent) y se atribuyó el efecto a la equivocada. Toda comprobación de alcance debe fijar una variable y mover la otra.
>
> **Consecuencia operativa permanente:** las URLs de este dominio **no se pueden verificar con un agente de IA** — siempre darán 403. Las comprobaciones de alcance se hacen con `curl` desde el Beelink variando el UA, o desde un móvil con datos.

**Conclusión: `local` es viable.** Meta obtiene 200. El cambio a R2 **no era necesario** por alcance.

### Estado final aplicado (2026-08-03)

Copia de seguridad en `/opt/homeserver/postiz/postiz.env.bak-20260803`.

| Variable | Valor | Cambiado |
|---|---|---|
| `STORAGE_PROVIDER` | **`local`** | No — se probó `cloudflare` y se revirtió |
| `UPLOAD_DIRECTORY` | `/uploads` → bind mount a `/mnt/seagate/postiz-media` | No |
| `API_LIMIT` | `30` → **`300`** | **Sí** (§4.3) |
| `CLOUDFLARE_BUCKET_URL` | sin barra final | **Sí** (inactivo, pero correcto si algún día se usa) |

Verificado tras recrear: contenedor `healthy`, tres procesos online con **0 reinicios**, `/uploads` intacto (214 MB, 33 ficheros), y `facebookexternalhit/1.1` → **200**.

**Los medios se almacenan en el propio Postiz**, sobre el Seagate. No hace falta R2 ni ningún almacenamiento externo.

> ### ⚠️ El Seagate es USB y `/uploads` es un bind mount
> Si `/mnt/seagate` se desmonta, Docker sirve el bind desde un directorio vacío del disco de sistema: **toda la biblioteca de medios desaparece en caliente** (404 en cada imagen) y las subidas nuevas llenan el disco del Beelink en silencio.
>
> Es el mismo riesgo que en su día justificó descartar los watchers (§13), sólo que aquí ya existe y no lo introduce este proyecto. Merece una comprobación de montaje en el arranque, pero es trabajo de infraestructura, no de este pipeline.

### Fase 1 — La cola a mano, dos semanas · coste cero

> **La pregunta "¿hace falta Notion?" ya está respondida.** El calendario de §7.1 lleva tiempo en uso, con cuatro marcas, series de contenido y proyectos relacionados. No hay nada que probar ahí.
>
> Lo que sí está sin probar es **la disciplina que exige la cola**: una fila por post, hora obligatoria, elegir `cuenta` y `colaboradores`, marcar `Listo`. Si el equipo no la llena, el sync automatizaría una tabla vacía.

**Crear la cola (§7.2) y llenarla a mano durante dos semanas, publicando también a mano desde Postiz.** Sin n8n, sin webhooks, sin nada automático.

Lo que se aprende, y sale gratis:

- Si el modelo de colaboradores encaja con cómo publicáis de verdad, o si acabáis desdoblando filas más de lo previsto.
- Cuántos carruseles y stories compartidos hay — son los que **no** admiten colaboradores (§7.2.4) y obligan a filas separadas.
- Qué campos sobran y cuáles faltan — **antes** de que haya un worker acoplado al esquema.
- La convención de zona horaria, publicando de verdad.

Si a las dos semanas la cola está llena y al día, el sync merece la pena. Si está a medias, el problema no es de automatización y automatizarlo lo empeora.

### Fase 2 — Notion · **PROPIEDADES CREADAS (2026-08-03)**

**4. ✅ Hecho.** Las 10 propiedades de §7.2 están creadas en `collection://186a2405-a123-81dc-832f-000b82a65c0c`, con descripción en cada una y las opciones de `cuenta`, `modo` y `publicación` ya pobladas. No se creó ninguna tabla.

**5. ✅ Resuelto — la hora en `Fecha` está activada.**

El `time_format: " "` que devolvía el esquema era la opción **«Oculto»** del desplegable *Formato de hora* de la propiedad. Cambiado a **24 horas** el 2026-08-03.

Es un **ajuste de propiedad**, no un interruptor por valor: al quitarlo de «Oculto», toda la columna admite y muestra hora.

Verificado sobre la base real: la fila «Tres cosas básicas…» guarda `2026-08-01T09:00:00.000+02:00`, con offset de Madrid correcto.

> ### ⚠️ Las 99 filas anteriores siguen sin hora
> Medido antes del cambio: sólo 1 de 100 filas con fecha incluía hora. Las históricas se quedan a día seco, y ninguna fila nueva nace con hora por defecto — hay que escribirla.
>
> **Regla obligatoria del worker:** si `Fecha` no trae hora, la fila va a `Error` con el motivo, **nunca se adivina**. Asumir medianoche publicaría a las 00:00 sin que nadie lo pidiera.
>
> Se mitiga poniendo una hora por defecto en la **plantilla de página** de la base.

El esquema devuelve `"Fecha": { "time_format": " " }` — el campo **no muestra hora**. Notion sí puede guardar `datetime` (existe `date:Fecha:is_datetime`), pero mientras el formato no incluya hora, quien rellene la fila **verá sólo el día** y no podrá elegir la hora.

Sin hora, `publish_at` no existe y el worker no sabe cuándo publicar. **Es bloqueante para la Fase 3b.**

> En Notion: abrir la propiedad `Fecha` → *Formato de fecha* → activar **Incluir hora**. El DDL de la API no permite cambiar el formato de visualización.

**6. ✅ Hecho — las dos vistas.**

| Vista | Filtro | Para qué |
|---|---|---|
| **IG · Publicación** | `Plataforma` contiene Instagram, orden por `Fecha` | Donde trabaja el equipo |
| **⚠️ Averías** | `publicación = Error` | Panel de fallos: cuenta, motivo e id |

**7. ✅ Hecho — opciones de `colaboradores`.** Sembradas con los usernames reales de Instagram, sacados del campo `profile` de `GET /public/v1/integrations`: `thedustincalderon`, `citem.teatromusical`, `amorismoelmusical`.

> Nota menor: el `ALTER` que puso las opciones **borró la descripción** de esa propiedad. Reponerla a mano si molesta.

**8. ✅ Resuelto — la integración de Notion ya existe.** El token de `#ARCHIVE/Motion_to_Notion/.env` ya tiene acceso al calendario por herencia. Ver Fase 3b.
> **El botón no se crea aquí**, sino en la Fase 3b: necesita la URL del webhook de n8n, que todavía no existe.

### Fase 3a — Los dos cambios en el fork · 2-3 h

Criterio para tocar el fork: **sólo donde la alternativa es imposible o frágil, nunca donde es sólo incómoda.** Y siempre **aditivo** — ficheros nuevos, columnas nuevas, env vars nuevos. Editar el interior de servicios compartidos (`posts.service.ts`, `instagram.provider.ts`) es donde nacen los conflictos con upstream.

**9. ✅ HECHO — `post.workflow.v1.0.6.ts`.** Tres arreglos, ninguno toca la `v1.0.5`:

| # | Arreglo | Por qué |
|---|---|---|
| 1 | `sendWebhooks(postsList[0].id, …)` en vez de `postsResults[0].postId` | El payload llegaba **vacío** (§4.4.1) |
| 2 | `notifyFailure()` en los tres `return false` | El webhook sólo salía en éxito (§4.4) |
| 3 | `changeState('ERROR')` en el camino de reintentos agotados | Ese camino salía con el post en `QUEUE` (§4.4) |

Cambios asociados: `workflows/index.ts` exporta la nueva versión, `posts.service.ts:729` arranca `postWorkflowV106`, y la llamada recursiva de `repeat-post` (`:442`) apunta a sí misma.

Verificado: `tsc --noEmit` sin errores en los ficheros tocados, y `post.workflow.v1.0.5.ts` sin cambios.

> ⚠️ **No se edita `v1.0.5` a propósito.** Los workflows de Temporal deben ser deterministas en el replay: cambiar una definición con ejecuciones en vuelo las rompe. Por eso el repo tiene un fichero por versión. Las ejecuciones antiguas siguen resolviendo contra la suya.

**✅ DESPLEGADO el 2026-08-03** (commit `2facd00f`). Evidencia de que entró de verdad:

| Comprobación | Resultado |
|---|---|
| Bundle de workflows de Temporal | **14 → 15 módulos** (60.9 → 72 KiB) |
| Fichero compilado | `dist/…/post.workflow.v1.0.6.js` presente |
| Contenedor | `healthy`, 3 procesos, **0 reinicios** |
| `backend-error.log` | vacío |

Ventana elegida: sólo había **1 post en cola, para el 14 de agosto**. Su workflow arrancó como `V105`, que sigue exportada.

> ### ⏳ Sin verificar en funcionamiento
> El arreglo está desplegado y typechecked, pero **nadie ha visto el webhook llegar con contenido**. Requiere publicar de verdad con un destino configurado. Es la primera prueba de la Fase 3b.

**10. `externalId` — ⏸️ NO se hizo, a propósito.** Columna nullable en `Post` + índice único `[organizationId, externalId]` + comprobación en `createPost` que devuelva el post existente en vez de crear otro.

Da idempotencia al worker, pero **sin worker no tiene consumidor**: sería una migración sobre la base de producción para un llamante que aún no existe. Se hace cuando el sync esté montado y se sepa qué necesita de verdad.

### Fase 3b — El sync en n8n · **PARCIAL: planificador montado y probado**

**Credenciales creadas en n8n** (esto además retira el token de Notion del repo archivado):

| Credencial | Tipo | ID |
|---|---|---|
| `Postiz API (CITEM org)` | `httpHeaderAuth` → `Authorization` | `h6bGMcfTHiZUD0dy` |
| `Notion — Calendario Social Media` | `httpHeaderAuth` → `Authorization: Bearer` | `5rCv9a6s5FyI0swq` |

**Workflow `k3QqOu4nQJGJMXuO` — «Postiz · Sync Instagram desde Notion (PLANIFICADOR)»**

Cron 06:00 + webhook → lee el calendario → **decide qué haría, sin escribir nada**. Implementa todas las puertas de §9.2 y las validaciones de §7.4: ventana de 15 días, margen de 2 h, `Fecha` sin hora, cuenta sin `integration.id`, >10 assets, colaboradores en carrusel o story.

**Ejecutado contra los datos reales (2026-08-03):**

```
filas de Instagram evaluadas: 99
  99  ignorar   (publicación vacía en todas)
acciones que se ejecutarían: 0
```

Correcto: **el pipeline está inerte hasta que alguien marque `Listo`.** Nada que arreglar en los datos existentes.

**🔒 Webhook protegido.** Se detectó que al activar el workflow, n8n exponía `POST /webhook/postiz-sync-ig` **sin autenticación**, y la respuesta del planificador incluye contenido de filas de Notion.

Corregido: el nodo Webhook exige ahora la cabecera **`X-Sync-Token`** (credencial `4jg5NXem2BvjFtFO`). El valor está en `/tmp/wf/token.txt` del servidor — **moverlo a `/opt/homeserver/.env` antes de que se limpie `/tmp`**.

Ese mismo token es el que tendrá que enviar el botón de Notion (§9.1).

**Sigue DESACTIVADO** hasta que exista la mitad que escribe: activar sólo el planificador no aporta nada y deja un endpoint más expuesto.

**Lo que falta del sync** (la mitad que escribe): descarga del asset desde Notion → `POST /upload` → `POST /posts` → write-back a Notion, más la pasada de retirada (§9.7) y el receptor del webhook de Postiz.

---

#### Referencia para completarlo

**Lo que ya está resuelto para montarlo:**

| Dato | Valor |
|---|---|
| n8n | `auto.dustincalderon.com` · API pública operativa · clave en `/opt/homeserver/.env` (`N8N_API_KEY`) |
| API de Postiz | `https://postiz.dustincalderon.com/api/public/v1` |
| Auth de Postiz | Cabecera `Authorization: <apiKey>` de la organización **`30c506a6-0a2c-4661-95bb-abec2e14b3f2`** — la única con integraciones |
| Cuentas | Los 3 `integration.id` de §7.2.1 |
| Cuerpo del POST | §9.8, con los cinco campos que dan 400 |

> **Ningún workflow actual de n8n usa el nodo de Notion** — todos van por `httpRequest`. Conviene seguir ese patrón: llamar a la API de Notion directamente en vez de introducir un nodo nuevo.

**Token de Notion: ✅ ya existe y ya tiene acceso.**

Vive en `D:\Code Projects\#ARCHIVE\Motion_to_Notion\.env` como `NOTION_API_KEY` (prefijo `ntn_`). Se creó para el sync Motion→Notion, pero **hereda acceso al calendario** porque su `NOTION_AREAS_DB_ID` (`852bcd83…`) es un ancestro suyo en el árbol, y los permisos de Notion bajan por la jerarquía.

Verificado contra la API real:

| Llamada | Resultado |
|---|---|
| `GET /v1/databases/186a2405…` | **200** — devuelve "Calendario Social Media" |
| `POST /v1/databases/186a2405…/query` | **200** — devuelve filas |

> ### ⚠️ Deuda: el token vive en un repo archivado
> `#ARCHIVE/Motion_to_Notion` es un repo muerto. Si se borra, se pierde la referencia al token — aunque la integración siga viva en Notion.
>
> **Al montar la Fase 3b, guardarlo como credencial de n8n** (que es su sitio) y añadirlo a `/opt/homeserver/.env` junto al resto. No dejarlo dependiendo de una carpeta archivada.

11. **Fijar y probar la zona horaria** (§7.5) con un post real. Antes que nada más.
12. Subflow de sync (§9.2) con el margen de seguridad (§9.3).
13. Cron a las **06:00 Europe/Madrid** sobre la ventana de 15 días, **con la pasada de retirada** (§9.7).
14. **A mano en la UI de Notion** (la API no permite crearlos, §9.1): propiedad Botón `Sincronizar ahora` → acción *Enviar webhook* → URL de n8n. Opcionalmente, automatización `publicación → Listo` → mismo webhook. Ambos apuntan **al mismo subflow**.
15. Receptor del webhook de Postiz → `Published` / `Error`.
16. **Dry-run — pero NO con `modo = borrador`.**

> ### ⚠️ Los drafts se saltan la validación entera
> `public.integrations.controller.ts:219` → `if (body.type !== 'draft')`. Todo el bloque que lanza `PostValidationException` (`:220-231`) **no se ejecuta para drafts**. Sólo se comprueba `emptyContent`.
>
> Un post que fallaría en `programar` **se crea sin una queja en `borrador`**. Usar drafts como dry-run no valida nada de lo que se quiere validar: da una falsa sensación de que todo está bien.
>
> **El dry-run real es programar de verdad con fechas lejanas** y revisarlas en la UI de Postiz antes de que lleguen, o publicar en una cuenta de prueba. `modo = borrador` se queda como aparcadero editorial, no como red de seguridad.
17. Alerta por **email al creador de la fila** (`created_by` de Notion) cuando pase a `Error`, con dirección general de reserva.

### Fase 4 — La capa creativa · el motivo de todo esto

18. Redacción de borradores con Claude vía **Notion MCP**, creando filas con el copy ya escrito y `publicación` vacío, listas para revisar.
19. Sistema de captura de materia prima: ideas, objeciones reales de clientes, ángulos.

> **Esta fase no necesita que se construya nada antes.** Está disponible desde el primer día, y es la única razón por la que las fases 2 y 3 merecen la pena. Si el copy se va a escribir a mano igualmente, el proyecto entero es una UI peor para algo que Postiz ya hace.

---

## 11. Decisiones abiertas

**Pendientes:**

| # | Decisión | Bloquea | Notas |
|---|---|---|---|
| 1 | ~~Formato y zona horaria~~ | — | **Resuelta:** offset explícito, contenedor en UTC (§9.8) |
| ~~2~~ | ~~Tope de tamaño~~ | — | **Resuelta: 300 MB.** Reels reales de 150-250 MB |
| ~~3~~ | ~~¿`URL` libre?~~ | — | **No.** Creada propiedad `release_url` aparte |
| ~~4~~ | ~~Dirección de reserva~~ | — | **`contacto@dustincalderon.com`** |
| 5 | Qué pasa si el sync entero falla | Fase 3b | Notion caído a las 06:00: reintentos + alerta distinta |
| 6 | ¿Meta acepta `collaborators` en `graph.instagram.com`? | — | **Deuda técnica.** No se probará de momento (decisión del 2026-08-04) |

**Resueltas:**

| Decisión | Valor |
|---|---|
| ¿Hace falta Notion? | **Sí** — el calendario de §7.1 lleva tiempo en uso |
| ¿Las 3 cuentas están en Postiz? | **Sí**, ya conectadas |
| Alcance | **Instagram, 3 cuentas** (`instagram-standalone`, §4.9) |
| Estructura en Notion | **Una sola tabla** — el calendario existente, con 10 propiedades más (§7.2) |
| IDs de integración | Los tres, verificados en la base de datos (§7.2.1) |
| Piezas compartidas entre cuentas | **Un post con `collaborators`**, no N posts (§7.2.4) |
| Estado del pipeline | Propiedad `publicación`, separada del `Status` humano (§7.2) |
| Alertas | **Email al creador de la fila** (`created_by`), con dirección general de reserva |
| Archivo en Drive | **Después**, cuando el pipeline funcione. Trabajo aparte, fuera del camino de publicación |
| Plan de Notion | **De pago** → el botón webhook es viable |
| Margen de seguridad | **2 h** (§9.3) |
| Ventana | **15 días** (§9.9) |
| Hora del cron | **06:00 Europe/Madrid** (§9.1) |

> **Ninguna bloquea el arranque.** Las propiedades se pueden crear ya; la #3 sólo decide si `release_url` reutiliza `URL` o es propia.

## 12. Riesgos

**Los bytes pasan por la memoria de n8n.** Los reels reales pesan **150-250 MB** y se descargan de Notion y se suben a Postiz a través del Beelink. **Tope fijado en 300 MB**, fallando con un error legible en vez de descubrirlo con un contenedor muerto.

Sigue siendo el riesgo operativo número uno, y a esa escala no es teórico: hay que medir el consumo real de n8n con el primer reel de verdad antes de confiar en el cron.

**Notion es ahora un punto único de fallo.** Es la contrapartida de que sea SSoT de verdad. Mitigación razonable: exportación periódica del workspace. No es urgente, pero conviene no ignorarlo.

**Rate limits en cascada.** `API_LIMIT` = 300 creaciones/hora en Postiz (nuestro) + 100 publicaciones/24 h en Instagram (suyo, innegociable, **por cuenta**).

Con el modelo de colaboradores, **una pieza compartida entre las tres cuentas es una sola fila**. A 3-5 piezas por semana, la ventana de 15 días contiene **~7-11 filas**, más las que sean carrusel o story compartidos, que sí se desdoblan (§7.2.4). Digamos **10-20**. La pasada nocturna las borra y recrea todas: **~20 creaciones sobre un techo de 300**.

> ### Corrección de una estimación anterior
> Una versión previa de este documento calculaba ~30 filas y presentaba `API_LIMIT=30` como un choque frontal. Ese número asumía **una fila por cuenta**, un modelo que los colaboradores eliminaron. La cifra real es unas tres veces menor.
>
> Subir `API_LIMIT` a 300 sigue estando bien —30 dejaba poco margen para pulsaciones del botón y reintentos el mismo día— pero **la urgencia estaba sobreestimada**. Con 30 probablemente habría funcionado.

Crece de forma lineal con ventana × frecuencia, y **por plataforma nueva**: YouTube no se comparte con colaboradores, así que cada pieza que vaya a YouTube es una fila más. Al añadirlo, rehacer esta cuenta **antes**, no después.

> Es el precio de "reescribir siempre en vez de detectar cambios" (§9). A esta escala compensa de largo: la alternativa —hashes o `last_edited_time`— es estado que mantener y sincronizar. Si algún día no compensara, el arreglo es comparar antes de recrear, y sólo entonces.

**Deuda técnica: tres organizaciones en Postiz, dos vacías.** `Organization` tiene tres filas —`CITEM` (`30c506a6…`, con las 4 integraciones), otra `CITEM` (`8019c9c4…`, vacía) y `Test` (`4d1bbcd5…`, vacía)—, cada una con su `apiKey`.

El pipeline usa la de `30c506a6…`, que es la única que ve las cuentas. Las otras dos no molestan hoy, pero son API keys vivas apuntando a organizaciones sin contenido, y el throttle de `API_LIMIT` se cuenta por organización. **Auditar y limpiar en otro momento** — no bloquea nada.

**Marca de agua de CapCut.** Algunas plantillas y efectos la añaden al exportar. Publicando a mano se ve; publicando en automático, no. Revisar el máster la primera vez que se use una plantilla nueva.

## 13. Lo que se decidió NO hacer

Esta sección existe para que el plan no vuelva a crecer. Cada línea fue considerada y descartada.

| Descartado | Por qué |
|---|---|
| Biblioteca en `/srv/media` (Seagate) | Para un equipo es peor: exige LAN o Nextcloud sincronizado por persona. Notion es un login web. |
| Watchers de directorios | Era el único componente que podía romper algo **en silencio** (escribir sobre un punto de montaje desmontado y llenar el disco del Beelink). Se elimina por borrado, no por mitigación. |
| Normalización con ffmpeg / ImageMagick | Se sustituye por una convención de exportación. Una convención sale gratis; un script hay que mantenerlo. Se añadirá el día que Instagram rechace algo de verdad. |
| Archivo de material en bruto (raw) | Es un proyecto legítimo, pero **es otro proyecto**. Archivar no tiene nada que ver con publicar; mezclarlos hace que ninguno arranque. |
| Estructura de tres niveles (raw / master / delivery) | Consecuencia del anterior. |
| Subir `MEDIA_RETENTION_DAYS` | Innecesario: con Notion como SSoT, la limpieza a los ~37 días es una función, no un riesgo (§4.7). |
| MinIO o cualquier S3 propio | Imposible: el endpoint de R2 está hardcodeado (§4.2). |
| Evitar `upload-from-url` | El bug del path sin extensión **no existe en este fork**: la extensión se deriva del magic-number del buffer. Se usa multipart por decisión de arquitectura, no por miedo a un bug. |
| **Modelo de cola** (procesar una vez y congelar) | Sustituido por reconciliación (§9). La cola no propagaba las ediciones: se editaba el copy en Notion y no pasaba nada. |
| ~~Eliminar el polling del todo~~ | **Revertido por la auditoría.** La entrega del webhook es best-effort y sin reintento (§4.4.1): el cron mantiene una pasada de recuperación (§9.4). |
| `type: 'update'` de Postiz | Delete+create tiene semántica inequívoca y es seguro (§4.8). No hace falta averiguar qué actualiza exactamente un `update`. |
| Añadir aprobación o campañas **a Postiz** | Es reconstruir Notion, peor y con código. Rompería además la regla de que Postiz sea sustituible (§2). |
| Hacer configurable el endpoint de S3 | `local` funciona y R2 queda como salida de emergencia. Hoy sería código sin usuario. |
| **Mover los medios a R2** | Se probó y se revirtió: el 403 que lo motivaba era el bloqueo de crawlers de IA de Cloudflare, no una limitación real. Meta obtiene 200 desde `local` (§10, Fase 0). |
| Derivar el margen de seguridad del horario del cron | Falso sentido de seguridad: el botón dispara a cualquier hora (§9.3). |

## 14. Fuentes

**Código de este repositorio** (autoridad para todo lo relativo a Postiz):
`upload.factory.ts` · `cloudflare.storage.ts` · `app.module.ts` · `throttler.provider.ts` · `instagram.provider.ts` · `instagram.dto.ts` · `create.post.dto.ts` · `get.posts.dto.ts` · `posts.service.ts` · `post.activity.ts` · `post.workflow.v1.0.5.ts` · `public.integrations.controller.ts` · `schema.prisma` · [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md)

**Notion (workspace real):** calendario `collection://186a2405-a123-81dc-832f-000b82a65c0c`

**Externas:**
- [Notion — Retrieving existing files](https://developers.notion.com/docs/retrieving-files) (caducidad de 1 h)
- [Notion — Working with files and media](https://developers.notion.com/docs/working-with-files-and-media) (5 GiB por fichero)
- [Meta — IG User Media reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/)
- [n8n — plantilla Notion + Postiz](https://n8n.io/workflows/12318-generate-and-schedule-themed-social-posts-with-notion-openai-falai-and-postiz/)
- [Postiz — usar Postiz con n8n](https://postiz.com/blog/use-postiz-with-n-8-n) (nodo comunitario `n8n-nodes-postiz`)

> **Nota sobre la documentación pública de Postiz:** describe un Postiz distinto al que corremos. Los límites de rate, el comportamiento de `upload-from-url` y la existencia de webhooks **no coinciden** con este fork. Ante una discrepancia, manda el código.
