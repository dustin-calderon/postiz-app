# Pipeline de contenido — lo que el fork de Postiz impone

> **Qué es esto:** las restricciones reales de `custom/postiz-dc` que condicionan el pipeline Notion → n8n → Postiz → Instagram, y lo que el fork añade para él.
> Todo está comprobado contra el código de este fork, no contra la documentación pública, que describe otro Postiz. **Si este documento y el código no coinciden, manda el código.**
>
> **Parte de:** [CONTENT_PIPELINE_NOTION_POSTIZ.md](./CONTENT_PIPELINE_NOTION_POSTIZ.md), que tiene el mapa de todos los documentos del pipeline.

---

## 1. La URL pública es obligatoria de verdad

`post()` de `instagram.provider.ts` construye la llamada a Meta pasando la ruta tal cual:

```ts
? `video_url=${m.path}&media_type=REELS&thumb_offset=${...}`
: `image_url=${m.path}`
```

Meta hace **fetch** de esa URL desde sus servidores. Si no es alcanzable desde internet, falla siempre — aunque subir a mano desde la UI funcione.

Con `STORAGE_PROVIDER=local` esa URL es `FRONTEND_URL + /uploads + /YYYY/MM/DD/<32 hex>.<ext>` (`local.storage.ts`: `uploadSimple`, `uploadFile` y `uploadStream`), y Meta la alcanza: `facebookexternalhit/1.1` recibe **200**.

> ### ⚠️ Este dominio devuelve 403 a los agentes de IA
> El `robots.txt` sirve la política de Content Signals de Cloudflare, que **bloquea crawlers de IA**. Desde una misma IP y un mismo path: UA vacío → 200, `python-requests` → 200, `facebookexternalhit/1.1` → 200, `ClaudeBot/1.0` → **403**.
>
> No afecta a la publicación, pero sí a cómo se comprueba: **el alcance de una URL de este dominio no se puede verificar con un agente de IA** — siempre dará 403 y parecerá una avería de infraestructura que no existe. Se comprueba con `curl` desde el Beelink variando el UA, o desde un móvil con datos.

## 2. Storage: sólo `local` o `cloudflare`

`upload.factory.ts` no admite nada más, y `cloudflare.storage.ts` **hardcodea** el endpoint `https://${accountID}.r2.cloudflarestorage.com`. No hay hueco para MinIO ni para otro S3 compatible: no es que falte soporte, es que no hay dónde ponerlo.

**Decisión: `local`.** Meta alcanza las URLs del dominio (§1) y los medios viven en el Seagate vía bind mount (`/uploads` → `/mnt/seagate/postiz-media`); no hace falta almacenamiento externo.

> Hay un bucket de R2 configurado y con credenciales válidas en `postiz.env`, **inactivo**. Es la salida si algún día el uplink de casa se convierte en el cuello de botella al servir reels a Meta: cambiar `STORAGE_PROVIDER` sería suficiente.

## 3. El rate limit no es el que dice la documentación pública

`apps/backend/src/app.module.ts` (`ThrottlerModule.forRoot`) → `API_LIMIT` o **90 por hora**, TTL 3600 s.
`canActivate` de `throttler.provider.ts` → sólo se aplica a `POST /public/v1/posts`:

```ts
if (method === 'POST' && url.includes('/public/v1/posts')) return super.canActivate(context);
return true;
```

Consecuencias:

- **Los uploads no están limitados.** No existe ninguna cuota de "30 uploads/hora".
- El único límite es sobre **creaciones de post**, contado **por organización**, no por IP. La clave exacta de `getTracker` (`throttler.provider.ts`) es `req.org.id + '_' + (url contiene '/posts' ? 'posts' : 'other')`, no el id de organización a secas.
- En producción, `API_LIMIT` = **300** ([INVENTARIO §2](../reference/CONTENT_PIPELINE_INVENTARIO.md)). Es nuestra instancia, con una sola organización en uso y una API key que es nuestra; el throttle existe para proteger un SaaS multi-inquilino, no este caso. Cuánto consume el pipeline de ese techo: [NOTION_POSTIZ §6](./CONTENT_PIPELINE_NOTION_POSTIZ.md).

> **Cuándo hará falta comparar antes de recrear.** Cada pasada crea una vez cada fila de la ventana, así que lo que gasta y lo que tarda crecen con las filas; la batería lanza muchas seguidas. La alternativa estructural —un `GET` (no throttleado) y sólo borrar+crear si algo cambió— ahorraría casi todas esas llamadas. Las dos señales de que hace falta: una fila en `Error` con «Postiz respondió 429», o pasadas del sync que se acercan a los 125 s, donde Cloudflare corta la respuesta del webhook con cabecera. `scripts/errores-pipeline.py` saca la primera; la duración de cada pasada está en las ejecuciones de n8n.

