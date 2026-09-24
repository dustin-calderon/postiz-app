# Pipeline de contenido — reconciliación: sin duplicados, sin huérfanos

> **Qué es esto:** lo que mantiene Postiz y Notion de acuerdo después de crear — el cierre del bucle cuando Postiz publica o falla, por qué se borra y recrea en vez de actualizar, la identidad externa que hace imposible el duplicado y la pasada que retira lo que ya no debe existir.
> Cómo se crea cada post está en [CONTENT_PIPELINE_SYNC.md](./CONTENT_PIPELINE_SYNC.md).
>
> **Parte de:** [CONTENT_PIPELINE_NOTION_POSTIZ.md](./CONTENT_PIPELINE_NOTION_POSTIZ.md), que tiene el mapa de todos los documentos del pipeline.

---

## 1. Cierre del bucle: reactivo, con red

Todo camino terminal del workflow de Postiz emite webhook ([POSTIZ_FORK §4](./CONTENT_PIPELINE_POSTIZ_FORK.md)), así que **publicado y fallido llegan por el mismo canal**:

```
Postiz publica (o falla) ──webhook──► n8n ──► Status = Publicado | Error
                                              ❌ release_url = permalink   (si publicó)
                                              ❌ error_log   = motivo      (si falló)
```

> Es la propiedad `Status` de Notion — no confundir con el `state` interno de Postiz, que es otra cosa y usa otros valores (`QUEUE`, `PUBLISHED`, `ERROR`).

n8n **no mira el `state`**: mira `releaseURL`/`releaseId`. Si vienen con valor, el post está en Instagram aunque el `state` diga `ERROR` ([POSTIZ_FORK §4.3](./CONTENT_PIPELINE_POSTIZ_FORK.md)). Sólo si vienen vacíos y el `state` es `ERROR` la fila va a `Error`. Cualquier otra cosa se ignora sin escribir nada. El receptor busca la fila que reclama el post; si no la hay (un post de la UI, el TikTok), lo ignora sin escribir.

> ### ⚠️ El webhook es el camino rápido, no el único
> La entrega es best-effort y sin reintento ([POSTIZ_FORK §4.2](./CONTENT_PIPELINE_POSTIZ_FORK.md)): si n8n está caído cuando Postiz publica, ese aviso **se pierde para siempre**.
>
> Por eso la retirada (§4) hace además una **pasada de recuperación**: para toda fila viva (`Listo`, `Programado` o `En Postiz (borrador)`) con post, `modo` distinto de `borrador` y la `Fecha` pasada hace más de 30 minutos, consulta el estado real en Postiz y corrige: `Publicado` con su enlace si salió; `Error` con su motivo si falló, si Postiz ya no tiene el post o si seguía como borrador porque se aprobó tarde. Es barato —va incluido en el `GET` que ya hace la retirada— y es lo único que evita que una fila con la fecha pasada se quede como estaba para siempre: el sync ya no la toca porque tiene post.

> **`❌ release_url` sólo puede venir de aquí.** `createPost` devuelve únicamente `[{postId, integration, alreadyClaimed}]` (`posts.service.ts`); el permalink no existe hasta que el post sale de verdad, y lo escribe `updatePost` en el workflow. Sin el webhook o la recuperación, ese campo se queda vacío para siempre.

Cómo está dado de alta el webhook en Postiz: [OPERACION §5](../guides/CONTENT_PIPELINE_OPERACION.md).

## 2. Por qué borrar y recrear, y no actualizar

Semántica inequívoca: el resultado es el estado correcto sin importar qué cambió. No hace falta averiguar qué actualiza exactamente un `type: 'update'` de Postiz. Cuesta dos llamadas en vez de una, irrelevante frente al techo de `API_LIMIT` ([POSTIZ_FORK §3](./CONTENT_PIPELINE_POSTIZ_FORK.md)).

Es seguro porque `deletePost` termina el workflow de Temporal asociado ([POSTIZ_FORK §8](./CONTENT_PIPELINE_POSTIZ_FORK.md)).

Y **no pone en riesgo los assets** — pero por una razón distinta a la que parece:

- El **Step 2** de la limpieza cuenta los posts soft-deleted como prueba de uso, y eso **convierte el media en candidato a borrado**, no lo protege (`findStalePublishedMedia` de `media.repository.ts`; el comentario del propio código lo dice).
- Quien **protege** es el **Step 3** (`findStalePublishedMedia` de `media.repository.ts`), que exige `p."deletedAt" IS NULL`.

