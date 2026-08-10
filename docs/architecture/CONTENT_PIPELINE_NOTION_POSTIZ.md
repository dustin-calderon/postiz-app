# Pipeline de contenido — Notion → n8n → Postiz → Instagram

> **Qué es esto:** la arquitectura del pipeline que publica en Instagram desde Notion —qué hace cada pieza y **por qué** es así—, más las restricciones del fork de Postiz que la condicionan.
> **Estado:** operativo. Lo construido y dónde vive: §14. Lo que no cubre: §14.5. Lo que queda por delante: §10.
> **Ámbito:** Instagram — **3 cuentas** (`instagram-standalone`, §4.9). Una sola tabla de Notion; ver la deuda conocida en §7.1
>
> ### 🗺️ ¿Buscas cómo encaja todo, no por qué?
> **→ [CONTENT_PIPELINE_DIAGRAMS.md](./CONTENT_PIPELINE_DIAGRAMS.md)** — el mapa visual: los cuatro workflows nodo a nodo, las puertas del planificador, la máquina de estados, la secuencia de un día y qué pasa cuando algo falla.
>
> Este documento explica **por qué** cada decisión es como es. Aquél enseña **cómo funciona**. Si sólo vas a leer uno y quieres operar el sistema, empieza por los diagramas.
>
> **Relacionado:** [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md) · [PLAN_ARCHIVO_DRIVE.md](./PLAN_ARCHIVO_DRIVE.md) · [VIDEO_FORMAT_SUPPORT.md](./VIDEO_FORMAT_SUPPORT.md) · [ARRANQUE_Y_SUPERVISION.md](./ARRANQUE_Y_SUPERVISION.md)
>
> ### ⚠️ Si el pipeline «no hace nada», mira primero si el backend está vivo
> El 2026-08-04 la API estuvo 2 h 38 min caída detrás de un contenedor que se
> declaraba `healthy`, y desde fuera se parecía a un fallo del pipeline. No lo era.
> **→ [ARRANQUE_Y_SUPERVISION.md](./ARRANQUE_Y_SUPERVISION.md)** cubre esa capa:
> cómo arrancan los tres procesos, quién los vigila y cómo comprobar en un
> comando que un arranque fue bien.

---

## 1. Decisión de arquitectura

Tres herramientas, todas con UI, ninguna que obligue al equipo a programar.

**Notion es la fuente de verdad (SSoT) — incluidos los ficheros máster.** El equipo no sale de Notion: planifica, escribe el copy, arrastra el vídeo a la fila y marca `Status = Listo`.

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

**El Seagate no queda fuera: es donde Postiz guarda los medios.** `/uploads` es un bind mount a `/mnt/seagate/postiz-media` . Lo que se descartó fue montar una **biblioteca paralela** en `/srv/media` con watchers y ffmpeg (§13) — no el disco.

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

Con `STORAGE_PROVIDER=local` esa URL es `FRONTEND_URL + /uploads + /YYYY/MM/DD/<32 hex>.<ext>` (`local.storage.ts:84,133,193`), y Meta la alcanza: `facebookexternalhit/1.1` recibe **200**.

> ### ⚠️ Este dominio devuelve 403 a los agentes de IA
> El `robots.txt` sirve la política de Content Signals de Cloudflare, que **bloquea crawlers de IA**. Desde una misma IP y un mismo path: UA vacío → 200, `python-requests` → 200, `facebookexternalhit/1.1` → 200, `ClaudeBot/1.0` → **403**.
>
> No afecta a la publicación, pero sí a cómo se comprueba: **el alcance de una URL de este dominio no se puede verificar con un agente de IA** — siempre dará 403 y parecerá una avería de infraestructura que no existe. Se comprueba con `curl` desde el Beelink variando el UA, o desde un móvil con datos.

### 4.2 Storage: sólo `local` o `cloudflare`

`upload.factory.ts` no admite nada más, y `cloudflare.storage.ts:45` **hardcodea** el endpoint `https://${accountID}.r2.cloudflarestorage.com`. No hay hueco para MinIO ni para otro S3 compatible: no es que falte soporte, es que no hay dónde ponerlo.

**Decisión: `local`.** Verificado que Meta alcanza las URLs del dominio . Los medios viven en el Seagate vía bind mount, no hace falta almacenamiento externo.

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
- El default del código es 90. En producción está en **300** (§14.4).

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

> **Impacto:** añadir `sendWebhooks` "en los `return false`" dando por hecho que el estado ya es `ERROR` **no se sostiene en ese camino**. El cambio tiene que poner `changeState('ERROR')` también ahí, o el webhook saldrá diciendo `QUEUE`.
>
> Además hay fallos **anteriores al bucle** (`:86`, `:91`, `:108`, `:123`, `:143`) que tampoco están cubiertos por ese rango.

**✅ Resuelto en la `v1.0.6`: todo camino terminal emite webhook.** Los cinco fallos previos al bucle también, porque el más probable de todos es `Refresh channel needed` — el token de Instagram caduca, el post falla y sin webhook nadie fuera de Postiz se entera hasta la pasada de recuperación del día siguiente.

El invariante "**todo camino terminal emite webhook**" es más fácil de sostener en el tiempo que "algunos sí y otros no", que es lo que obliga a releer el fichero entero en cada cambio.


### 4.4.1 ⚠️ El webhook se dispara hoy con el cuerpo vacío

`post.workflow.v1.0.5.ts:272-276` llama a `sendWebhooks(postsResults[0].postId, …)`. Ese `postId` es **el ID de la red social** (`mediaId` de Instagram), no el `Post.id` interno — véase `updatePost(postsList[i].id, postsResults[i].postId, …)` en `:196-200`, que los usa como cosas distintas.

Pero `getPostByForWebhookId` (`posts.repository.ts:869-875`) busca por `where: { id: postId }`, es decir **por el id interno**. Con el ID de Instagram no encuentra nada y `findMany` devuelve `[]`.

**Resultado: el webhook llega con `[]` como cuerpo.** Se dispara, pero no dice de qué post habla ni en qué estado quedó.

> Todo el cierre reactivo del §9.4 depende de que ese payload traiga el post. **Sin arreglarlo, el diseño no funciona.** Corregido en la `v1.0.6`.

**✅ Diagnóstico confirmado contra la base de producción**, sin publicar nada. Los dos espacios de identificadores son disjuntos:

```sql
Post.id     = cmrah83mf0001tb78bxpfhpob   -- cuid
releaseId   = 18442815235186433           -- id de media de Instagram
SELECT count(*) FROM "Post" p WHERE EXISTS (SELECT 1 FROM "Post" q WHERE q."releaseId" = p.id);
 count = 0
```

Cero solapamiento: la `v1.0.5` **nunca** pudo encontrar el post. Y la consulta de la `v1.0.6`, con el id interno, devuelve la fila con su `content` y su `state`.

### 4.4.2 La entrega del webhook no está garantizada

`post.activity.ts:326-340` envuelve el `fetch` en `try { … } catch (e) { /**empty**/ }`. Si n8n está caído o hay timeout, **el fallo se traga sin log y sin reintento**, y el `Promise.all` no propaga nada al workflow.

Un `Publicado` perdido no se recupera solo. **Por eso no se puede eliminar el polling del todo** (§9.4).

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

Para que el consumidor pueda aplicarla, `getPostByForWebhookId` incluye ahora `releaseId` y `error` en su `select`. Sin `error`, `❌ error_log` nunca podría llevar el motivo que pide §9.4.

### 4.5 Postiz valida el post antes de crearlo

`instagram.provider.ts:48-57` rechaza >10 medias y exige al menos una. El API público ejecuta `validatePosts` antes de crear nada y devuelve un 400 legible. La validación en n8n sigue siendo buena idea (fallar antes es mejor), pero no es la última línea de defensa.

> ### ⚠️ …salvo con `modo = borrador`, donde casi no valida nada
> El resultado de `checkValidity` viaja en `item.errors`, y ese campo **sólo se comprueba dentro de `if (body.type !== 'draft')`** (`public.integrations.controller.ts:267-279`). Fuera de ese bloque queda una sola comprobación: `emptyContent`, que exige que el texto **y** las imágenes estén vacíos **a la vez** (`posts.service.ts:831-835`).
>
> Es decir: un borrador sin ninguna imagen pero con copy pasa sin queja, aunque `checkValidity` lo habría rechazado con *«Should have at least one media»*.
>
> **Con `modo = borrador`, n8n es la única defensa incluso para las reglas que §7.4 marca como «✅ Sí».** Es la misma razón por la que §10 descarta usar borradores como dry-run.

### 4.6 `createPost` devuelve un ID por integración

`posts.service.ts:927` → `[{ postId, integration }]`. De ahí la regla **una fila = un post**.

### 4.7 La limpieza de medios, y por qué su retención dejó de ser 30

Según [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md):