El batching del worker existe por el límite de **Instagram** (100 publicaciones / 24 h) y por no saturar el orchestrator, **no** por cuota de Postiz.

## 4. Postiz tiene webhooks, y todo camino terminal emite uno

`sendWebhooks` (`post.activity.ts`) se dispara desde el workflow del orchestrator (`post.workflow.v1.0.6.ts`) con el post completo en el body, filtrable por integración.

**Invariante de la `v1.0.6`: todo camino terminal emite webhook, en éxito y en fallo.** Eso incluye los fallos previos al bucle de publicación —el más probable es `Refresh channel needed`: el token de Instagram caduca, el post falla y sin webhook nadie fuera de Postiz se entera hasta la pasada de recuperación— y cada salida del bucle, que pasa por `notifyFailure` después de `changeState('ERROR')`.

> **Al tocar el workflow, sostener el invariante.** Añadir un `return` sin `changeState('ERROR')` y sin webhook hace que un fallo salga en silencio. Un caso que no es obvio: si todos los intentos fallan con `refresh_token` y el refresh funciona, el bucle hace `continue` sin tocar el estado; por eso la salida de «reintentos agotados» pone `ERROR` explícitamente antes de avisar.

### 4.1 El webhook lleva el `Post.id` interno, nunca el de Instagram

`getPostByForWebhookId` (`posts.repository.ts`) busca por `where: { id: postId }`, es decir **por el id interno**. Por eso `sendWebhooks` recibe `postsList[0].id`, no `postsResults[0].postId`, que es **el ID de la red social** (`mediaId` de Instagram).

Los dos espacios de identificadores son disjuntos (`cuid` frente a un número de Instagram, sin ningún solapamiento en producción): con el id equivocado el cuerpo llega como `[]` —se dispara, pero no dice de qué post habla—. Todo el cierre reactivo ([RECONCILIACION §1](./CONTENT_PIPELINE_RECONCILIACION.md)) depende de que ese payload traiga el post.

### 4.2 La entrega del webhook no está garantizada

`sendWebhooks` (`post.activity.ts`) envuelve el `fetch` en `try { … } catch (e) { /**empty**/ }`. Si n8n está caído o hay timeout, **el fallo se traga sin log y sin reintento**, y el `Promise.all` no propaga nada al workflow.

Un `Publicado` perdido no se recupera solo. **Por eso no se puede eliminar el polling del todo** ([RECONCILIACION §1](./CONTENT_PIPELINE_RECONCILIACION.md)).

### 4.3 El `state` no basta para saber si se publicó

`updatePost` (`posts.repository.ts`) marca `state='PUBLISHED'` **y** guarda `releaseURL`/`releaseId`. Si después falla el primer comentario ([NOTION_SCHEMA §3](./CONTENT_PIPELINE_NOTION_SCHEMA.md)), `changeState` pone `ERROR` **sobre el post padre** y `releaseURL` **se conserva**.

Es decir: `state=ERROR` cubre dos situaciones opuestas.

| Situación | `state` | `releaseURL` |
|---|---|---|
| No se publicó | `ERROR` | vacío |
| **Se publicó y falló el comentario** | `ERROR` | **con permalink** |
| Todo bien | `PUBLISHED` | con permalink |

> ### ⚠️ Aplicar "state=ERROR ⇒ no publicó" provoca publicar dos veces
> La fila iría a `Error`, alguien la devolvería a `Listo`, y el sync la borraría y recrearía — con el post **ya vivo en Instagram**.
>
> **La regla correcta es `releaseURL`/`releaseId` no vacío ⇒ publicado**, mande lo que mande el `state`. Está implementada en el receptor y en la pasada de recuperación.

Para que el consumidor pueda aplicarla, `getPostByForWebhookId` incluye `releaseId` y `error` en su `select`. Sin `error`, `❌ error_log` no podría llevar el motivo del fallo.

## 5. Postiz valida el post antes de crearlo

`checkValidity` de `instagram.provider.ts` rechaza >10 medias y exige al menos una. El API público ejecuta `validatePosts` antes de crear nada y devuelve un 400 legible. La validación en n8n sigue siendo buena idea (fallar antes es mejor), pero no es la última línea de defensa.

