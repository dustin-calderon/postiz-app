# Pipeline de contenido — Notion → n8n → Postiz → Instagram

> **Estado:** Fases 0, 2, 3a y **3b cerradas**. El sync escribe, retira y recupera; probado de punta a punta con un reel real de 150 MB, y el webhook de Postiz entrega en n8n con contenido (§14.7).
> **Sin publicar nada en Instagram todavía**, a propósito.
> **Inventario completo de lo implementado y lo no verificado: §14.**
> **Fecha:** agosto 2026 · última verificación 2026-08-04
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
- El único límite es sobre **creaciones de post**, contado **por organización**, no por IP. La clave exacta de `getTracker` (`throttler.provider.ts:18-24`) es `req.org.id + '_' + (url contiene '/posts' ? 'posts' : 'other')`, no el id de organización a secas.
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

**✅ Resuelto en la `v1.0.6`: todo camino terminal emite webhook.** Los cinco fallos previos al bucle también, porque el más probable de todos es `Refresh channel needed` — el token de Instagram caduca, el post falla y sin webhook nadie fuera de Postiz se entera hasta la pasada de recuperación del día siguiente.

El invariante "**todo camino terminal emite webhook**" es más fácil de sostener en el tiempo que "algunos sí y otros no", que es lo que obliga a releer el fichero entero en cada cambio.

Verificado ejecutando el workflow contra un post borrado (camino `:86`), sin tocar Instagram:

```
temporal workflow show --workflow-id zzaudit-webhookpath-1
  5  getPost
 11  changeState
 17  sendWebhooks     ← se ejecuta
Status  COMPLETED
```

### 4.4.1 ⚠️ El webhook se dispara hoy con el cuerpo vacío

`post.workflow.v1.0.5.ts:272-276` llama a `sendWebhooks(postsResults[0].postId, …)`. Ese `postId` es **el ID de la red social** (`mediaId` de Instagram), no el `Post.id` interno — véase `updatePost(postsList[i].id, postsResults[i].postId, …)` en `:196-200`, que los usa como cosas distintas.

Pero `getPostByForWebhookId` (`posts.repository.ts:869-875`) busca por `where: { id: postId }`, es decir **por el id interno**. Con el ID de Instagram no encuentra nada y `findMany` devuelve `[]`.

**Resultado: el webhook llega con `[]` como cuerpo.** Se dispara, pero no dice de qué post habla ni en qué estado quedó.

> Todo el cierre reactivo del §9.4 depende de que ese payload traiga el post. **Sin arreglarlo, el diseño no funciona.** Corregido en la `v1.0.6` (§10, Fase 3a).

**✅ Diagnóstico confirmado contra la base de producción**, sin publicar nada. Los dos espacios de identificadores son disjuntos:

```sql
Post.id     = cmrah83mf0001tb78bxpfhpob   -- cuid
releaseId   = 18442815235186433           -- id de media de Instagram
SELECT count(*) FROM "Post" p WHERE EXISTS (SELECT 1 FROM "Post" q WHERE q."releaseId" = p.id);
 count = 0
```

Cero solapamiento: la `v1.0.5` **nunca** pudo encontrar el post. Y la consulta de la `v1.0.6`, con el id interno, devuelve la fila con su `content` y su `state`.

### 4.4.3 El `state` no basta para saber si se publicó

`updatePost` (`posts.repository.ts:392-402`) marca `state='PUBLISHED'` **y** guarda `releaseURL`/`releaseId`. Si después falla el primer comentario —el sitio recomendado para los hashtags (§7.3)—, `changeState` pone `ERROR` **sobre el post padre** y `releaseURL` **se conserva**.

Es decir: `state=ERROR` cubre dos situaciones opuestas.

| Situación | `state` | `releaseURL` |
|---|---|---|
| No se publicó | `ERROR` | vacío |
| **Se publicó y falló el comentario** | `ERROR` | **con permalink** |
| Todo bien | `PUBLISHED` | con permalink |

> ### ⚠️ Aplicar "state=ERROR ⇒ no publicó" provoca publicar dos veces
> La fila iría a `Error`, alguien la devolvería a `Listo` (§8.1), y el sync la borraría y recrearía (§9.2) — con el post **ya vivo en Instagram**.
>
> **La regla correcta es `releaseURL`/`releaseId` no vacío ⇒ publicado**, mande lo que mande el `state`. Implementada en el receptor y en la pasada de recuperación.

Para que el consumidor pueda aplicarla, `getPostByForWebhookId` incluye ahora `releaseId` y `error` en su `select`. Sin `error`, `error_log` nunca podría llevar el motivo que pide §9.4.

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