- `MEDIA_RETENTION_DAYS` — default del código **30**; **en producción, `3650` desde el 2026-08-04**
- El filtro es **positivo**: sólo son candidatos los medias cuyo `path` aparece en un `Post` con `state='PUBLISHED'` y `publishDate` anterior a la retención
- Hard-delete **7 días** después del soft-delete

**Un asset subido hoy y programado para dentro de tres semanas no corre ningún riesgo**: no ha sido publicado, luego no es candidato. Eso no depende del número de días.

> ### ⚠️ La retención se subió a 3650. El razonamiento de los 30 días era cierto a medias
> Este documento sostenía que 30 días eran correctos **porque el original vive en Notion** — y avisaba: *«si algún día Postiz volviera a ser el único sitio donde vive el fichero, esta variable pasa a ser una bomba y hay que subirla»*.
>
> **Ya lo era, y no para el futuro sino para el pasado.** Los **18 posts publicados desde la UI de Postiz no tienen fila en Notion**: para ellos la caché del Seagate no era una copia derivada, era la única. Nueve ya habían perdido sus ficheros cuando se miró —junio es la fecha en que se **subieron**, no en que se publicaron: dos de esas nueve salieron ya en julio—; los otros nueve conservaban 201,0 MB —191,7 MiB en 18 ficheros distintos— que se habrían empezado a purgar el 2026-08-05. (La cifra que figuraba aquí, 214,5 MB, era falsa: contaba dos veces un `.mov` referenciado por dos publicaciones y etiquetaba MiB como MB.)
>
> Tampoco había red debajo: **ninguna copia de seguridad del servidor tocaba Postiz** — `backup-daily.sh` sólo volcaba bases de datos y configuración, y ningún cron ni timer rozaba `/mnt/seagate`. Hoy ya no es así: los medios los copia el espejo a Drive de las 02:40 (desde el 2026-08-04) y la base entra en `backup-daily.sh` (desde el 2026-08-05).
>
> **Aplicado: `MEDIA_RETENTION_DAYS = 3650`** (§14.4). El procedimiento no es obvio —el workflow lleva la retención como argumento y hay que terminarlo y relanzarlo en Temporal, no basta con reiniciar el contenedor—: está en [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md).

La afirmación que sí se sostiene, acotada: **para el material que pasa por el pipeline**, la copia de Postiz es derivada y reconstruible desde Notion. Para todo lo anterior a agosto de 2026, no. La retención larga es el parche que compra tiempo; la solución de raíz es el archivo en Drive ([PLAN_ARCHIVO_DRIVE.md](./PLAN_ARCHIVO_DRIVE.md)), que da una segunda copia navegable a lo publicado, venga de Notion o no.

---

### 4.8 Borrar un post termina su workflow

`posts.service.ts:660-677`: `deletePost` busca las ejecuciones de Temporal asociadas y las termina.

```ts
query: `postId="${post.id}" AND ExecutionStatus="Running"`
...
await workflow.terminate();
```

**Esta es la garantía que hace viable el modelo de reconciliación** (§9). Sin ella, borrar y recrear dejaría workflows zombis publicando posts borrados.

### 4.9 ⚠️ Las 3 cuentas usan `instagram-standalone`, no `instagram`

Verificado en la base de datos de producción: las tres integraciones tienen `providerIdentifier = 'instagram-standalone'`.

| Integración | Cuenta |
|---|---|
| `cmqjq77hg0001mw7y2xf6bg86` | Dustin Calderón \| Compositor de Teatro Musical |
| `cmqjqapu00003mw7yrudcwklj` | CITEM Conservatorio Iberoamericano de Teatro Musical ⚠️ *(nombre obsoleto — ver nota)* |
| `cmqjqfvnw0005mw7yoywgo6he` | AMORISMO VOL III |

> ⚠️ **El nombre de la integración de CITEM está obsoleto en Postiz, no en Instagram** (verificado 2026-08-10).
> La cuenta real es **`citem.teatromusical` · `CITEM - Ecosistema Digital de Teatro Musical`**.
> `Conservatorio Iberoamericano de Teatro Musical` está retirado de todo el ecosistema desde
> ADR-044 (2026-07-21) — ver `campus_dc/docs/branding/POSITIONING.md` §5.
>
> Postiz **cachea el nombre en el momento de conectar** la integración y no lo refresca solo, así
> que su BD conserva el nombre viejo. **No es un bug de datos ni hay que editar la BD a mano:** se
> corrige reconectando la integración de Instagram desde la UI de Postiz. Mientras no se reconecte,
> cualquier informe o `post.txt` generado desde esta tabla arrastrará el nombre retirado — que es
> justo lo que pasa en `PLAN_ARCHIVO_DRIVE.md` §`post.txt`.

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