**`checkValidity` también mide los ficheros** (`instagram.media.rules.ts`) contra la referencia de Meta (IG User Media, especificaciones de imagen, reels y stories): un video de más de 1920 px de ancho o 25 Mbps; un reel de más de 300 MiB o 15 min, una story de más de 100 MiB o 60 s, y cualquiera de los dos de menos de 3 s; y una foto del feed (post o carrusel) fuera de la proporción 4:5–1,91:1, que Meta rechaza al publicar con el error 2207009. Un video dentro de un carrusel solo se mide en ancho y bitrate: la referencia no le da tamaño ni duración propios. Solo mira lo que exige decidir a una persona —acortar un video, recortar una foto—: lo que se arregla convirtiendo lo hace antes `normalizar-media.sh` ([SYNC §2](./CONTENT_PIPELINE_SYNC.md)). El mensaje lleva los valores medidos y llega a `❌ error_log` como «Postiz rechazó la pieza» ([NOTION_SCHEMA §7.1](./CONTENT_PIPELINE_NOTION_SCHEMA.md)), así que el problema se descubre al sincronizar y no a la hora de publicar. Es **fail-open**: solo bloquea con evidencia —lo que no se puede medir pasa, y una foto girada por su orientación EXIF o un video girado 90° no se juzgan por sus medidas, porque Meta no dice cuáles mira—, y solo aplica con storage `local`.

> ### ⚠️ …salvo con `modo = borrador`, donde casi no valida nada
> El resultado de `checkValidity` viaja en `item.errors`, y ese campo **sólo se comprueba dentro de `if (body.type !== 'draft')`** (`createPost` de `public.integrations.controller.ts`). Ahí dentro van también los ajustes y el límite de 2200 caracteres. Fuera de ese bloque queda una sola comprobación: `emptyContent`, que exige que el texto **y** las imágenes estén vacíos **a la vez** (`validatePosts` de `posts.service.ts`).
>
> Es decir: un borrador sin ninguna imagen pero con copy pasa sin queja, aunque `checkValidity` lo habría rechazado con *«Should have at least one media»*.
>
> **Con `modo = borrador`, n8n es la única defensa**, incluso para las reglas que [NOTION_SCHEMA §4](./CONTENT_PIPELINE_NOTION_SCHEMA.md) marca como «✅ Sí». Por eso el borrador es un dry-run editorial, no técnico ([NOTION_SCHEMA §2.2](./CONTENT_PIPELINE_NOTION_SCHEMA.md)).

## 6. `createPost` devuelve un ID por integración

`createPost` de `posts.service.ts` → `[{ postId, integration, alreadyClaimed }]`. De ahí la regla **una fila = un post**.

## 7. La limpieza de medios: retención de 3650 días

La limpieza automática la describe [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md). Lo que importa aquí:

- `MEDIA_RETENTION_DAYS` — default del código **30**; en producción **3650**.
- El filtro es **positivo**: sólo son candidatos los medias cuyo `path` aparece en un `Post` con `state='PUBLISHED'` y `publishDate` anterior a la retención.
- Hard-delete **7 días** después del soft-delete.

**Un asset subido hoy y programado para dentro de tres semanas no corre ningún riesgo**: no ha sido publicado, luego no es candidato. Eso no depende del número de días.

**Por qué 3650 y no 30.** Treinta días sólo son seguros si el máster vive en otro sitio. **Para el material que pasa por el pipeline** así es: la copia de Postiz es derivada y reconstruible desde Notion. Para lo publicado desde la UI de Postiz, no: no tiene fila en Notion, y la caché del Seagate es su única copia en el servidor. Las cifras de lo que se perdió y el procedimiento para cambiar la retención —hay que terminar y relanzar el workflow en Temporal, no basta con reiniciar el contenedor— están en [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md).

La retención larga compra tiempo; la segunda copia real es el archivo en Drive ([ARCHIVO_DRIVE.md](./ARCHIVO_DRIVE.md)), que cubre todo lo publicado, venga de Notion o no. Volver a bajar la retención exige que cada fichero tenga esa segunda copia.

## 8. Borrar un post termina su workflow

`posts.service.ts`: `deletePost` busca las ejecuciones de Temporal asociadas y las termina.

```ts
query: `postId="${post.id}" AND ExecutionStatus="Running"`
...
await workflow.terminate();
```

**Esta es la garantía que hace viable el modelo de reconciliación** ([RECONCILIACION §2](./CONTENT_PIPELINE_RECONCILIACION.md)). Sin ella, borrar y recrear dejaría workflows zombis publicando posts borrados.

## 9. ⚠️ Las 3 cuentas usan `instagram-standalone`, no `instagram`

Las tres integraciones de Instagram tienen `providerIdentifier = 'instagram-standalone'` en la base de producción. Sus IDs, y qué opción de Notion corresponde a cada una: [NOTION_SCHEMA §2.1](./CONTENT_PIPELINE_NOTION_SCHEMA.md). Hay además una integración de TikTok, `cmqjs6xnx0001q07q9aohapuv`, fuera del pipeline.