Un post recreado está vivo y sin borrar, luego protege sus ficheros. La conclusión se sostiene; **el razonamiento intuitivo es el contrario del que aplica el código**, y conviene tenerlo escrito para no equivocarse en el próximo cambio.

> **Consecuencia a saber:** `❌ postiz_post_id` cambia en cada resincronización. Es "el post actual en Postiz", no un identificador estable en el tiempo. n8n lo reescribe cada vez, así que Notion siempre tiene el vigente.
>
> **El identificador estable es el otro:** cada post lleva dentro el `externalId` de su fila (§3). Ése no cambia nunca, y es el que hay que usar para emparejar. `❌ postiz_post_id` es una comodidad de lectura, no el vínculo del que depende la corrección.

## 3. La identidad externa — por qué el duplicado no es posible

Si el único vínculo entre la fila y su post fuera `❌ postiz_post_id`, viviría **fuera de Postiz** y se escribiría **después**, en una segunda llamada. Con eso el duplicado es improbable, no imposible: dos disparos del botón que se solapan —Notion lanza la automatización una vez por cada fila tocada— leen el mismo `❌ postiz_post_id`, los dos borran, los dos crean, y la última escritura en Notion pisa a la otra. Resultado: posts vivos que ninguna fila reclama, es decir publicaciones duplicadas.

| Si… | Con el vínculo sólo en Notion | Con `externalId` |
|---|---|---|
| dos pasadas se cruzan | duplicado | la segunda adopta el post de la primera |
| la escritura de vuelta se pisa | huérfano vivo | irrelevante: el post ya sabe de quién es |
| el flujo muere entre el `POST` y el write-back | huérfano *y* fila apuntando a nada | la siguiente pasada adopta el post existente |
| la retirada corre mientras el sync crea | borra un post legítimo | lo reclama por identidad (§4) |

`Post.externalId` mueve ese vínculo **dentro del post**, donde se graba de forma atómica con él. Crear es idempotente: una segunda creación con la misma identidad **devuelve la que ya existe** en vez de acuñar otra. No hay ventana que proteger porque no hay dos pasos.

n8n manda `posts[0].externalId = <id de la página de Notion>` ([API_POSTIZ §3](../reference/CONTENT_PIPELINE_API_POSTIZ.md)). Nada más.

> ### Por qué un cerrojo de transacción y no un índice único
> Un índice único por organización **no sirve aquí:** el borrado en Postiz es **blando** y ocurre en tres sitios distintos —borrado explícito, la sustitución de grupo al editar desde la UI, y el borrado de un canal—. Un índice único total obligaría a liberar la clave en los tres, y en los que añada upstream mañana; **olvidar uno no daría un duplicado: impediría crear**, que es peor que el fallo que se arregla.
>
> Se usa `pg_advisory_xact_lock` sobre `hash(organización + externalId)` **dentro de la misma transacción que la creación**. Mantiene la invariante donde se acuña la identidad, se libera sola al cerrar la transacción pase lo que pase, y no depende de qué conexión del pool sirvió la petición —un cerrojo de sesión sí dependería, y podría quedarse colgado sin que nadie pudiera abrirlo—.
>
> Hay además una razón de despliegue: el esquema se sincroniza con `prisma db push`, no con migraciones. Un índice parcial escrito en SQL crudo **lo borraría el siguiente despliegue, en silencio**.

> ### ⚠️ `alreadyClaimed` no es cosmético
> La respuesta de `POST /posts` trae `alreadyClaimed` por post. El servicio **debe** mirarlo: si lanzara el workflow de publicación para un post que ya tiene el suyo, el duplicado pasaría del calendario **a Instagram**. De dos peticiones simultáneas, exactamente una lo recibe `true` — la que llegó segunda.

**La batería lo verifica con grupo de control** ([OPERACION §1](../guides/CONTENT_PIPELINE_OPERACION.md)): dos creaciones realmente solapadas con la misma identidad dejan **un** post y devuelven el mismo `postId`; las mismas dos sin identidad dejan **dos**. Sin ese control, «cero duplicados» podría significar «no se creó nada».

## 4. La pasada de retirada — sin ella el sync sólo sabe añadir

**Reconciliar no es sólo crear lo que falta: es también retirar lo que ya no debe existir.**