**3. Los colaboradores sí se envían** — el bloque de `instagram.provider.ts:640-645` no distingue por `type`. Lo que **no está verificado** es que Meta los acepte en la API de Instagram Login. **Se aceptó como deuda técnica y no se va a probar de momento** (decisión #7 de §11): comprobarlo exige publicar de verdad en una cuenta real.

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
- ✗ **Nunca se editan a mano** `❌ postiz_post_id`, `❌ postiz_media`, `❌ release_url` ni `Status = Programado`.
- ✓ **El `❌ postiz_post_id` dice la verdad, no el `Status`.** El estado es para las personas; el ID es para la máquina: si los dos se contradicen, manda el ID.
- ✓ **Una fila = un post = una integración.** Aunque hoy sólo haya Instagram.

---

## 7. Esquema de Notion — una sola tabla

**Todo vive en el calendario que ya existe**, `collection://186a2405-a123-81dc-832f-000b82a65c0c`. No se crea ninguna tabla nueva: se le añaden las propiedades del pipeline.

### 7.1 Lo que ya tiene y se aprovecha

`Name`, `Brand` (4 marcas), `Plataforma` (5), `Tipo`, `Fecha`, `Notas`, `Content Series`, `🌐 Projects`, `URL`, `Agendada`, `Validación`.

> Esta lista cambia cuando el equipo reorganiza el calendario, y da igual: **el pipeline no mira ninguna de ellas**. La lista que sí importa es la de §7.2.

*(Había también un `Status` de tipo *status* con el ciclo de producción del equipo. Se fusionó con el estado del pipeline — §7.2.)*

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

**Once propiedades nuevas, ni una más.** (Diez en la tabla, más `❌ release_url`, que dejó de reutilizar `URL` al cerrarse la decisión #3 de §11.)

| Propiedad | Tipo | Lo escribe | → API |
|---|---|---|---|
| `cuenta` | **Select** | equipo | `integration.id` (§7.2.1) |
| `colaboradores` | Multi-select | equipo | `settings.collaborators[].label` — **restricciones en §7.2.4** |
| `copy` | Text | equipo / agente | `value[0].content` |
| `media` | **Files** | equipo | `value[0].image[]` — **en orden** |
| `first_comment` | Text | equipo / agente | `value[1].content` (§7.3) |
| `modo` | Select: `borrador`·`programar` | equipo | **`type`** (§7.2.2) |
| `Status` | Select | equipo → n8n | ✗ — el estado del pipeline (§8) |
| `❌ postiz_post_id` | Text | **n8n** | — el candado |
| `❌ postiz_media` | Text | **n8n** | — JSON `[{id, path}]`, mismo orden que `media`. Ver aviso |
| `❌ error_log` | Text | **n8n** | — último error |

Y tres cosas que **no** son propiedades nuevas:

- **`post_type`** sale de `Tipo` (§7.1). Es obligatorio en la API (`@IsDefined()` en `InstagramDto`), pero no hace falta pedirlo dos veces.
- **`publish_at`** es `Fecha`, con hora (§7.5).
- **`❌ release_url`** es **propiedad propia** (tipo `url`). Se planteó reutilizar la `URL` que ya existía y se descartó: `URL` es tuya y tiene otro uso (decisión #3 de §11).

> **El aviso de error irá al correo de quien creó la fila.** No hace falta propiedad: Notion expone `created_by` como metadato de página y n8n puede resolverlo a email, con una dirección general de reserva. **Diseño decidido, implementación pendiente** (§11): hoy los fallos se ven en la vista *⚠️ Averías*.

> ### ⚠️ Renombrar una propiedad rompe el worker
> Los workflows buscan las propiedades **por su nombre exacto**, acentos y emoji incluidos. Renombrar una en Notion y no tocar n8n tiene dos desenlaces, ninguno bueno:
>
> - `Plataforma` o `Status` → el sync falla entero y **no publica nada**. Al menos se nota.
> - Cualquier otra → el sync sigue corriendo pero **deja de ver ese campo**, y la fila acaba en `Error` con un motivo engañoso («sin cuenta» con la cuenta puesta).
>
> **Se puede renombrar**, pero hay que actualizar los cuatro workflows en el mismo movimiento. Las propiedades libres —las que ningún workflow toca— son `Brand`, `Notas`, `Content Series`, `🌐 Projects`, `URL`, `Agendada` y `Validación`; y cualquier otra que se añada. `Name` sólo se usa para etiquetar la ejecución en n8n: renombrarla es cosmético.

Los tres campos de n8n (`❌ postiz_post_id`, `❌ postiz_media`, `❌ error_log`) son **territorio exclusivo del worker**. Si alguien se ve editándolos a mano, algo se ha roto.

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

> ### `Status` es una sola propiedad, y antes fueron dos
> El diseño original tenía **dos**: el `Status` original —de tipo *status*, con el ciclo de producción del equipo— y una `publicación` aparte con los estados del pipeline. La razón era técnica: **al tipo *status* la API de Notion no le puede añadir opciones**, así que no había forma de meterle `Listo`, `Programado` ni `Error` desde un script.
>
> **Se fusionaron.** El `Status` original se borró y `publicación` pasó a llamarse `Status`. Dos motivos:
>
> - **Convivían dos vocabularios que se pisaban.** «Borrador» significaba una cosa en `Status`, otra en `modo` y otra en `publicación`. «Publicado» aparecía en dos propiedades con sentidos distintos —lo dio por cerrado una persona, o salió de verdad en Instagram—.
> - **El calendario es de Instagram.** De 136 filas, 99 son sólo de Instagram y apenas 4 de otra plataforma. Mantener un ciclo de producción separado «para las demás plataformas» no compensaba.
>
> El `Status` que queda es un *select*, así que **ahora sí se le pueden añadir opciones por API** si algún día hace falta vocabulario de producción (`Sin empezar`, `En progreso`).
>
> Se guardó copia de los 136 valores del `Status` anterior en `/opt/homeserver/n8n-workflows/backup-Status-20260804.json`.

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

`borrador` sirve para dos cosas: el **dry-run** editorial y para revisar una pieza en la vista real de Postiz antes de soltarla. Cambiar de `borrador` a `programar` lo recoge el sync en la siguiente pasada, o al pulsar el botón.

> **No contradice "nunca se aprueba en Postiz" (§6).** La aprobación sigue siendo `Status = Listo` en Notion. `modo` sólo decide qué hace Postiz con algo ya aprobado. Nadie promueve un draft desde la UI de Postiz — si lo hiciera, la siguiente pasada del sync lo revertiría.

> ### ⚠️ Un borrador **no pasa por la validación del servidor**
> `checkValidity`, los ajustes y el límite de 2200 caracteres se comprueban **sólo** dentro de `if (body.type !== 'draft')` (§4.2, `public.integrations.controller.ts:267-279`). Un `borrador` entra con lo único que se mira siempre: que no esté vacío del todo.
>
> Consecuencia: una pieza que en `borrador` se crea sin quejarse puede **fallar al pasarla a `programar`**. El dry-run editorial no es un dry-run técnico. Las validaciones de n8n (§9.2) sí corren en ambos casos, y son las que atrapan casi todo.

### 7.2.3 Ajustes opcionales de Instagram

Se añaden a la tabla el día que se necesiten. Añadir una propiedad en Notion cuesta diez segundos; lo que importa es que el mapeo esté escrito.

| Campo Notion | Tipo | → API | Restricción |
|---|---|---|---|
| `is_trial_reel` | Checkbox | `settings.is_trial_reel` | **Exactamente 1 media, debe ser vídeo, y `Tipo` ≠ `Historia`** — ver abajo dónde se comprueba cada una |
| `graduation_strategy` | Select | `settings.graduation_strategy` | `MANUAL`·`SS_PERFORMANCE`. Sólo con trial reel |
| `thumbnail_seconds` | Number | `image[].thumbnailTimestamp` | **No declarado en `MediaDto`** — sobrevive porque el ValidationPipe no usa `whitelist` (`main.ts:53-57`). Frágil ante merges. Tampoco se envía en stories |

> **`audio_id` no está en la lista a propósito.** Con `instagram-standalone` el parámetro se descarta en silencio (§4.9). Exponerlo en Notion sería ofrecer un botón que no hace nada.

> ### ⚠️ Las tres reglas del trial reel no se comprueban en el mismo sitio
> Leer sólo el código de Postiz lleva a la conclusión equivocada. `instagram.standalone.provider.ts:53-63` valida **dos**: `'Trial Reels can only have one video'` y `'Trial Reels must be a video'`. La tercera **no está ahí**: `instagram.provider.ts:631` añade `trial_params` aunque `isStory` sea `true`, sin guarda.
>
> Quien la comprueba es **el subflow de n8n**, antes de llegar a Postiz, con el motivo `trial reel: no puede ser una Historia`. Verificado por `prueba-trial-reels.py` (12/12 el 2026-08-05), que cubre las tres.
>
> La consecuencia práctica: para una fila que venga de Notion las tres dan `Error` legible, pero **un post creado directamente contra la API de Postiz se saltaría la tercera**. Es otra razón por la que §6 prohíbe publicar sin pasar por Notion.

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

Por eso `first_comment` es un campo propio y no parte de `copy`: es una decisión editorial distinta y conviene poder verla y editarla por separado.

> **Dos precisiones verificadas:**
> - **Las imágenes de un comentario se ignoran en Instagram.** `instagram.provider.ts:820-860` sólo manda `message=` a `/comments`. Un comentario con ficheros publica sólo el texto.
> - **`delay` está en minutos**, no en segundos ni ms: `post.workflow.v1.0.5.ts:179-180` hace `sleep(60000 * delay)`.

### 7.4 Reglas de validación previas al envío

El worker las comprueba antes de gastar una llamada. Todas verificadas en `instagram.provider.ts`:

**Ojo: estas reglas son para `instagram-standalone` (§4.9), que valida mucho menos que el provider normal.**

| Regla | ¿La para Postiz? | Dónde |
|---|---|---|
| Al menos 1 media | ✅ Sí\* | `instagram.standalone.provider.ts:50-52` |
| Trial reel: 1 media y vídeo | ✅ Sí\* | `instagram.standalone.provider.ts:53-63` |
| **Máximo 10 medias** | ❌ **No** | El provider normal sí, el standalone **no**. Llega a Meta |
| **Carrusel: mínimo 2 medias** | ❌ No | Error de Instagram, traducido en `instagram.provider.ts:362-367` |
| **Colaboradores en carrusel** | ❌ No | Error de Instagram, traducido en `instagram.provider.ts:376-381` |
| **Colaboradores en story** | ❌ No | Se **descartan en silencio** (`!isStory`, sin error) |
| **Audio** | ❌ No | Se **descarta en silencio**: exige `graph.facebook.com` (§4.9) |

> **\* Sólo con `modo = programar`.** Con `borrador`, Postiz se salta `checkValidity` entero (§4.5), así que **ninguna** de las siete la para: son 7 de 7 a cargo de n8n.

> ### ⚠️ Cinco de estas siete no dan error, o lo dan tarde
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

Las opciones de la propiedad `Status` (§7.2):

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

**`Status` es la única propiedad de estado.** Antes había dos —un ciclo de producción propio y el del pipeline— y se fusionaron; el porqué está en §7.2. Tú escribes `Listo` y n8n escribe el resto.

A partir de `Listo` nadie vuelve a tocar `Status` — pero **sí se puede seguir editando el contenido**: el sync propaga los cambios mientras el post no se haya publicado (§9).

`Programado → Publicado` y `Programado → Error` los escribe n8n al recibir el webhook de Postiz. Ninguna de las dos transiciones necesita polling.

**Con `modo = borrador`** (§7.2.2) la fila sincronizada no va a `Programado` sino a **`En Postiz (borrador)`**. Es un estado propio a propósito: si reutilizáramos `Programado`, alguien daría por hecho que va a salir y no saldría nunca. Desde ahí se pasa a `Programado` cambiando `modo`, no la propiedad `Status`.

**Postiz no se entera de que la pieza existe hasta que `Status = Listo`.** El borrador *editorial* vive en Notion y no sale de ahí. Lo que Postiz recibe ya está aprobado; `modo` sólo decide si además queda programado o esperando.

### 8.1 El camino de vuelta desde `Error`

`Error` **no es un sumidero**. Se corrige lo que falló y se devuelve `Status` a `Listo` vaciando `❌ error_log`.

Al reintentar, el worker **reutiliza `❌ postiz_media` si ya tiene valor** y sólo re-transfiere los ficheros si está vacío. Esto es lo que evita volver a mover un reel de 100 MB por un fallo que ocurrió después de la subida.

> Si el error fue **en el propio fichero** (se subió el vídeo equivocado), hay que **vaciar `❌ postiz_media` a mano** además de cambiar los ficheros. Es la única excepción a "no se editan a mano los campos del worker", y conviene tenerla escrita.

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
> **Cómo se configura el botón.** Es una propiedad de tipo **Botón** en el calendario, con la acción *Enviar webhook*. Hay dos URLs válidas y ambas desembocan en el mismo nodo:

| URL | Auth | |
|---|---|---|
| `…/webhook/` + `N8N_SYNC_IG_BUTTON_PATH` | el secreto va en la ruta | **← la que usa el botón** |
| `…/webhook/postiz-sync-ig` | cabecera `X-Sync-Token` | para scripts y `curl` |

El apartado **«Contenido» se deja vacío** — el workflow no lee el cuerpo, relee el calendario por su cuenta.

> La variante con cabecera sería algo mejor —un secreto en la ruta acaba en los logs de ejecución de n8n y del túnel; en una cabecera, no— y la UI de Notion **sí** admite encabezados personalizados. Cambiarlo es editar la automatización del botón; no urge, porque la ruta viaja cifrada bajo HTTPS.

**Cómo se distingue una pulsación del botón en n8n:** la petición llega con `user-agent: NotionAutomation` y un cuerpo `{"source":{"type":"automation","automation_id":…}}`. El cron, en cambio, no pasa por ningún nodo webhook.

> **La propiedad botón no se puede crear por API.** Las dos versiones (`2022-06-28` y `2025-09-03`) rechazan el tipo `button`; los 23 tipos que aceptan no lo incluyen. Es UI o nada, y tiene que ser una propiedad de tipo Botón, no un sucedáneo.

### 9.2 Qué hace el subflow con una fila

| Situación | Acción |
|---|---|
| `Plataforma` no contiene Instagram | Invisible para el worker |
| `Status` vacío | No crear nada — **la retirada (§9.7) lo borra de Postiz si existía** |
| `Status` = `Publicado` | **No tocar jamás** |
| Dentro del margen de seguridad **y ya tiene `❌ postiz_post_id`** (§9.3) | **Saltar** — se reporta en la ejecución, **no** se escribe en `❌ error_log` (ver nota) |
| `❌ postiz_post_id` vacío | Crear |
| Tiene `❌ postiz_post_id`, aún no publicado | **Borrar y recrear** |
| `❌ postiz_media` con valor | No re-subir los assets |
| `Fecha` sin hora | `Error` — nunca se adivina la hora |
| `Fecha` ya pasó y nunca se sincronizó | `Error` + motivo |

> ⚠️ La segunda fila **no es "ignorar y seguir"**. Si sólo se implementa esta tabla y no §9.7, vaciar `Status` de una fila ya sincronizada deja el post programado en Postiz y **sale publicado igual**. Las dos partes son una sola.

> ### ⚠️ El orden de las puertas importa: primero la hora, después la ventana
> Parece intercambiable y no lo es. Notion devuelve una fecha sin hora como `2026-08-10` a secas, y `new Date('2026-08-10')` la interpreta como **medianoche UTC**. Si el margen de 2 h se evalúa antes que la comprobación de hora, esa fila puede caer dentro del margen y salir como «saltar» — es decir, **la fila sin hora nunca llega a `Error`**, que es justo lo contrario de la regla.
>
> El orden implementado es: **validaciones estructurales** (hora, offset, cuenta, copy, media, colaboradores) → y sólo con una fecha válida, **ventana → pasado → margen**.
>
> No es teórico: hoy **1 de cada 100 filas** con fecha tiene hora.

> **Sobre el margen y `❌ error_log`:** saltar por el margen de seguridad no es un error, es el sistema funcionando. Escribirlo en `❌ error_log` dejaría un mensaje de avería en una fila sana y acabaría entrenando al equipo a ignorar ese campo. Se reporta en la ejecución de n8n; la fila se recoge sola en la siguiente pasada.

Superadas las puertas, cada fila es **un solo post**, así que el subflow es lineal:

```
1. valida  ≤10 items · reglas de §7.4                    ← el tamaño ya no,
           colaboradores ⇒ ni carrusel ni story            lo aplica Postiz (§9.2)
2. resuelve `cuenta` ──► integration.id                  (§7.2.1)
3. si tiene ❌ postiz_post_id y no está publicado ──► DELETE primero
4. si `❌ postiz_media` está vacío:
      pide a Notion la URL FRESCA de cada fichero   ← nunca una guardada
      POST /public/v1/upload-from-url  { "url": ... }
        └─ los bytes NO pasan por n8n: los baja Postiz, por streaming
      └──► ESCRIBE ❌ postiz_media                      [write 1]
5. POST /public/v1/posts
      type                        = modo                 (§7.2.2)
      value[0].content            = copy
      value[0].image[]            = ❌ postiz_media
      value[1].content            = first_comment        (si lo hay, §7.3)
      settings.collaborators[]    = colaboradores        (si los hay)
      └──► ESCRIBE ❌ postiz_post_id                        [write 2]
           Status = Programado           si modo = programar
           Status = En Postiz (borrador) si modo = borrador

   si el paso 5 falla:
      Status = Error · ❌ error_log = motivo
      y si el media se subió EN ESTA pasada:
        DELETE /public/v1/media/:id  +  vaciar ❌ postiz_media
```

> ### Por qué el worker borra su propio media al fallar
> La limpieza automática sólo hace candidato lo que aparece en un post **publicado**. Un fichero subido y nunca publicado **no lo recoge nadie**, valga lo que valga `MEDIA_RETENTION_DAYS`. Sin este paso, cada fila abandonada tras un fallo dejaría un reel de 150 MB en el Seagate para siempre.
>
> **Sólo se borra lo subido en esa misma pasada.** Si el media venía reutilizado de un intento anterior (§8.1), borrarlo dejaría `❌ postiz_media` apuntando a la nada. Y cuando se borra, se vacía también `❌ postiz_media`, para que el reintento vuelva a subir.
>
> Requirió **añadir `DELETE /public/v1/media/:id` a la API pública del fork** — sólo existía en la API con sesión.

> **No hay fan-out.** Una pieza compartida entre cuentas es un post con colaboradores (§7.2.4), no N posts. Eso mantiene el 1:1 con Postiz —un ID, un estado, un `❌ release_url`— y elimina cualquier necesidad de estados parciales o de una tabla intermedia.
>
> La excepción son los **carruseles y stories compartidos**, que Instagram no permite compartir: ahí son filas independientes, y cada una sigue siendo un post. El modelo no cambia.

Las dos escrituras siguen separadas: guardar `❌ postiz_media` en cuanto sube hace el proceso **reanudable a mitad**, y evita volver a subir un reel en cada resincronización.

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
> ### El tope de 300 MB desapareció: `upload-from-url` va por streaming
>
> La primera versión hacía `Buffer.from(await response.arrayBuffer())`, así que la memoria crecía con el fichero — y como este proceso **también corre el orchestrator**, una subida grande se llevaba por delante la publicación programada. De ahí venían los 300 MB y la sonda de tamaño en n8n: gestionar el síntoma.
>
> Ahora el tipo se detecta con `fileType.stream()` —lee la cabecera y sigue emitiendo todos los bytes— y se vuelca a disco con `pipeline()`. **La memoria pasa a ser constante.** Medido:
>
> | Fichero | Memoria de Postiz | Tiempo |
> |---|---|---|
> | 672 MB | **2130 MB → 2132 MB** | 8 s |
>
> Dos megas de diferencia para 672 de fichero, con `md5` idéntico en destino. (Los 2,1 GB son la línea base de los tres procesos, no la subida: en reposo no se movía de 2130.)
>
> El único límite que queda es **`MAX_URL_UPLOAD_BYTES`**, hoy **1 GiB**, y existe para que una URL equivocada no llene el disco — no para acotar la RAM. Probado con un fichero de 1,4 GB: `400` con mensaje legible y **sin dejar fichero parcial**.
>
> **La sonda de tamaño de n8n se eliminó.** El límite vive ahora en un solo sitio, que es el que puede aplicarlo; duplicar la constante en los dos lados era una trampa de mantenimiento. Si Postiz lo rechaza, su mensaje llega tal cual a `❌ error_log`.
>
> `uploadStream` es **opcional** en `IUploadProvider`: quien no pueda streamear —R2 necesitaría multipart— no lo implementa y el llamante cae al camino con buffer, que se conserva intacto.

### 9.3 El margen de seguridad — obligatorio

**No se borra y recrea ninguna fila cuyo `publish_at` esté dentro de las próximas 2 horas.**

Borrar y recrear abre una ventana en la que el post no existe en Postiz. Hacerlo cerca de la hora de publicación es una carrera contra el orchestrator, con dos finales malos: el post se pierde, o se recrea con una fecha ya pasada y el comportamiento deja de ser predecible.

> **Este guardarraíl vive en el subflow, no en el horario del cron.** La hora del cron (06:00 Europe/Madrid) ya garantiza que **el cron** nunca colisione con una publicación. Pero **el botón se dispara cuando alguien lo pulsa**, y antes o después alguien va a tocar un post veinte minutos antes de que salga. El guardarraíl existe por el botón, no por el cron. Son tres líneas en el subflow.

Si una fila cae dentro del margen, el sync **no hace nada** y lo anota. Si hay que cambiar algo a 20 minutos de publicar, se hace a mano en Postiz — es la única excepción a "nunca se aprueba en Postiz", y es una excepción de emergencia.

> ### ⚠️ El margen sólo se aplica a lo que ya está en Postiz
>
> La condición es `dentro del margen` **Y** `❌ postiz_post_id` no vacío. Sin la segunda mitad el guardarraíl se vuelve del revés y **come filas nuevas**:
>
> - Una fila aprobada a 40 minutos de su hora cae en el margen y se salta.
> - En la siguiente pasada la fecha está **más cerca**, no más lejos: se vuelve a saltar.
> - No hay salida. Nunca se crea, y cuando la fecha pasa la fila termina en `Error` con el motivo equivocado.
>
> El peligro que justifica el margen es la ventana de no-existencia entre el `DELETE` y el `POST`. Una fila sin `❌ postiz_post_id` no tiene nada que borrar: crearla es una sola operación atómica y no hay carrera posible. Aplicarle el margen no protege nada y rompe el caso más común — aprobar algo para hoy mismo.
>
> Salió a la luz con una fila real programada para dentro de dos horas que el botón se negaba a crear, pulsada tras pulsada, sin escribir un solo error.

> ### La hora programada es cuándo *empieza* a publicar, no cuándo aparece
>
> Temporal despierta el workflow al segundo exacto, pero publicar en Instagram no es una llamada: Postiz crea un contenedor por imagen y **sondea el estado de cada uno hasta que Meta los da por procesados** (método `waitForContainer` de `instagram.provider.ts`). Los contenedores se crean en paralelo, así que manda el más lento.
>
> El sondeo pregunta cada 30 s, **devuelve en cuanto Meta responde `FINISHED`** y está acotado a 8 minutos.
>
> Medido en un carrusel de 5 fotos, **antes** de que el sondeo devolviera al primer `FINISHED`: timer disparado a las `18:40:00`, workflow completado a las `18:42:15` — **2 min 15 s**.
>
> Medido **después** del cambio, con un reel de 19 s y 28 MB (2026-08-10): programado a las `14:00:00Z`, Instagram lo sella a las `14:00:32Z` y Postiz lo marca `PUBLISHED` a las `14:00:38`. **38 segundos**, una sola pasada del sondeo y sin reintentos. Un reel pesado sigue tardando más — manda el tiempo que Meta tarde en procesar.
>
> Consecuencia práctica: si la pieza tiene que estar visible a una hora concreta, la `Fecha` de Notion se pone unos minutos antes. Y no hay que dar por fallida una publicación hasta pasados unos minutos de su hora.

> ### Lo que había antes aquí, y por qué se cambió (agosto 2026)
>
> El bucle era `while (status === 'IN_PROGRESS')` con el `await timer(30000)` **antes** de asignar `status = status_code`. Tres defectos, los tres corregidos:
>
> - **Cualquier estado que no fuera `IN_PROGRESS` salía del bucle y publicaba igual**, incluidos `ERROR` y `EXPIRED` — o una respuesta sin `status_code`. Ahora sólo `FINISHED`/`PUBLISHED` siguen adelante; el resto lanza un error legible.
> - **No tenía tope.** `postSocial` corre en una actividad Temporal con `startToCloseTimeout` de 10 min: un contenedor lento agotaba el plazo, Temporal reintentaba y **el vídeo se subía a Instagram por segunda vez**. El tope de 8 min corta eso sin quitarle tiempo a nada que hoy publique bien.
> - **Suelo de 30 s** aunque Meta respondiera «listo» a la primera.
>
> En el mismo cambio: un rate limit de Meta (`code 4`, «Application request limit reached») venía marcado por Meta como **`is_transient: true`** pero Postiz lo convertía en un fallo **no reintentable** con el mensaje inútil «Unknown Error», y el post se perdía. Pasó de verdad con dos posts de CITEM el 6 de agosto de 2026. Ahora `handleErrors` honra el flag `is_transient` de Meta y reintenta. Son 3 reintentos de 5 s: reduce las pérdidas, **no las elimina**.

### 9.4 Cierre del bucle: reactivo

Con el webhook de fallo añadido (§4.4), **publicado y fallido llegan por el mismo canal**:

```
Postiz publica (o falla) ──webhook──► n8n ──► Status = Publicado | Error
                                              ❌ release_url = permalink   (si publicó)
                                              ❌ error_log   = motivo      (si falló)
```

> Es la propiedad `Status` de Notion — no confundir con el `state` interno de Postiz, que es otra cosa y usa otros valores (`QUEUE`, `PUBLISHED`, `ERROR`).

n8n **no mira el `state`**: mira `releaseURL`/`releaseId`. Si vienen con valor, el post está en Instagram aunque el `state` diga `ERROR` (§4.4.3). Sólo si vienen vacíos y el `state` es `ERROR` la fila va a `Error`. Cualquier otra cosa se ignora sin escribir nada.

> ### ⚠️ El webhook es el camino rápido, no el único
> La entrega es best-effort y sin reintento (§4.4.1): si n8n está caído cuando Postiz publica, ese aviso **se pierde para siempre**.
>
> Por eso el cron de las 06:00 hace además una **pasada de recuperación**: para toda fila en `Programado` cuya `Fecha` ya pasó con margen, consulta el estado real en Postiz y corrige. Es barato —va incluido en el `GET` que ya hace la retirada (§9.7)— y es lo único que evita que una fila se quede en `Programado` para siempre.

> **`❌ release_url` sólo puede venir de aquí.** `createPost` devuelve únicamente `[{postId, integration}]` (`posts.service.ts:927`); el permalink no existe hasta que el post sale de verdad, y lo escribe `updatePost` en el workflow. Si el webhook no está montado, ese campo se queda vacío para siempre.

### 9.5 Por qué borrar y recrear, y no actualizar

Semántica inequívoca: el resultado es el estado correcto sin importar qué cambió. Cuesta dos llamadas en vez de una, irrelevante frente a las 300/hora de `API_LIMIT`.

Es seguro por §4.8: `deletePost` termina el workflow de Temporal asociado.

Y **no pone en riesgo los assets** — pero por una razón distinta a la que parece:

- El **Step 2** de la limpieza cuenta los posts soft-deleted como prueba de uso, y eso **convierte el media en candidato a borrado**, no lo protege (`media.repository.ts:304-319`; el comentario del propio código lo dice).
- Quien **protege** es el **Step 3** (`media.repository.ts:338-350`), que exige `p."deletedAt" IS NULL`.

Un post recreado está vivo y sin borrar, luego protege sus ficheros. La conclusión se sostiene; **el razonamiento intuitivo es el contrario del que aplica el código**, y conviene tenerlo escrito para no equivocarse en el próximo cambio.

> **Consecuencia a saber:** `❌ postiz_post_id` cambia en cada resincronización. Es "el post actual en Postiz", no un identificador estable en el tiempo. n8n lo reescribe cada vez, así que Notion siempre tiene el vigente.

### 9.6 El candado que evita duplicados

Crear sólo si `❌ postiz_post_id` está vacío.

Escenario: n8n crea el post y justo antes del write-back se cae el contenedor. La fila queda sin ID. La siguiente pasada la vuelve a crear → **post duplicado en producción**.

El candado actual lo hace improbable, no imposible. La solución definitiva es `externalId` en Postiz (§11, decisión #10): con un índice único por organización, el duplicado pasa a ser **imposible por construcción** y n8n deja de tener que acordarse de nada.

### 9.7 La pasada de retirada — sin ella el sync sólo sabe añadir

**Reconciliar no es sólo crear lo que falta: es también retirar lo que ya no debe existir.**

El subflow de §9.2 itera sobre las filas de Notion. Todo lo que desaparece de esa lista se vuelve invisible para él — y el post correspondiente **se queda programado en Postiz y se publica igual**. Tres formas de provocarlo, todas normales:

| Acción en Notion | Sin pasada de retirada |
|---|---|
| Se borra la fila | El post se publica igualmente |
| `Status` vuelve de `Listo` a vacío | El post se publica igualmente |
| `publish_at` se mueve fuera de la ventana | Se publica en la fecha vieja |

El segundo es el más traicionero: la regla "`status` ∈ (Idea, Draft) → ignorar" hace exactamente lo contrario de lo que la gente espera. Alguien retira un post a borrador para repensarlo, y sale publicado.

**La pasada:** tras sincronizar la ventana, pedir a Postiz lo que tiene programado en ese mismo rango y **borrar todo lo que no tenga una fila viva detrás**.

```
GET /public/v1/posts?startDate=...&endDate=...   ← existe: GetPostsDto
   └─ FILTRAR por state en el propio n8n           ← ver aviso
   └─ FILTRAR por creationMethod === 'API'         ← ver aviso rojo
   └─ para cada post aún no publicado en la ventana:
        ¿sigue habiendo una fila viva en Notion que lo reclame?
          (viva = Status en Listo · Programado · En Postiz (borrador))
          no ──► DELETE /public/v1/posts/:id
```

> ### 🔴 Sin filtrar por `creationMethod`, la retirada borra el trabajo hecho a mano
> Un post creado desde la UI de Postiz **no tiene fila en Notion**, así que "todo lo que no tenga una fila viva detrás" lo incluye. La primera pasada del cron se lo habría llevado.
>
> No es hipotético: en el calendario hay posts creados a mano desde la UI. `GET /posts` expone `creationMethod`, y los valores separan limpiamente los dos orígenes:
>
> | Origen | `creationMethod` |
> |---|---|
> | UI de Postiz | `WEB` |
> | Este pipeline (API pública) | `API` |
>
> **La retirada sólo toca `API`.** Comprobado: con el post de prueba reclamado, la pasada devuelve «nada que hacer» y el post `WEB` sigue intacto; al vaciar `Status`, se lleva el de la API —y su comentario— y sigue sin tocar el `WEB`.

> ### ⚠️ El endpoint no filtra por estado
> `posts.repository.ts:129-172` **no filtra por `state`**: devuelve también `PUBLISHED`, `ERROR` y `DRAFT`. Y con `intervalInDays` no nulo puede devolver posts **fuera de la ventana** (`:152-157`).
>
> Si la retirada borrase todo lo que no reconoce, **borraría posts ya publicados**. El filtro por estado lo tiene que hacer n8n.

El emparejamiento es por `❌ postiz_post_id` mientras no exista `externalId`; en cuanto exista, es directo y no depende de que Notion conserve el ID.

> Aplica el mismo margen de seguridad de §9.3: nada dentro de las próximas 2 horas se retira automáticamente.

### 9.8 El cuerpo exacto de `POST /public/v1/posts`

**Contrastado contra la API real**, no sólo derivado de los DTOs.

Ejemplo de la forma exacta del cuerpo, para una de las tres cuentas. *(La fecha aquí es ilustrativa; la del ensayo de punta a punta fue `2027-01-15T10:00:00+01:00`, más abajo.)*

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
> Confirmado ejecutándolo: el post y su comentario quedaron correctamente soft-deleted, y aun así la respuesta fue `{"error":true}` con 200. `posts.service.ts:683` devuelve eso siempre.
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

## 10. Qué queda por delante

Lo construido, y dónde vive cada pieza, está en §14. Aquí sólo lo que **todavía no se ha hecho**.

### 10.1 El filtro que sigue sin pasarse: ¿aguanta la cola?

El plan original ponía una condición antes de automatizar nada: **llenar la cola a mano durante dos semanas**, publicando desde Postiz, sin n8n. No para probar Notion —el calendario lleva tiempo en uso— sino para probar **la disciplina que exige la cola**: una fila por post, hora obligatoria, elegir `cuenta` y `colaboradores`, marcar `Listo`.

**Ese filtro se saltó.** El esquema y el worker se montaron sin esperar, porque montarlos destapaba defectos del fork que había que arreglar igualmente. La consecuencia es que el sistema está listo pero la pregunta sigue abierta.

Lo que revelarían esas dos semanas, y sigue sin saberse:

- Si el modelo de colaboradores encaja con cómo se publica de verdad, o si acaban desdoblándose filas más de lo previsto.
- Cuántos carruseles y stories compartidos hay — son los que **no** admiten colaboradores (§7.2.4) y obligan a filas separadas.
- Qué campos sobran y cuáles faltan, antes de que el worker se acople más al esquema.

> Si a las dos semanas de uso real la cola está a medias, **el problema no lo arregla el sync**. Automatizar una tabla que nadie llena sólo añade una pieza que mantener.

### 10.2 La capa creativa — el motivo de todo esto

- Redacción de borradores con Claude vía **Notion MCP**, creando filas con el copy ya escrito y `Status` vacío, listas para revisar.
- Sistema de captura de materia prima: ideas, objeciones reales de clientes, ángulos.

> **No necesita que se construya nada antes**, y es la única razón por la que el resto merece la pena. Si el copy se va a escribir a mano igualmente, el proyecto entero es una UI peor para algo que Postiz ya hace.

### 10.3 El archivo en Drive, a medias

Dejó de ser trabajo hipotético: el destino, la cuenta y el origen de los bytes están decididos y verificados contra Drive. Falta lo que escribe de verdad —el espejo nocturno y el archivador curado con su enlace de vuelta a Notion—. Todo el detalle en [PLAN_ARCHIVO_DRIVE.md](./PLAN_ARCHIVO_DRIVE.md); aquí sólo importa que **no toca el camino de publicación** y que hasta que exista, la única red del material publicado es la retención larga de §4.7.

---

## 11. Decisiones abiertas

**Pendientes:**

| # | Decisión | Bloquea | Notas |
|---|---|---|---|
| 1 | ~~Formato y zona horaria~~ | — | **Resuelta:** offset explícito, contenedor en UTC (§9.8) |
| ~~2~~ | ~~Tope de tamaño~~ | — | **Resuelta, y el tope dejó de ser un problema.** No son 300 MB sino **1 GiB** (`MAX_URL_UPLOAD_BYTES`), y ya no protege memoria —el streaming la hace constante— sino el disco (§9.2). Probado con 672 MB |
| ~~3~~ | ~~¿`URL` libre?~~ | — | **No.** Creada propiedad `❌ release_url` aparte |
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
| Estructura en Notion | **Una sola tabla** — el calendario existente, con 11 propiedades más (§7.2) |
| IDs de integración | Los tres, verificados en la base de datos (§7.2.1) |
| Piezas compartidas entre cuentas | **Un post con `collaborators`**, no N posts (§7.2.4) |
| Estado del pipeline | Propiedad `Status`, única — antes eran dos y se fusionaron (§7.2) |
| Alertas | **Email al creador de la fila** (`created_by`), con dirección general de reserva `contacto@dustincalderon.com` — *diseño decidido; **sin implementar**: falta elegir remitente (§10)* |
| Archivo en Drive | **En marcha.** Ya no es «para después»: destino, cuenta y origen de los bytes están decididos y verificados; falta el script del espejo y el archivador curado. Sigue fuera del camino de publicación → [PLAN_ARCHIVO_DRIVE.md](./PLAN_ARCHIVO_DRIVE.md) |
| Retención de la caché de medios | **`MEDIA_RETENTION_DAYS = 3650`**, aplicado y verificado. El default de 30 sólo era seguro para el material con fila en Notion (§4.7) |
| Plan de Notion | **De pago** → el botón webhook es viable |
| Margen de seguridad | **2 h** (§9.3) |
| Ventana | **15 días** (§9.9) |
| Hora del cron | **06:00 Europe/Madrid** (§9.1) |

> **Ninguna de las dos abiertas bloquea el uso diario.** La #5 sólo importa el día que Notion esté caído a las 06:00; la #7 es una incógnita que se despejará sola en la primera publicación con colaboradores.

## 12. Riesgos

### El tamaño de los ficheros no es un riesgo *para Postiz*, pero sí para publicar

La mitad conocida está cerrada, y por cambio de arquitectura en vez de por mitigación: con `upload-from-url` los bytes van de Notion a Postiz directamente —n8n sólo manda una URL— y Postiz los **streamea a disco** con memoria constante (§9.2). Lo único que queda por ahí es `MAX_URL_UPLOAD_BYTES` = **1 GiB**, y su motivo es el **disco, no la RAM**: Notion admite ficheros de hasta 5 GiB y no queremos que uno llene el Seagate por error.

> ### ⚠️ Corrección: una versión previa daba esto por cerrado del todo
>
> Decía que el tamaño «ya no es un riesgo» porque a Postiz le da igual. Eso mide al consumidor equivocado: **quien tiene que descargarse el fichero es Meta**, del Beelink y por el túnel, y ahí el tamaño manda.
>
> El **2026-08-06** dos Trial Reels de **2160×3840 a 38 Mbps → 585 MB** no se publicaron nunca. Meta no terminó de descargarlos, el contenedor se quedó en `IN_PROGRESS`, saltó el `startToCloseTimeout` de 10 min de la actividad, Temporal reintentó 3 veces **volviendo a servir los 585 MB** y eso agotó el rate limit de la app. Firma en la tabla `Errors`: `activity StartToClose timeout`. Un clip de **1080×1920 a 8 Mbps (18 MB)** del mismo día publicó sin problema y acumuló 2.250 visualizaciones.
>
> Así que la frase «los reels pesan 150-250 MB» tampoco es una tranquilidad: es ya la zona incómoda. **Lo publicable es ≤1080×1920 y ≲12 Mbps** — Instagram admite hasta 25 Mbps y 1 GiB, pero eso es lo que *acepta*, no lo que nuestro uplink *entrega a tiempo*.

**Dónde está resuelto y dónde no.** El pipeline de clips lo cierra en su Paso 5: mide el clip con `ffprobe` antes de subirlo y lo recodifica a 1080×1920 / 8 Mbps si se sale (Opus renderiza a la resolución de la fuente y su API no deja elegirla).

**El camino de Notion no tiene esa red.** Un vídeo en 4K adjuntado en una fila se sube tal cual y morirá igual. Si algún día pasa, el sitio donde va la comprobación es §7.4, junto al resto de validaciones previas al envío. Hoy es un hueco conocido y asumido, no un descuido.

### ⚠️ El Seagate es USB y `/uploads` es un bind mount

Si `/mnt/seagate` se desmonta, Docker sirve el bind desde un directorio vacío del disco de sistema: **toda la biblioteca de medios desaparece en caliente** —404 en cada imagen— y las subidas nuevas llenan el disco del Beelink en silencio.

Es el mismo riesgo que en su día justificó descartar los watchers (§13), sólo que aquí ya existe y no lo introduce este proyecto. Merece una comprobación de montaje en el arranque, pero es trabajo de infraestructura, no de este pipeline.

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
| ~~Subir `MEDIA_RETENTION_DAYS`~~ | **Revertido.** Se dio por innecesario asumiendo que todo lo publicado tenía máster en Notion; los 18 posts anteriores al pipeline no lo tienen, y su única copia se estaba purgando. Subida a **3650** el 2026-08-04 (§4.7). |
| MinIO o cualquier S3 propio | Imposible: el endpoint de R2 está hardcodeado (§4.2). |
| ~~Evitar `upload-from-url`~~ | **Revertido.** Se usaba multipart "por decisión de arquitectura"; esa decisión era errónea. El multipart choca con el límite de 100 MB del Cloudflare Tunnel y ningún reel real pasa (§9.2). `upload-from-url` es ahora el camino: menos viajes, sin tope de túnel y sin bytes por n8n. |
| **Modelo de cola** (procesar una vez y congelar) | Sustituido por reconciliación (§9). La cola no propagaba las ediciones: se editaba el copy en Notion y no pasaba nada. |
| ~~Eliminar el polling del todo~~ | **Revertido por la auditoría.** La entrega del webhook es best-effort y sin reintento (§4.4.1): el cron mantiene una pasada de recuperación (§9.4). |
| `type: 'update'` de Postiz | Delete+create tiene semántica inequívoca y es seguro (§4.8). No hace falta averiguar qué actualiza exactamente un `update`. |
| Añadir aprobación o campañas **a Postiz** | Es reconstruir Notion, peor y con código. Rompería además la regla de que Postiz sea sustituible (§2). |
| Hacer configurable el endpoint de S3 | `local` funciona y R2 queda como salida de emergencia. Hoy sería código sin usuario. |
| **Mover los medios a R2** | Se probó y se revirtió: el 403 que lo motivaba era el bloqueo de crawlers de IA de Cloudflare, no una limitación real. Meta obtiene 200 desde `local` . |
| Derivar el margen de seguridad del horario del cron | Falso sentido de seguridad: el botón dispara a cualquier hora (§9.3). |

## 14. Inventario de lo implementado

> **Tres cuartas partes de esto no viven en git** — conviene saber dónde mirar antes de auditar.

### 14.1 En el repositorio · `custom/postiz-dc`

| Qué | Dónde |
|---|---|
| `post.workflow.v1.0.6.ts` | `apps/orchestrator/src/workflows/post-workflows/` |
| Export de la versión | `apps/orchestrator/src/workflows/index.ts` |
| Arranque de `postWorkflowV106` | `posts.service.ts:729` |
| `releaseId` + `error` en el payload del webhook | `posts.repository.ts` → `getPostByForWebhookId` |
| Webhook en los 5 caminos previos al bucle | `post.workflow.v1.0.6.ts` |
| **`DELETE /public/v1/media/:id`** | `public.integrations.controller.ts` |
| **`upload-from-url` por streaming** | `public.integrations.controller.ts` + `local.storage.ts` (`uploadStream`) + `upload.interface.ts` |
| Este documento | `docs/architecture/` |

**Cómo se despliega:** commit y push a `origin/custom/postiz-dc`, `git pull` en `/opt/repos/postiz-fork`, `bash /opt/homeserver/postiz/build.sh` y `docker compose -f /opt/homeserver/postiz/docker-compose.yml up -d postiz`.

> ### ⚠️ Tocar un `post.workflow.vX` con ejecuciones en vuelo rompe los replays
> Temporal reproduce el historial de una ejecución contra la definición actual del workflow. Por eso la convención del proyecto es **un fichero por versión**, y por eso `V105` sigue exportada aunque ya no se arranque.
>
> Editar una versión existente **sólo es seguro si no hay ninguna ejecución suya corriendo** — se comprueba en Temporal antes de tocarla. Un post programado mantiene su workflow vivo desde que se crea hasta que publica, así que puede haber ejecuciones en vuelo durante semanas.
>
> Editar un post desde la UI reinicia su workflow (`posts.service.ts:729`), y entonces pasa a arrancar con la versión actual.

### 14.2 En Notion · `collection://186a2405-a123-81dc-832f-000b82a65c0c`

**11 propiedades nuevas** (§7.2), verificadas contra la API: `cuenta`, `colaboradores`, `copy`, `media`, `first_comment`, `modo`, `Status`, `❌ postiz_post_id`, `❌ postiz_media`, `❌ error_log`, `❌ release_url`. Tipos y opciones correctos.

> ### ⚠️ Las descripciones de propiedad no se pueden escribir por API — y se borran solas
> Comprobado ejecutándolo contra Notion:
>
> - `PATCH /v1/databases` **rechaza** cualquier cuerpo que incluya `description` en una propiedad (400, en `2022-06-28` y en `2025-09-03`, y también en `/v1/data_sources`).
> - Un `PATCH` que reenvía el **tipo** de la propiedad —aunque mande las opciones con sus mismos `id`— **deja la descripción vacía**.
>
> Es decir: son de sólo lectura por API y **frágiles ante cualquier cambio de esquema automatizado**. Así se perdieron las de `colaboradores` y `modo`; hay que reponerlas a mano en la UI.
>
> **Antes de tocar el esquema con un script, apunta las descripciones**: no hay forma de restaurarlas programáticamente.

**1 propiedad de tipo botón:** `Sync now` → *Enviar webhook* (§9.1). Sólo se puede crear desde la UI.

**2 vistas nuevas**, sobre las 5 que el calendario ya tenía:

| Vista | Tipo | Filtro | Orden |
|---|---|---|---|
| `IG · Publicación` | tabla | `Plataforma` contiene `Instagram` | `Fecha` ascendente |
| `⚠️ Averías` | tabla | `Status` es `Error` | `Fecha` ascendente |

`IG · Publicación` muestra las columnas del pipeline (`cuenta`, `Tipo`, `Status`, `modo`, `copy`, `media`, `colaboradores`, `first_comment`, `❌ error_log`); `⚠️ Averías` se queda con lo que hace falta para diagnosticar: `cuenta`, `❌ error_log` y `❌ postiz_post_id`.

**1 cambio del usuario:** `Fecha` pasó de *Formato de hora: Oculto* a **24 horas** (`time_format: "H:mm"`).

> Todo lo de esta sección está verificado contra Notion. Las vistas y el botón no los expone la API REST, pero sí el conector de Notion —`fetch` sobre la base devuelve `<views>` y el esquema con `"Sync now": {"type": "button"}`—, así que aquí no queda nada dado por bueno de palabra.

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
| `POST /webhook/postiz-sync-ig` | `X-Sync-Token` | Sync a demanda (scripts, curl) |
| `POST /webhook/postiz-sync-<secreto>` | **el secreto va en la ruta** | El botón `Sync now` de Notion (§9.1) |
| `POST /webhook/postiz-retirada-ig` | `X-Sync-Token` | Retirada/recuperación a demanda |
| `POST /webhook/postiz-status-<secreto>` | **el secreto va en la ruta** | Destino del webhook de Postiz |

Los secretos de ruta viven en `/opt/homeserver/.env` como `N8N_SYNC_IG_BUTTON_PATH` y `N8N_POSTIZ_WEBHOOK_PATH`.

> ### Por qué el receptor lleva el secreto en la URL y no en una cabecera
> `post.activity.ts:329-335` manda el webhook con **una sola cabecera**, `Content-Type`. No hay firma, ni HMAC, ni campo de secreto en el modelo `Webhooks` (id, name, url, organizationId). Con un emisor que no puede autenticarse, meter el secreto en la ruta es la única opción; sobre HTTPS la ruta no viaja en claro. El valor está en `/opt/homeserver/.env` como `N8N_POSTIZ_WEBHOOK_PATH`.

**Copia durable:** los cuatro workflows están exportados en `/opt/homeserver/n8n-workflows/postiz-<id>.json` (modo `600`). **No van a este repositorio**: el receptor lleva su ruta secreta dentro, y esto es un fork de un proyecto público (§14.4).

> ### La batería de pruebas — `/opt/homeserver/n8n-workflows/suite-pruebas-postiz.py`
>
> **34 comprobaciones contra producción sin publicar nada en Instagram.** Se ejecuta con el entorno del servidor cargado:
>
> ```
> set -a; . /opt/homeserver/.env; set +a; python3 /opt/homeserver/n8n-workflows/suite-pruebas-postiz.py
> ```
>
> **Desde el 2026-08-05 está versionada** en `docs/architecture/scripts/`, junto con `prueba-trial-reels.py`. Vivían sólo en el servidor con permisos `600` y sin respaldo — la red de seguridad del pipeline estaba a una reinstalación de perderse. Se aplica la misma regla que a los scripts de Drive: **si se toca una copia hay que actualizar la otra**, y se comparan con `md5sum`. Sí van al repositorio, al contrario que los JSON de n8n: leen los cuatro valores sensibles de `os.environ` y no llevan ninguna ruta secreta dentro.
>
> Al cargar el `.env` verás `line 103: {client_id:: command not found`. **Es inocuo y no hace falta arreglarlo**: `GOOGLE_API_CREDENTIALS` es un JSON sin comillas, así que el shell lo parte en el primer espacio y esa variable queda vacía. Cargan las otras 54, ninguna la usa el pipeline, y el consumidor real (`calcom`) la recibe entera porque docker-compose no usa semántica de shell. Ponerle comillas arreglaría el aviso y podría romper `calcom`.
>
> Cubre: seguridad de los tres disparadores, las cuatro validaciones que deben acabar en `Error` **con el motivo nombrando la propiedad tal y como se llama hoy**, el camino completo de un carrusel, la regresión del margen (§9.3), el reintento que reutiliza los medios, la retirada, el estado en reposo y la limpieza de sus propios ficheros.
>
> Tres cosas que hay que respetar al tocarla, porque las tres ya dieron un resultado falso:
>
> - **`User-Agent` obligatorio.** Cloudflare bloquea `Python-urllib` en este dominio (§4.1) y devuelve `403` sin que la petición llegue a n8n. Los checks que *esperan* `403` entonces **pasan por el motivo equivocado** — por eso ahora comprueban además que el cuerpo sea de n8n y no una página de Cloudflare.
> - **Fechas relativas a hoy, nunca fijas.** Una fecha escrita a mano se sale de la ventana de 15 días con el tiempo y el sync la ignora con razón; se lee como una avería del pipeline.
> - **La fila del margen usa `modo = borrador` a propósito.** Su fecha cae dentro de 40 minutos: en `programar` saldría publicada de verdad si la limpieza fallara. El margen se evalúa en `Planificar`, antes de que `modo` importe, así que la regresión se prueba igual con riesgo cero.

> **Convención: todo va por `httpRequest`, no por nodos de integración.** Ningún workflow de esta instancia usa el nodo de Notion; se llama a la API directamente. Conviene mantenerlo — un nodo de tercero añade una dependencia que se actualiza sola y puede cambiar de comportamiento bajo los pies.

**Por qué la retirada es un workflow aparte y va 20 minutos después.** Es la parte destructiva. Encadenarla al sync obliga a razonar sobre qué pasa cuando no hay filas que crear (los nodos sin items no se ejecutan, y la retirada no correría nunca justo el día que más falta hace). Separada, siempre corre, y el desfase garantiza que el sync ya ha escrito los `❌ postiz_post_id` que ella va a leer.

### 14.4 En producción, fuera de todo lo anterior

| Fichero | Cambio |
|---|---|
| `/opt/homeserver/postiz.env` | `API_LIMIT` 30 → **300**; `CLOUDFLARE_BUCKET_URL` sin barra final. Copia: `postiz.env.bak-20260803` |
| `/opt/homeserver/.env` | **`N8N_SYNC_IG_TOKEN`** añadido — el token del webhook (§9.1) |
| `/opt/homeserver/.env` | **`NOTION_API_KEY`** añadido — copia durable del token de Notion |
| `/opt/homeserver/.env` | **`N8N_POSTIZ_WEBHOOK_PATH`** añadido — ruta secreta del receptor (§14.3) |
| `/opt/homeserver/.env` | **`N8N_SYNC_IG_BUTTON_PATH`** añadido — ruta secreta del botón de Notion |
| `/opt/homeserver/postiz/postiz.env` | **`MAX_URL_UPLOAD_BYTES=1073741824`** añadido — 1 GiB (§9.2) |
| `/opt/homeserver/postiz/postiz.env` | **`MEDIA_RETENTION_DAYS=3650`** añadido (§4.7). Copia: `postiz.env.bak-20260804-retention`. **No basta con reiniciar el contenedor**: hubo que terminar y relanzar el workflow en Temporal — ver [MEDIA_CLEANUP_PIPELINE.md](./MEDIA_CLEANUP_PIPELINE.md) |
| Google Drive | Remoto rclone **`gdrive-work`** (cuenta de Workspace) + dos carpetas destino, verificadas con escritura real → [PLAN_ARCHIVO_DRIVE.md](./PLAN_ARCHIVO_DRIVE.md) |

Todos verificados presentes. `API_LIMIT=300`, `STORAGE_PROVIDER=local`, `TZ` vacío y `CLOUDFLARE_BUCKET_URL` sin barra final, también.

> ### 🔑 Dónde vive cada secreto, y por qué no en este repo
> El token de Notion estaba **sólo** en `#ARCHIVE/Motion_to_Notion/.env`, un repo muerto. Ahora vive en dos sitios durables:
>
> 1. **Credencial de n8n** `5rCv9a6s5FyI0swq` — cifrada, es la que usa el worker.
> 2. **`/opt/homeserver/.env`** — junto al resto de secretos del servidor, que es la convención del HomeLab.
>
> **Ya se puede borrar `#ARCHIVE/Motion_to_Notion` sin perder nada.**
>
> **Nunca en este repositorio.** Es un fork de un proyecto público: basta un push al remoto equivocado para filtrar el token. Los secretos van al `.env` del servidor o al gestor de credenciales de la herramienta que los usa — jamás a git, ni siquiera en un repo privado.

### 14.5 Límites conocidos

Lo que el sistema **no** cubre hoy, para que nadie lo descubra a base de sorpresa:

| Límite | Consecuencia |
|---|---|
| **Colaboradores en `graph.instagram.com`** | Se envían, pero no está comprobado que Meta los acepte en la API de Instagram Login. Deuda aceptada (§11, decisión #7) |
| **Más de 100 filas accionables** | Ninguna de las dos consultas a Notion pagina. **Fallan a las claras** si `has_more` es `true`, en vez de sincronizar media cola en silencio. Con el filtro por estados vivos, hoy el margen es enorme |
| **Subida parcial de un carrusel** | Si el asset 1 sube y el 2 falla, el primero queda huérfano. Raro, y arreglarlo obliga a arrastrar estado a medias por el subflow |
| **Notion caído a la hora del cron** | No hay reintento ni alerta distinta. Decisión abierta (§11) |

> **Los medios de un post fallido sí se limpian.** El subflow borra lo que acaba de subir si el `POST /posts` falla (§9.2) — el huérfano permanente sólo aparece en el caso parcial de arriba.


### 14.6 El webhook de Postiz — cómo está configurado

**Se da de alta a mano en la UI de Postiz**, que es la única vía: `POST /webhooks` vive en la API con sesión (`webhooks.controller.ts`), no en la pública, y con la API key devuelve `401`.

| Campo | Valor |
|---|---|
| Nombre | `n8n sync Instagram` |
| URL | `https://auto.dustincalderon.com/webhook/` + `N8N_POSTIZ_WEBHOOK_PATH` |
| Integraciones | las 4 conectadas: las 3 de Instagram y el TikTok |

> ### ⚠️ Elegir integraciones concretas es una trampa a futuro
> El filtro de `sendWebhooks` (`post.activity.ts:316-323`) es `f.integrations.length === 0 || f.integrations.some(...)`. Con integraciones concretas **sólo entrega cuando el `integrationId` coincide**.
>
> Hoy están marcadas las cuatro que existen. **El día que se conecte una quinta cuenta habrá que añadirla aquí a mano, o sus avisos no llegarán y no lo dirá nadie.** Con la opción «todas las integraciones» eso no pasa; merece la pena cambiarlo la próxima vez que se conecte una cuenta.
>
> Dos de los cinco caminos previos al bucle («No Post») no conocen la integración y pasan `''`, así que no entregan. No se pierde nada: ahí el post no existe y el cuerpo sería `[]` igualmente.
>
> Que TikTok esté incluido es inocuo: el receptor busca en Notion una fila que reclame el post y, al no encontrarla, lo ignora sin escribir.

> ### 🔑 No rotar la API key sin avisar a n8n
> El botón *Rotate Key* de *Settings → Developers* invalida la clave que usa la credencial `h6bGMcfTHiZUD0dy`. Rompería **los cuatro workflows a la vez** y en silencio: no se notaría hasta la pasada de las 06:00. Si se rota, hay que actualizar la credencial de n8n el mismo día.
>
> El resto de esa pantalla —CLI, skill del agente, MCP de Postiz, nodo comunitario de n8n— **no se usa a propósito**: todo eso publica *directamente en Postiz*, saltándose Notion, que es justo lo que prohíbe §6. La capa creativa (§10.2) usa el **MCP de Notion**, no el de Postiz.

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