> **Postiz cachea el nombre de la integración al conectarla** y no lo refresca solo. Si una cuenta cambia de nombre en Instagram, el nombre viejo sigue en la base de Postiz, y con él en cualquier informe o `post.txt` generado desde esa tabla ([ARCHIVO_DRIVE.md](./ARCHIVO_DRIVE.md)). No es un bug de datos ni se edita la base a mano: **se corrige reconectando la integración desde la UI de Postiz.**

`instagram.standalone.provider.ts` delega `post()` al provider normal pero con **`graph.instagram.com`** en vez de `graph.facebook.com`. Consecuencias que cambian el diseño:

**1. `checkValidity` está sobreescrito y valida mucho menos** (`instagram.standalone.provider.ts`):

```ts
override async checkValidity(...) {
  if (!firstPost?.length) return 'Should have at least one media';
  if (settings?.is_trial_reel) { … }
  return true;
}
```

**No comprueba el máximo de 10 medias ni la regla del audio.** Todo lo que el provider normal rechazaría con un 400 legible, aquí llega hasta Meta. **La validación en n8n es la única red** ([NOTION_SCHEMA §4](./CONTENT_PIPELINE_NOTION_SCHEMA.md)).

**2. El audio nunca se aplica.** `audioConfiguration`, en `post()` de `instagram.provider.ts`, exige `type === 'graph.facebook.com'`. Con `graph.instagram.com` la condición es falsa y el parámetro **se descarta en silencio**, sin error. No tiene sentido exponer `audio_id` en Notion.

**3. Los colaboradores sí se envían** — `const collaborators`, en `post()` de `instagram.provider.ts`, no distingue por `type`. Que Meta los acepte en la API de Instagram Login es un límite conocido ([NOTION_POSTIZ §6](./CONTENT_PIPELINE_NOTION_POSTIZ.md)).

> **Regla general:** ante cualquier afirmación sobre validación, manda `instagram.standalone.provider.ts`, no `instagram.provider.ts`. Sólo la lógica de publicación y `handleErrors` son compartidas.

## 10. Lo que el fork añade para el pipeline

| Qué | Dónde |
|---|---|
| Webhook en todo camino terminal, con el `Post.id` interno (§4) | `post.workflow.v1.0.6.ts`, en `apps/orchestrator/src/workflows/post-workflows/`; exportado en `apps/orchestrator/src/workflows/index.ts` y arrancado desde `startWorkflow` de `posts.service.ts` |
| `releaseId` + `error` en el payload del webhook (§4.3) | `getPostByForWebhookId` de `posts.repository.ts` |
| **`DELETE /public/v1/media/:id`** — sólo existía en la API con sesión | `public.integrations.controller.ts` |
| **`upload-from-url` por streaming** ([SYNC §2](./CONTENT_PIPELINE_SYNC.md)) | `public.integrations.controller.ts` + `local.storage.ts` (`uploadStream`) + `upload.interface.ts` |
| Identidad externa `Post.externalId` ([RECONCILIACION §3](./CONTENT_PIPELINE_RECONCILIACION.md)) | `create.post.dto.ts`, `posts.service.ts`, `posts.repository.ts`, `schema.prisma` |
| Validación de fotos y videos contra la referencia de Meta (§5) | `instagram.media.rules.ts`; `probeUploadedImage` de `social.abstract.ts` |
| Sondeo de contenedores acotado y reintento de errores transitorios de Meta ([SYNC §3](./CONTENT_PIPELINE_SYNC.md)) | `waitForContainer` y `handleErrors` de `instagram.provider.ts` |

Cómo llega un cambio a producción: [ARRANQUE_Y_SUPERVISION.md](./ARRANQUE_Y_SUPERVISION.md), «Despliegue».

> ### ⚠️ Tocar un `post.workflow.vX` con ejecuciones en vuelo rompe los replays
> Temporal reproduce el historial de una ejecución contra la definición actual del workflow. Por eso la convención del proyecto es **un fichero por versión**, y por eso las versiones anteriores siguen exportadas aunque ya no se arranquen.
>
> Editar una versión existente **sólo es seguro si no hay ninguna ejecución suya corriendo** — se comprueba en Temporal antes de tocarla. Un post programado mantiene su workflow vivo desde que se crea hasta que publica, así que puede haber ejecuciones en vuelo durante semanas.
>
> Editar un post desde la UI reinicia su workflow (`startWorkflow` de `posts.service.ts`), y entonces pasa a arrancar con la versión actual.
