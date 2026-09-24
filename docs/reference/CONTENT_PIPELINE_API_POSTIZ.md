# Pipeline de contenido — el contrato con la API pública de Postiz

> **Qué es esto:** el cuerpo exacto que n8n manda a `POST /public/v1/posts`, los campos que dan 400 si se olvidan y lo que responde cada llamada. Contrastado contra la API real, no sólo derivado de los DTOs.
>
> **Parte de:** [CONTENT_PIPELINE_NOTION_POSTIZ.md](../architecture/CONTENT_PIPELINE_NOTION_POSTIZ.md), que tiene el mapa de todos los documentos del pipeline.

---

## 1. El cuerpo de `POST /public/v1/posts`

La forma exacta, para una de las tres cuentas (la fecha es ilustrativa):

```json
{
  "type": "schedule",
  "shortLink": false,
  "date": "2026-08-14T08:00:00+02:00",
  "tags": [],
  "posts": [
    {
      "integration": { "id": "cmqjq77hg0001mw7y2xf6bg86" },
      "externalId": "395a2405-a123-81a8-a44a-c70f9eba783e",
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

De dónde sale cada campo en Notion: [NOTION_SCHEMA §2](../architecture/CONTENT_PIPELINE_NOTION_SCHEMA.md). `value[1]` es el primer comentario ([NOTION_SCHEMA §3](../architecture/CONTENT_PIPELINE_NOTION_SCHEMA.md)).

## 2. Los campos que dan 400 si se olvidan

| Campo | Regla | Nota |
|---|---|---|
| `shortLink` | `@IsDefined() @IsBoolean()` | **No es opcional.** Omitirlo es 400 aunque no uses acortador |
| `tags` | `@IsDefined() @IsArray()` | Debe existir aunque sea `[]` |
| `date` | `@IsDefined() @IsDateString()` | **Con offset explícito** ([NOTION_SCHEMA §5](../architecture/CONTENT_PIPELINE_NOTION_SCHEMA.md)) |
| `settings.__type` | `@IsIn(...)` | **`instagram-standalone`**, no `instagram` |
| `settings.post_type` | `@IsDefined()` | `post` o `story` |
| `value[].image[].id` y `.path` | `@IsDefined()` los dos, en `MediaDto` | Ver abajo |

> **`__type` decide qué provider resuelve.** `createPost` de `posts.service.ts` hace `getSocialIntegration(settings.__type)`. Poner `instagram` en una cuenta `instagram-standalone` resolvería el provider equivocado, con otras validaciones y otro host de Meta ([POSTIZ_FORK §9](../architecture/CONTENT_PIPELINE_POSTIZ_FORK.md)).

> ### `value[].image[]` necesita `id` **y** `path`
> `MediaDto` (`media.dto.ts`) declara los dos campos como `@IsDefined()`:
>
> ```ts
> @IsString() @IsDefined()                          id: string;
> @IsString() @IsDefined()
> @Validate(ValidUrlPath) @Validate(ValidUrlExtension) path: string;
> ```
>
> **Son dos validadores sobre `path`, no uno.** `ValidUrlExtension` (`valid.url.path.ts`) exige además que el path acabe en una extensión de la lista blanca —`png·jpg·jpeg·gif·webp·avif·bmp·tif·tiff` + `mp4·mov·webm·mpeg·mpg`— tras quitar el query string. En la práctica no salta, porque la extensión la deriva `local.storage.ts` del magic-number del fichero; pero es otra forma de recibir un 400.
>
> Mandar sólo la URL devuelve **400**. Por eso `❌ postiz_media` guarda el objeto entero que devuelve la subida (`uploadSimple` de `public.integrations.controller.ts` → `mediaService.saveFile`), no una lista de URLs:
>
> ```json
> [{"id":"…","path":"https://postiz.dustincalderon.com/uploads/…"}]
> ```

## 3. `externalId` — opcional para la API, obligatorio para este pipeline

No da 400 si falta: los posts creados desde la UI no tienen ninguno. Pero **omitirlo desde n8n desactiva la protección contra duplicados** sin dar ningún error ([RECONCILIACION §3](../architecture/CONTENT_PIPELINE_RECONCILIACION.md)), que es la peor forma de romperlo. Va **por post**, no en la raíz del cuerpo: la identidad pertenece al grupo de posts, y una misma fila que algún día publique en tres canales necesitará tres identidades distintas.

Su valor es el **id de la página de Notion**, tal cual lo devuelve la API (con guiones). En el subflow sale de `ctx.page_id`.

## 4. Respuestas reales medidas

| Llamada | Status | Cuerpo |
|---|---|---|
| `POST /upload` (multipart, campo `file`) | **201** | `{id, name, originalName, path, thumbnail, alt}` |
| `POST /posts` | **201** | `[{postId, integration, alreadyClaimed}]` — `alreadyClaimed` en [RECONCILIACION §3](../architecture/CONTENT_PIPELINE_RECONCILIACION.md) |
| `DELETE /posts/:id` | **200** | `{"error":true}` ⚠️ |

> ### ⚠️ `DELETE` devuelve `{"error":true}` aunque funcione
> El post y su comentario quedan correctamente soft-deleted, y aun así la respuesta es `{"error":true}` con 200: `deletePost` de `posts.service.ts` devuelve eso siempre.
>
> **n8n no puede usar el cuerpo como señal de éxito.** Si necesita certeza, tiene que releer el estado; en la práctica basta con no tratar esa respuesta como fallo.

## 5. Lo que no está en la API pública

- **`POST /webhooks`** vive en la API con sesión (`webhooks.controller.ts`); con la API key devuelve `401`. El webhook se da de alta desde la UI ([OPERACION §5](../guides/CONTENT_PIPELINE_OPERACION.md)).
- **`DELETE /public/v1/media/:id`** sí está, pero porque lo añade este fork; y `upload-from-url` va por streaming por un cambio del fork ([POSTIZ_FORK §10](../architecture/CONTENT_PIPELINE_POSTIZ_FORK.md)).