**Once propiedades nuevas, ni una más.** (Diez en la tabla, más `release_url`, que dejó de reutilizar `URL` al cerrarse la decisión #3 de §11.)

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
- **`release_url`** es **propiedad propia** (tipo `url`). Se planteó reutilizar la `URL` que ya existía y se descartó: `URL` es tuya y tiene otro uso (decisión #3 de §11).

> **El aviso de error va al correo de quien creó la fila.** No hace falta propiedad: Notion expone `created_by` como metadato de página y n8n lo resuelve a email, con una dirección general de reserva (§10, Fase 3b).

Los tres campos de n8n (`postiz_post_id`, `postiz_media`, `error_log`) son **territorio exclusivo del worker**. Si alguien se ve editándolos a mano, algo se ha roto.

> ### ⚠️ No basta con la URL: `MediaDto` exige `id` **y** `path`
> `media.dto.ts:4-13` declara los dos campos como `@IsDefined()`:
>
> ```ts
> @IsString() @IsDefined()                          id: string;
> @IsString() @IsDefined()
> @Validate(ValidUrlPath) @Validate(ValidUrlExtension) path: string;
> ```
>
> **Son dos validadores, no uno.** `ValidUrlExtension` (`valid.url.path.ts:28-33`) exige además que el path acabe en una extensión de la lista blanca —`png·jpg·jpeg·gif·webp·avif·bmp·tif·tiff` + `mp4·mov·webm·mpeg·mpg`— tras quitar el query string. En la práctica no salta, porque la extensión la deriva `local.storage.ts` del magic-number del fichero; pero es una sexta forma de recibir un 400 y conviene tenerla escrita.
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

**Regla innegociable: nunca dos implementaciones.** Si el botón hace algo distinto que el cron, divergen en tres semanas y se depura a ciegas.

> ### Implementado: el botón **no** manda una fila
> El nodo del webhook desemboca en la **misma** consulta a Notion que el cron: ambos releen la cola entera y hacen la pasada completa. Las propiedades que Notion adjunta al pulsar el botón **se descartan a propósito**.
>
> Es más fiel a la regla de arriba que lo planeado: no hay un camino "de una fila" que pueda divergir del camino "de N filas", porque sólo hay uno. Cuesta una consulta a Notion de más por pulsación, que es gratis.
>
> El botón usa la acción **"Send webhook"** de Notion (sólo POST) y debe mandar la cabecera `X-Sync-Token`.

### 9.2 Qué hace el subflow con una fila

| Situación | Acción |
|---|---|
| `Plataforma` no contiene Instagram | Invisible para el worker |
| `publicación` vacío | No crear nada — **la retirada (§9.7) lo borra de Postiz si existía** |
| `publicación` = `Publicado` | **No tocar jamás** |
| Dentro del margen de seguridad (§9.3) | **Saltar** — se reporta en la ejecución, **no** se escribe en `error_log` (ver nota) |
| `postiz_post_id` vacío | Crear |
| Tiene `postiz_post_id`, aún no publicado | **Borrar y recrear** |
| `postiz_media` con valor | No re-subir los assets |
| `Fecha` sin hora | `Error` — nunca se adivina la hora (§10, Fase 2) |
| `Fecha` ya pasó y nunca se sincronizó | `Error` + motivo |

> ⚠️ La segunda fila **no es "ignorar y seguir"**. Si sólo se implementa esta tabla y no §9.7, vaciar `publicación` de una fila ya sincronizada deja el post programado en Postiz y **sale publicado igual**. Las dos partes son una sola.

> ### ⚠️ El orden de las puertas importa: primero la hora, después la ventana
> Parece intercambiable y no lo es. Notion devuelve una fecha sin hora como `2026-08-10` a secas, y `new Date('2026-08-10')` la interpreta como **medianoche UTC**. Si el margen de 2 h se evalúa antes que la comprobación de hora, esa fila puede caer dentro del margen y salir como «saltar» — es decir, **la fila sin hora nunca llega a `Error`**, que es justo lo contrario de la regla obligatoria de §10, Fase 2.
>
> El orden implementado es: **validaciones estructurales** (hora, offset, cuenta, content, assets, colaboradores) → y sólo con una fecha válida, **ventana → pasado → margen**.
>
> No es teórico: hoy **1 de cada 100 filas** con fecha tiene hora.

> **Sobre el margen y `error_log`:** saltar por el margen de seguridad no es un error, es el sistema funcionando. Escribirlo en `error_log` dejaría un mensaje de avería en una fila sana y acabaría entrenando al equipo a ignorar ese campo. Se reporta en la ejecución de n8n; la fila se recoge sola en la siguiente pasada.

Superadas las puertas, cada fila es **un solo post**, así que el subflow es lineal:

```
1. valida  ≤10 items · tamaño · reglas de §7.4
           colaboradores ⇒ ni carrusel ni story          (§7.2.4)
2. resuelve `cuenta` ──► integration.id                  (§7.2.1)
3. si tiene postiz_post_id y no está publicado ──► DELETE primero
4. si `postiz_media` está vacío:
      pide a Notion la URL FRESCA de cada fichero   ← nunca una guardada
      mide el tamaño con un GET de 1 byte (Range)  ← tope de 300 MB
      POST /public/v1/upload-from-url  { "url": ... }
        └─ los bytes NO pasan por n8n: los baja Postiz
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

   si el paso 5 falla:
      publicación = Error · error_log = motivo
      y si el media se subió EN ESTA pasada:
        DELETE /public/v1/media/:id  +  vaciar postiz_media
```

> ### Por qué el worker borra su propio media al fallar
> La limpieza automática sólo hace candidato lo que aparece en un post **publicado**. Un fichero subido y nunca publicado **no lo recoge nadie**, ni a los 30 días ni nunca. Sin este paso, cada fila abandonada tras un fallo dejaría un reel de 150 MB en el Seagate para siempre.
>
> **Sólo se borra lo subido en esa misma pasada.** Si el media venía reutilizado de un intento anterior (§8.1), borrarlo dejaría `postiz_media` apuntando a la nada. Y cuando se borra, se vacía también `postiz_media`, para que el reintento vuelva a subir.
>
> Requirió **añadir `DELETE /public/v1/media/:id` a la API pública del fork** — sólo existía en la API con sesión.

> **No hay fan-out.** Una pieza compartida entre cuentas es un post con colaboradores (§7.2.4), no N posts. Eso mantiene el 1:1 con Postiz —un ID, un estado, un `release_url`— y elimina cualquier necesidad de estados parciales o de una tabla intermedia.
>
> La excepción son los **carruseles y stories compartidos**, que Instagram no permite compartir: ahí son filas independientes, y cada una sigue siendo un post. El modelo no cambia.

Las dos escrituras siguen separadas: guardar `postiz_media` en cuanto sube hace el proceso **reanudable a mitad**, y evita volver a subir un reel en cada resincronización.

> ### ⚠️ Por qué `upload-from-url` y no multipart desde n8n
>
> El diseño original —n8n descarga de Notion y **sube** los bytes a Postiz por `POST /upload`— **no funciona**, y no por memoria: `postiz.dustincalderon.com` está detrás de un **Cloudflare Tunnel**, y el edge de Cloudflare corta los **cuerpos de petición** a 100 MB. Medido variando sólo el tamaño, con el mismo host, la misma cabecera y el mismo path:
>
> | Cuerpo | Resultado |
> |---|---|
> | 5 MB | `401` — llega al origen |
> | 90 MB | `401` — llega al origen |
> | **100 MB** | **`413`** · `server: cloudflare` |
> | **150 MB** | **`413`** tras aceptar 1,7 MB |
>
> Y no llega al Beelink: `grep -c 413` en los logs de Postiz da **0**. Lo corta el edge.
>
> **Nada que ver con R2** (§4.2), que es almacenamiento y sigue desactivado. Es el túnel, no el disco.
>
> Con `upload-from-url` el cuerpo que entra por el túnel son ~100 bytes de JSON y **es Postiz quien sale a internet** a por el fichero. La salida no tiene ese límite. Beneficios en cadena:
>
> - Desaparece el tope de 100 MB.
> - Los bytes **no pasan por n8n**: se acabó el riesgo de memoria del §12.
> - Un viaje en vez de dos (Notion → Postiz, en vez de Notion → n8n → Postiz).
>
> **Medido de punta a punta:** reel de 150 MB subido a Notion, y de Notion a Postiz en **9 s**, con `md5` idéntico en destino y `206` para `facebookexternalhit/1.1`.
>
> El tope de 300 MB sigue haciendo falta, pero por otro motivo: `upload-from-url` carga el fichero entero en memoria de Postiz (`Buffer.from(await response.arrayBuffer())`) y **no comprueba tamaño**. Notion admite hasta 5 GiB. Sin ese guardarraíl, un arrastre equivocado tumbaría el contenedor que además corre el orchestrator. Por eso el worker mide antes con un `Range: bytes=0-0`, que cuesta un byte.

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

n8n **no mira el `state`**: mira `releaseURL`/`releaseId`. Si vienen con valor, el post está en Instagram aunque el `state` diga `ERROR` (§4.4.3). Sólo si vienen vacíos y el `state` es `ERROR` la fila va a `Error`. Cualquier otra cosa se ignora sin escribir nada.

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
   └─ FILTRAR por creationMethod === 'API'         ← ver aviso rojo
   └─ para cada post aún no publicado en la ventana:
        ¿sigue habiendo una fila viva en Notion que lo reclame?
          (viva = publicación en Listo · Programado · En Postiz (borrador))
          no ──► DELETE /public/v1/posts/:id
```

> ### 🔴 Sin filtrar por `creationMethod`, la retirada borra el trabajo hecho a mano
> Un post creado desde la UI de Postiz **no tiene fila en Notion**, así que "todo lo que no tenga una fila viva detrás" lo incluye. La primera pasada del cron se lo habría llevado.
>
> No es hipotético: al auditar había un post real programado para el **14 de agosto** (`cmrah83mf…`, cuenta AMORISMO) creado a mano. `GET /posts` expone `creationMethod`, y los valores separan limpiamente los dos orígenes:
>
> | Origen | `creationMethod` |
> |---|---|
> | UI de Postiz | `WEB` |
> | Este pipeline (API pública) | `API` |
>
> **La retirada sólo toca `API`.** Comprobado: con el post de prueba reclamado, la pasada devuelve «nada que hacer» y el post `WEB` sigue intacto; al vaciar `publicación`, se lleva el de la API —y su comentario— y sigue sin tocar el `WEB`.

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

Sin hora, `publish_at` no existe y el worker no sabe cuándo publicar. Era **bloqueante para la Fase 3b**; resuelto arriba. Lo que sigue vigente es la regla del worker: una fila sin hora va a `Error`, nunca se adivina.

> En Notion: abrir la propiedad `Fecha` → *Formato de fecha* → activar **Incluir hora**. El DDL de la API no permite cambiar el formato de visualización.

**6. ✅ Hecho — las dos vistas.**

| Vista | Filtro | Para qué |
|---|---|---|
| **IG · Publicación** | `Plataforma` contiene Instagram, orden por `Fecha` | Donde trabaja el equipo |
| **⚠️ Averías** | `publicación = Error` | Panel de fallos: cuenta, motivo e id |

**7. ✅ Hecho — opciones de `colaboradores`.** Sembradas con los usernames reales de Instagram, sacados del campo `profile` de `GET /public/v1/integrations`: `thedustincalderon`, `citem.teatromusical`, `amorismoelmusical`.

> Nota menor: el `ALTER` que puso las opciones **borró la descripción** de esa propiedad. Reponerla a mano si molesta.

**8. ✅ Resuelto — la integración de Notion ya existe.** El token de `#ARCHIVE/Motion_to_Notion/.env` ya tiene acceso al calendario por herencia. Ver Fase 3b.
> **El botón no se crea aquí**, sino en la Fase 3b: necesitaba la URL del webhook de n8n. Ya existe — `https://auto.dustincalderon.com/webhook/postiz-sync-ig`, con la cabecera `X-Sync-Token` (§10, Fase 3b, punto 14).

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

> ### ✅ Verificado — sin publicar en Instagram
> - El **diagnóstico** de §4.4.1 se confirmó contra la base de producción: `Post.id` y `releaseId` son espacios disjuntos (0 coincidencias), así que la `v1.0.5` nunca pudo encontrar el post.
> - La **consulta corregida** devuelve la fila con `content` y `state`.
> - El **camino de fallo** se ejecutó de verdad (`getPost → changeState → sendWebhooks`, `COMPLETED`).
>
> Y el **destino** ya está dado de alta, con la entrega comprobada contra producción (§14.7).

**10. `externalId` — ⏸️ NO se hizo, a propósito.** Columna nullable en `Post` + índice único `[organizationId, externalId]` + comprobación en `createPost` que devuelva el post existente en vez de crear otro.

Da idempotencia al worker, pero **sin worker no tenía consumidor**: sería una migración sobre la base de producción para un llamante que aún no existía.

> **Ahora el worker existe, así que toca revisitarlo — y la respuesta sigue siendo "todavía no".** El candado de §9.6 (crear sólo si `postiz_post_id` está vacío) cubre el caso normal; la ventana de duplicado es el segundo exacto entre el `POST /posts` y el write-back a Notion. Con una pasada al día y una pulsación ocasional, es un riesgo diminuto frente a una migración sobre producción.
>
> **El disparador para hacerlo** es que aparezca un duplicado real, o que el sync pase a correr con frecuencia. Entonces `externalId` lo vuelve imposible por construcción y n8n deja de tener que acordarse de nada.

### Fase 3b — El sync en n8n · **CERRADA**

> **Resumen:** los cuatro workflows de §14.3 están montados, activos y probados de punta a punta con un reel real de 150 MB, sin publicar nada en Instagram. Lo que sigue es el registro de cómo se llegó ahí.
>
> **Tres cosas salieron distintas de lo planeado**, y las tres están explicadas donde corresponde:
> 1. Los bytes ya **no pasan por n8n** (§9.2) — el multipart chocaba con el túnel de Cloudflare.
> 2. La retirada **filtra por `creationMethod`** (§9.7) — si no, borra los posts hechos a mano.
> 3. El cierre del bucle mira **`releaseURL`, no `state`** (§4.4.3) — si no, republica.
>
> **El botón de Notion no manda una fila, dispara la pasada entera.** §9.1 lo describía al revés. Es mejor así: una sola implementación de verdad, en vez de dos caminos que divergen. El guardarraíl de las 2 h (§9.3) sigue haciendo falta exactamente por lo mismo — el botón se pulsa a cualquier hora.

#### Cómo se llegó (histórico)

**Credenciales creadas en n8n** (esto además retira el token de Notion del repo archivado):

| Credencial | Tipo | ID |
|---|---|---|
| `Postiz API (CITEM org)` | `httpHeaderAuth` → `Authorization` | `h6bGMcfTHiZUD0dy` |
| `Notion — Calendario Social Media` | `httpHeaderAuth` → `Authorization: Bearer` | `5rCv9a6s5FyI0swq` |

**Workflow `k3QqOu4nQJGJMXuO` — «(PLANIFICADOR)» · ⚰️ borrado, lo sustituye `eKxZPM4zjwhNb3vf`**

Cron 06:00 + webhook → lee el calendario → **decidía qué haría, sin escribir nada**.

> **Cubría menos de lo que decía.** Se afirmó que implementaba «todas las puertas de §9.2 y las validaciones de §7.4»; en realidad le faltaban **el tope de tamaño** —que es la que más falta hacía— y la regla del *trial reel*. Y evaluaba el margen de 2 h **antes** que la comprobación de hora, con lo que una fila sin hora salía como «saltar» en vez de `Error` (§9.2).
>
> Ambas cosas están corregidas en el workflow que lo sustituye.

**Ejecutado contra los datos reales (2026-08-03):**

```
filas de Instagram evaluadas: 99
  99  ignorar   (publicación vacía en todas)
acciones que se ejecutarían: 0
```

Correcto: **el pipeline está inerte hasta que alguien marque `Listo`.** Nada que arreglar en los datos existentes.

**🔒 Webhook protegido.** Se detectó que al activar el workflow, n8n exponía `POST /webhook/postiz-sync-ig` **sin autenticación**, y la respuesta del planificador incluye contenido de filas de Notion.

Corregido: el nodo Webhook exige la cabecera **`X-Sync-Token`** (credencial `4jg5NXem2BvjFtFO`). ✅ El valor vive en `/opt/homeserver/.env` como `N8N_SYNC_IG_TOKEN`, y **la copia de `/tmp/wf/token.txt` ya se borró** — era el secreto vivo con permisos `664` (§14.5).

Ese mismo token es el que tendrá que enviar el botón de Notion (§9.1).

**✅ La mitad que escribe ya existe** — §14.3. El planificador se borró porque el workflow nuevo hace lo mismo y además escribe.

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

> ### ✅ Saldada la deuda del token en un repo archivado
> Ya vive en los dos sitios durables: credencial cifrada de n8n `5rCv9a6s5FyI0swq` y `/opt/homeserver/.env`. **Se puede borrar `#ARCHIVE/Motion_to_Notion` sin perder nada.**
>
> La integración se llama `Motion_to_Notio` en el workspace `DC Brand`, y su límite de subida es de **5 GiB** por fichero — el mismo dato de §5, ahora confirmado contra `GET /v1/users/me`.

11. ✅ **Zona horaria fijada y probada** (§7.5): `10:00+02:00` enviado → `08:00` UTC almacenado, con un post real.
12. ✅ **Subflow de sync** (§9.2) con el margen de seguridad (§9.3) — `A0XMq6dLdAWvwMPv`.
13. ✅ **Cron 06:00 Europe/Madrid** sobre la ventana de 15 días (`eKxZPM4zjwhNb3vf`) **+ retirada y recuperación a las 06:20** (`rxVcGlxSZjzzI5ez`, §14.3). Confirmado que la zona del cron es Madrid de verdad: el contenedor de n8n corre con `TZ` y `GENERIC_TIMEZONE` = `Europe/Madrid`.
14. ⏸️ **A mano en la UI de Notion** (la API no permite crearlos, §9.1): propiedad Botón `Sincronizar ahora` → acción *Enviar webhook* → `https://auto.dustincalderon.com/webhook/postiz-sync-ig`, con la cabecera `X-Sync-Token`. Opcionalmente, automatización `publicación → Listo` → mismo webhook.
15. ✅ **Receptor del webhook de Postiz** — `VMezjZaMTIU5dIUz`, probado con los cuatro payloads, **dado de alta en Postiz y con la entrega verificada** (§14.7).
16. ✅ **Dry-run hecho — programando de verdad, no con `modo = borrador`.** Se creó un post con fecha dentro de ventana, se comprobó en Postiz y se retiró con la propia pasada de retirada. Cero publicaciones en Instagram.

> ### ⚠️ Los drafts se saltan la validación entera
> `public.integrations.controller.ts:219` → `if (body.type !== 'draft')`. Todo el bloque que lanza `PostValidationException` (`:220-231`) **no se ejecuta para drafts**. Sólo se comprueba `emptyContent`.
>
> Un post que fallaría en `programar` **se crea sin una queja en `borrador`**. Usar drafts como dry-run no valida nada de lo que se quiere validar: da una falsa sensación de que todo está bien.
>
> **El dry-run real es programar de verdad con fechas lejanas** y revisarlas en la UI de Postiz antes de que lleguen, o publicar en una cuenta de prueba. `modo = borrador` se queda como aparcadero editorial, no como red de seguridad.
17. Alerta por **email al creador de la fila** (`created_by` de Notion) cuando pase a `Error`, con dirección general de reserva. **⏸️ Pendiente, y a propósito:** hace falta decidir el remitente. Las credenciales SMTP que hay en n8n son de otras marcas (`Amazon SES — Los Repertoristas`, `— Radar TM`) y usar una de ellas para esto sería un préstamo que confunde. Mientras tanto, la vista **⚠️ Averías** (§10, Fase 2) lista todos los fallos con cuenta, motivo e id.

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
| ~~2~~ | ~~Tope de tamaño~~ | — | **Resuelta: 300 MB**, pero por un motivo distinto al inicial. No protege la memoria de n8n (ya no ve los bytes) sino la de **Postiz**, que sí carga el fichero entero (§12) |
| ~~3~~ | ~~¿`URL` libre?~~ | — | **No.** Creada propiedad `release_url` aparte |
| ~~4~~ | ~~Dirección de reserva~~ | — | **`contacto@dustincalderon.com`** |
| 5 | Qué pasa si el sync entero falla | — | Notion caído a las 06:00: reintentos + alerta distinta. **Sigue abierta** |
| ~~6~~ | ~~Huérfanos de `/upload` si falla el `POST /posts`~~ | — | **Resuelta: se añadió `DELETE /public/v1/media/:id` al fork** y el worker borra lo que acaba de subir si la creación falla (§9.2). Verificado: 30 medios vivos antes y después de un fallo real |
| 7 | ¿Meta acepta `collaborators` en `graph.instagram.com`? | — | **Deuda técnica.** No se probará de momento |

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

**~~Los bytes pasan por la memoria de n8n.~~ Ya no.** Era el riesgo operativo número uno y **ha desaparecido por cambio de arquitectura**, no por mitigación: con `upload-from-url` los bytes van de Notion a Postiz directamente y n8n sólo manda una URL (§9.2). Medido con un reel de 150 MB: **9 s**, `md5` idéntico, memoria de n8n irrelevante.

**El riesgo que queda es de memoria de _Postiz_**, no de n8n: `upload-from-url` carga el fichero entero en un `Buffer` y no comprueba tamaño. Por eso el worker mide antes con un `Range: bytes=0-0` y **rechaza por encima de 300 MB** con un error legible. Sin ese tope, un fichero de 5 GiB (lo que Notion permite) tumbaría el contenedor que además corre el orchestrator.

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
| ~~Evitar `upload-from-url`~~ | **Revertido.** Se usaba multipart "por decisión de arquitectura"; esa decisión era errónea. El multipart choca con el límite de 100 MB del Cloudflare Tunnel y ningún reel real pasa (§9.2). `upload-from-url` es ahora el camino: menos viajes, sin tope de túnel y sin bytes por n8n. |
| **Modelo de cola** (procesar una vez y congelar) | Sustituido por reconciliación (§9). La cola no propagaba las ediciones: se editaba el copy en Notion y no pasaba nada. |
| ~~Eliminar el polling del todo~~ | **Revertido por la auditoría.** La entrega del webhook es best-effort y sin reintento (§4.4.1): el cron mantiene una pasada de recuperación (§9.4). |
| `type: 'update'` de Postiz | Delete+create tiene semántica inequívoca y es seguro (§4.8). No hace falta averiguar qué actualiza exactamente un `update`. |
| Añadir aprobación o campañas **a Postiz** | Es reconstruir Notion, peor y con código. Rompería además la regla de que Postiz sea sustituible (§2). |
| Hacer configurable el endpoint de S3 | `local` funciona y R2 queda como salida de emergencia. Hoy sería código sin usuario. |
| **Mover los medios a R2** | Se probó y se revirtió: el 403 que lo motivaba era el bloqueo de crawlers de IA de Cloudflare, no una limitación real. Meta obtiene 200 desde `local` (§10, Fase 0). |
| Derivar el margen de seguridad del horario del cron | Falso sentido de seguridad: el botón dispara a cualquier hora (§9.3). |

## 14. Inventario de lo implementado

> Estado a 2026-08-04. **Tres cuartas partes de esto no viven en git** — conviene saber dónde mirar antes de auditar.

### 14.1 En el repositorio · `custom/postiz-dc`

| Qué | Dónde |
|---|---|
| `post.workflow.v1.0.6.ts` | `apps/orchestrator/src/workflows/post-workflows/` |
| Export de la versión | `apps/orchestrator/src/workflows/index.ts` |
| Arranque de `postWorkflowV106` | `posts.service.ts:729` |
| `releaseId` + `error` en el payload del webhook | `posts.repository.ts` → `getPostByForWebhookId` |
| Webhook en los 5 caminos previos al bucle | `post.workflow.v1.0.6.ts` |
| **`DELETE /public/v1/media/:id`** | `public.integrations.controller.ts` |
| Este documento | `docs/architecture/` |

**Desplegado:** imagen `postiz-custom:local` (tag `local-69921960`). Verificado tras recrear: contenedor `healthy`, tres procesos con **0 reinicios**, `backend-error.log` vacío, y el workflow del post del 14 de agosto **sigue `Running`** (Temporal conserva el estado; arrancó como `V105` y ahí sigue).

> Editar la `v1.0.6` en vez de crear una `v1.0.7` fue deliberado, y sólo es seguro porque se comprobó antes que **no había ninguna ejecución suya en vuelo** (la única existente estaba `Terminated`). La regla de "un fichero por versión" existe para no romper replays; sin replays que romper, una versión nueva sólo habría añadido ruido.

### 14.2 En Notion · `collection://186a2405-a123-81dc-832f-000b82a65c0c`

**11 propiedades nuevas** (§7.2), verificadas contra la API: `cuenta`, `colaboradores`, `content`, `assets`, `first_comment`, `modo`, `publicación`, `postiz_post_id`, `postiz_media`, `error_log`, `release_url`. Tipos y opciones correctos.

> **Todas con descripción menos una:** `colaboradores` la tiene **vacía**, porque el `ALTER` que sembró sus opciones la borró (§10, Fase 2). Reponerla a mano si molesta.

**2 vistas:** `IG · Publicación` (filtrada por Instagram) y `⚠️ Averías` (filtrada por `publicación = Error`). *No verificables por la API pública de Notion, que no expone las vistas de una data source: se dan por buenas según quien las creó.*

**1 cambio del usuario:** `Fecha` pasó de *Formato de hora: Oculto* a **24 horas** — confirmado (`time_format: "H:mm"`).

### 14.3 En n8n · `auto.dustincalderon.com`

| Objeto | ID | Estado |
|---|---|---|
| **Sync Instagram desde Notion** (cron 06:00 + botón) | `eKxZPM4zjwhNb3vf` | **Activo** |
| **Sync IG — SUBFLOW (una fila)** | `A0XMq6dLdAWvwMPv` | **Activo** |
| **Retirada y recuperación (IG)** (cron 06:20) | `rxVcGlxSZjzzI5ez` | **Activo** |
| **Receptor de estado (webhook) → Notion** | `VMezjZaMTIU5dIUz` | **Activo** |
| Credencial Postiz | `h6bGMcfTHiZUD0dy` | — |
| Credencial Notion | `5rCv9a6s5FyI0swq` | — |
| Credencial webhook | `4jg5NXem2BvjFtFO` | `X-Sync-Token` |

El planificador `k3QqOu4nQJGJMXuO` **se borró**: lo sustituye `eKxZPM4zjwhNb3vf`, que además escribe.

**Puntos de entrada:**

| Ruta | Auth | Para qué |
|---|---|---|
| `POST /webhook/postiz-sync-ig` | `X-Sync-Token` | Botón de Notion y sync a demanda |
| `POST /webhook/postiz-retirada-ig` | `X-Sync-Token` | Retirada/recuperación a demanda |
| `POST /webhook/postiz-status-<secreto>` | **el secreto va en la ruta** | Destino del webhook de Postiz |

> ### Por qué el receptor lleva el secreto en la URL y no en una cabecera
> `post.activity.ts:329-335` manda el webhook con **una sola cabecera**, `Content-Type`. No hay firma, ni HMAC, ni campo de secreto en el modelo `Webhooks` (id, name, url, organizationId). Con un emisor que no puede autenticarse, meter el secreto en la ruta es la única opción; sobre HTTPS la ruta no viaja en claro. El valor está en `/opt/homeserver/.env` como `N8N_POSTIZ_WEBHOOK_PATH`.

**Copia durable:** los cuatro workflows están exportados en `/opt/homeserver/n8n-workflows/postiz-<id>.json` (modo `600`). **No van a este repositorio**: el receptor lleva su ruta secreta dentro, y esto es un fork de un proyecto público (§14.4).

**Por qué la retirada es un workflow aparte y va 20 minutos después.** Es la parte destructiva. Encadenarla al sync obliga a razonar sobre qué pasa cuando no hay filas que crear (los nodos sin items no se ejecutan, y la retirada no correría nunca justo el día que más falta hace). Separada, siempre corre, y el desfase garantiza que el sync ya ha escrito los `postiz_post_id` que ella va a leer.

### 14.4 En producción, fuera de todo lo anterior

| Fichero | Cambio |
|---|---|
| `/opt/homeserver/postiz.env` | `API_LIMIT` 30 → **300**; `CLOUDFLARE_BUCKET_URL` sin barra final. Copia: `postiz.env.bak-20260803` |
| `/opt/homeserver/.env` | **`N8N_SYNC_IG_TOKEN`** añadido — el token del webhook (§9.1) |
| `/opt/homeserver/.env` | **`NOTION_API_KEY`** añadido — copia durable del token de Notion |
| `/opt/homeserver/.env` | **`N8N_POSTIZ_WEBHOOK_PATH`** añadido — ruta secreta del receptor (§14.3) |

Los tres verificados presentes. `API_LIMIT=300`, `STORAGE_PROVIDER=local`, `TZ` vacío y `CLOUDFLARE_BUCKET_URL` sin barra final, también.

> ### 🔑 Dónde vive cada secreto, y por qué no en este repo
> El token de Notion estaba **sólo** en `#ARCHIVE/Motion_to_Notion/.env`, un repo muerto. Ahora vive en dos sitios durables:
>
> 1. **Credencial de n8n** `5rCv9a6s5FyI0swq` — cifrada, es la que usa el worker.
> 2. **`/opt/homeserver/.env`** — junto al resto de secretos del servidor, que es la convención del HomeLab.
>
> **Ya se puede borrar `#ARCHIVE/Motion_to_Notion` sin perder nada.**
>
> **Nunca en este repositorio.** Es un fork de un proyecto público: basta un push al remoto equivocado para filtrar el token. Los secretos van al `.env` del servidor o al gestor de credenciales de la herramienta que los usa — jamás a git, ni siquiera en un repo privado.

### 14.5 Residuos de las pruebas — qué se dejó y qué se limpió

Durante la verificación se crearon objetos en producción. Registro honesto de todos:

| Artefacto | Estado |
|---|---|
| Fila de Notion «__TEST hora (borrar)» | ✅ Archivada |
| Post de Postiz `cmsduippv0000ns71oty7cibs` + su comentario | ✅ Soft-deleted vía API |
| Media `6ef7cac0-b740-498c-8999-878c8c9325cc` | ✅ Soft-deleted **a mano** — ver aviso |
| `/tmp/test-pipeline.jpg` y los JSON de `/tmp/wf/` | ✅ Borrados |
| `/tmp/wf/planner.js` y `token.txt` | ✅ **Borrados** — ver aviso |
| Ejecución `203001` de n8n | ⏸️ Queda en el historial |
| Fila de Notion «__ZZ AUDIT pipeline (borrar)» | ✅ Archivada |
| Posts de prueba en Postiz (2027 y 18-ago) + comentarios | ✅ Soft-deleted (por la propia retirada) |
| Workflows de Temporal `zzaudit-webhookpath-1`, `zzaudit-entrega-1/2` | ⏸️ Completados, quedan en el historial |
| Borrador de prueba de la entrega (`cmsegdkbi…`) | ✅ Borrado vía API |
| 4 media de prueba (~470 MB) | ✅ Soft-deleted — el blob lo borra la limpieza a los 7 días |

> ### 🔑 El token del webhook estaba en `/tmp` y era legible por cualquiera
> `/tmp/wf/token.txt` no era "una referencia": su contenido **coincidía exactamente** con el `N8N_SYNC_IG_TOKEN` vivo, con permisos `664` (lectura para todo el mundo) en un directorio que cualquier usuario del host puede listar.
>
> Borrado. El valor sigue donde debe: en `/opt/homeserver/.env` y en la credencial cifrada de n8n.

> ### ⚠️ Un fichero subido y no publicado no lo recoge nadie
> El Step 2 de la limpieza (§4.7) sólo hace candidatos a los medias que aparecen en un post `PUBLISHED`: **si nunca se publicó, la fase 1 no lo ve jamás**.
>
> La salida es soft-borrarlo a mano. **Verificado que eso basta:** la fase 2 (`findOrphanedSoftDeletedMedia`) selecciona cualquier media con `deletedAt` de más de 7 días, sin mirar si se publicó. Es decir, el agujero está en *quién marca el `deletedAt`*, no en la limpieza.
>
> **Sigue siendo un agujero del pipeline, y ahora con un emisor real:** cada vez que el sync suba un asset y el `POST /posts` falle después, ese fichero queda huérfano y permanente. Lo mitiga que el reintento **reutiliza `postiz_media`** en vez de resubir (§8.1), así que no se acumulan por reintento — sólo queda basura si la fila se abandona. **Decisión #6 de §11, aún abierta.**

### 14.6 Qué se verificó ejecutándolo, y qué no

**Verificado ejecutando, no leyendo:**

| Qué | Evidencia |
|---|---|
| Sync completo de una fila real | Notion `Listo` → `Programado`, con `postiz_post_id` y `postiz_media` escritos, y post + comentario en Postiz |
| **Reel de 150 MB de Notion a Postiz** | 9 s, `md5` idéntico, `206` para `facebookexternalhit/1.1` |
| Zona horaria | `10:00+02:00` enviado → `08:00` UTC almacenado |
| Primer comentario (hashtags) | Crea un `Post` hijo con la misma `publishDate` |
| Recrear reutilizando media | 2ª pasada en 1,7 s (vs 13,5 s), sin volver a subir, post anterior borrado |
| Retirada — seguridad | Con todo reclamado: «nada que hacer»; el post `WEB` intacto |
| Retirada — función | Al vaciar `publicación`: borra el post de la API **y su comentario**, y sigue sin tocar el `WEB` |
| Receptor de webhook | 4 payloads: publicado · error · **error con `releaseURL`** · `[]` vacío |
| Camino de fallo previo al bucle | `getPost → changeState → sendWebhooks`, workflow `COMPLETED` |
| **Entrega real Postiz → n8n** | Webhook recibido **con contenido**, incluidos `error` y `releaseId` (§14.7) |
| Post sin fila en Notion | El receptor lo ignora y **no** intenta escribir (§14.7, aviso del spread) |
| **Fallo tras subir el asset** | Copy de 2593 caracteres → `400`. La fila queda en `Error` con el motivo real, `postiz_media` vacío, y **el media borrado**: 30 vivos antes y después |
| Límite de Cloudflare | 90 MB pasa · 100 MB y 150 MB dan `413` del edge |
| Diagnóstico de §4.4.1 | `Post.id` y `releaseId` disjuntos en producción (0 coincidencias) |

**Lo que sigue sin verificarse funcionando:**

1. **Una publicación real en Instagram.** A propósito: no se ha publicado nada en las cuentas de producción. Todo se probó por el camino de fallo o con fechas dentro de ventana que se retiraron después.
3. **Colaboradores en `graph.instagram.com`** — deuda técnica por decisión, no se probará.
4. **Más de 100 filas accionables.** Ninguna de las dos consultas a Notion pagina: **fallan a las claras** con un error si `has_more` es `true`, en vez de sincronizar media cola en silencio. Con el filtro por `publicación` (sólo estados vivos) hoy hay **0**, así que el margen es enorme.

Y una decisión abierta: qué hacer si el sync entero falla (Notion caído a las 06:00).

### 14.7 El webhook, dado de alta · ✅ y el bucle cerrado de verdad

**Dado de alta a mano en la UI**, que es la única vía: `POST /webhooks` vive en la API con sesión (`webhooks.controller.ts`), no en la pública, y con la API key devuelve `401`.

| Campo | Valor |
|---|---|
| Nombre | `n8n sync Instagram` |
| URL | `https://auto.dustincalderon.com/webhook/` + `N8N_POSTIZ_WEBHOOK_PATH` |
| Integraciones | **las 3 de Instagram** (no «todas») |

**✅ Entrega verificada de punta a punta en producción**, sin publicar nada: se creó un **borrador** (que nunca arranca workflow ni publica) y se lanzó su workflow a mano, cayendo por el camino `Already posted`. El cuerpo llegó **completo**:

```json
[{ "id": "cmsegdkbi…", "content": "…", "releaseURL": null, "releaseId": null,
   "error": "Already posted", "state": "ERROR",
   "integration": { "id": "cmqjq77hg…", "providerIdentifier": "instagram-standalone" } }]
```

Es exactamente lo que §4.4.1 decía que **no** llegaba, más los dos campos que se añadieron al fork (`releaseId`, `error`). El defecto original está cerrado.

> ### ⚠️ El orden del spread — un fallo que sólo aparecía con posts ajenos al pipeline
> Esa primera entrega **falló en n8n**, y el motivo merece quedar escrito porque es de los que no se ven leyendo:
>
> ```js
> // MAL: ...ctx va al final y sobreescribe accion con el 'escribir' que trae ctx
> return [{ json: { accion: 'ignorar', motivo: '…', ...ctx } }];
> ```
>
> Cuando ninguna fila de Notion reclama el post, el nodo devolvía `accion: 'escribir'` igualmente y la siguiente llamada iba a `PATCH /v1/pages/undefined` → `Invalid request URL`.
>
> **Sólo se manifiesta con posts que no vienen del pipeline** — es decir, con cada publicación hecha a mano desde la UI de Postiz, que son las que hoy existen. Las pruebas anteriores del receptor no lo destaparon porque todas usaban una fila que sí existía.
>
> Corregido con `Object.assign({}, ctx, { accion: … })` y reprobado con el mismo escenario: ahora termina en `success` y sale por «Sin fila que actualizar». De paso, `release_url` se limpia cuando el estado es `Error`, para que no quede un permalink viejo contradiciendo al estado.

> ### ⚠️ Consecuencia de elegir «integraciones específicas»
> El filtro de `sendWebhooks` (`post.activity.ts:316-323`) es `f.integrations.length === 0 || f.integrations.some(...)`. Con integraciones concretas, **sólo entrega cuando el `integrationId` coincide**.
>
> Dos de los cinco caminos previos al bucle (`:86` y `:108`, «No Post») no conocen la integración y pasan `''`, así que **no entregan**. No se pierde nada: en esos casos el post no existe y el cuerpo sería `[]` de todos modos.
>
> **Lo que sí es una trampa a futuro:** el día que se conecte una cuarta cuenta de Instagram, habrá que añadirla aquí a mano o sus avisos no llegarán, en silencio. Con «todas las integraciones» eso no pasa. Merece la pena cambiarlo si algún día se añade una cuenta.

> ### 🔑 No rotar la API key sin avisar a n8n
> El botón *Rotate Key* de *Settings → Developers* invalida la clave que usa la credencial `h6bGMcfTHiZUD0dy`. Rompería **los cuatro workflows a la vez** y de forma silenciosa: no se notaría hasta la pasada de las 06:00. Si se rota, hay que actualizar la credencial de n8n el mismo día.
>
> El resto de esa pantalla —CLI, skill del agente, MCP de Postiz, nodo comunitario de n8n— **no se usa a propósito**: todo eso publica *directamente en Postiz*, saltándose Notion, que es justo lo que prohíbe §6. La Fase 4 usa el **MCP de Notion**, no el de Postiz.

**Los medios de prueba ya están soft-deleted** (~470 MB: dos reels de 150 MB y dos imágenes). No hay endpoint público para borrar media, así que se marcaron igual que hace el botón de la UI (`deletedAt = now()`, `media.repository.ts:52-62`), tras comprobar que ningún post vivo los referenciaba.

El blob físico lo borra la **fase 2** de la limpieza, que recoge **cualquier** media con `deletedAt` de más de 7 días —publicado o no (`findOrphanedSoftDeletedMedia`, `media.repository.ts:394-413`)—. Verificado que el limpiador está vivo: `RUN_CRON=true` y el workflow `media-cleanup-workflow` lleva **29 ciclos completados**.

## 15. Fuentes

**Código de este repositorio** (autoridad para todo lo relativo a Postiz):
`upload.factory.ts` · `cloudflare.storage.ts` · `local.storage.ts` · `app.module.ts` · `throttler.provider.ts` · `instagram.provider.ts` · **`instagram.standalone.provider.ts`** · `instagram.dto.ts` · `create.post.dto.ts` · `media.dto.ts` · **`valid.url.path.ts`** · `has.extension.ts` · `custom.upload.validation.ts` · `get.posts.dto.ts` · `posts.service.ts` · `posts.repository.ts` · `media.repository.ts` · `webhooks.repository.ts` · `webhooks.controller.ts` · `post.activity.ts` · `post.workflow.v1.0.5.ts` · **`post.workflow.v1.0.6.ts`** · `public.integrations.controller.ts` · `schema.prisma` · [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md) · [VIDEO_FORMAT_SUPPORT.md](./VIDEO_FORMAT_SUPPORT.md)

**Fuera del repositorio** (§14.3): los cuatro workflows de n8n, exportados en `/opt/homeserver/n8n-workflows/`.

**Notion (workspace real):** calendario `collection://186a2405-a123-81dc-832f-000b82a65c0c`

**Externas:**
- [Notion — Retrieving existing files](https://developers.notion.com/docs/retrieving-files) (caducidad de 1 h)
- [Notion — Working with files and media](https://developers.notion.com/docs/working-with-files-and-media) (5 GiB por fichero)
- [Meta — IG User Media reference](https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media/)
- [n8n — plantilla Notion + Postiz](https://n8n.io/workflows/12318-generate-and-schedule-themed-social-posts-with-notion-openai-falai-and-postiz/)
- [Postiz — usar Postiz con n8n](https://postiz.com/blog/use-postiz-with-n-8-n) (nodo comunitario `n8n-nodes-postiz`)

> **Nota sobre la documentación pública de Postiz:** describe un Postiz distinto al que corremos. Los límites de rate, el comportamiento de `upload-from-url` y la existencia de webhooks **no coinciden** con este fork. Ante una discrepancia, manda el código.