El subflow itera sobre las filas de Notion. Todo lo que desaparece de esa lista se vuelve invisible para él — y el post correspondiente **se queda programado en Postiz y se publica igual**. Tres formas de provocarlo, todas normales:

| Acción en Notion | Sin pasada de retirada |
|---|---|
| Se borra la fila | El post se publica igualmente |
| `Status` vuelve de `Listo` a vacío | El post se publica igualmente |
| La `Fecha` se mueve a más de 15 días | Se publica en la fecha vieja |

El segundo es el más traicionero: alguien retira un post para repensarlo, y sin retirada sale publicado.

**La pasada:** pedir a Postiz lo que tiene programado en la ventana y **borrar todo lo que no tenga detrás una fila que lo quiera**.

```
GET /public/v1/posts?startDate=...&endDate=...   ← existe: GetPostsDto
   └─ FILTRAR por state en el propio n8n           ← ver aviso
   └─ FILTRAR por creationMethod === 'API'         ← ver aviso rojo
   └─ para cada post aún no publicado en la ventana:
        ¿alguna fila de Notion lo reclama?
          (cualquier Status puesto, Publicado y Error incluidos,
           salvo una fila viva cuya Fecha está a más de 15 días)
          no ──► DELETE /public/v1/posts/:id
                 y si su fila estaba en Programado o En Postiz ──► Listo
```

**Cuándo corre.** Es un workflow aparte, `Retirada y recuperación (IG)` ([INVENTARIO §1](../reference/CONTENT_PIPELINE_INVENTARIO.md)). El sync lo llama **una vez por pasada, antes de crear** (cron y botón): así aplazar una pieza o vaciar su `Status` y pulsar `Sync now` la retira en el acto. Y corre solo a las **06:20**, 20 minutos después del cron del sync, cuando éste ya ha escrito los `❌ postiz_post_id` que ella va a leer. Separado del camino de creación corre siempre, también el día que no hay filas que crear (en n8n los nodos sin items no se ejecutan).

> ### 🔴 Sin filtrar por `creationMethod`, la retirada borra el trabajo hecho a mano
> Un post creado desde la UI de Postiz **no tiene fila en Notion**, así que "todo lo que no tenga una fila viva detrás" lo incluye. `GET /posts` expone `creationMethod`, y los valores separan limpiamente los dos orígenes:
>
> | Origen | `creationMethod` |
> |---|---|
> | UI de Postiz | `WEB` |
> | Este pipeline (API pública) | `API` |
>
> **La retirada sólo toca `API`.**

> ### ⚠️ El endpoint no filtra por estado
> `getPosts` de `posts.repository.ts` **no filtra por `state`**: devuelve también `PUBLISHED`, `ERROR` y `DRAFT`. Y con `intervalInDays` no nulo puede devolver posts **fuera de la ventana** (la rama `intervalInDays: { not: null }`).
>
> Si la retirada borrase todo lo que no reconoce, **borraría posts ya publicados**. El filtro por estado lo tiene que hacer n8n.

**El emparejamiento es por las dos vías.** Por `❌ postiz_post_id` y **por `externalId`**: `GET /posts` lo devuelve, así que un post recién creado **cuya id aún no se ha escrito en Notion** no parece huérfano —lleva dentro la fila a la que pertenece—. Eso cierra la carrera entre la retirada y un sync que crea, que sin identidad borraría un post legítimo y dejaría la fila apuntando a un id muerto: un fallo **silencioso** (no se publica nada), peor que el duplicado visible. Reclamar por identidad no puede provocar borrados de más: sólo añade motivos para **no** borrar.

> Aplica el mismo margen de seguridad del sync ([SYNC §3](./CONTENT_PIPELINE_SYNC.md)): nada dentro de los próximos 5 minutos se retira automáticamente.

> ### La lista de filas se lee entera o no se retira nada
> Las filas que reclaman crecen sin tope, porque las `Publicado` se quedan. `Notion: filas vivas` pagina (`start_cursor`, hasta 50 páginas de 100) y ordena por `created_time`: sin orden, Notion no garantiza ninguno, y una fila editada entre dos páginas podría no leerse y su post parecería huérfano. `Reconciliar` junta las páginas y **se niega a seguir** si alguna no es una lista o si la última aún dice `has_more`: con una lista a medias borraría posts legítimos.
