# Video Format Support (`.mov` and beyond)

> **SSoT** para cómo el sistema decide "esto es un video". Antes de tocar
> detección de video en cualquier provider o en el frontend, lee esto.

## Problema original

Históricamente Postiz consideraba **video únicamente al `.mp4`**. La detección
estaba hard-codeada en ~20 sitios como `hasExtension(path, 'mp4')` o
`path.indexOf('mp4') > -1`. Consecuencia para cualquier otro contenedor de
video (típicamente `.mov` de dispositivos Apple):

1. **No se podía programar** (síntoma reportado: "no se guarda, no aparece en el
   calendario"). El validador `ValidUrlExtension` del `MediaDto.path` solo
   permitía `.png/.jpg/.jpeg/.gif/.webp/.mp4`. Un `.mov` fallaba la validación
   del DTO → `400 Bad Request` en `POST /posts` → el post nunca se guardaba.
2. Aunque se guardara, el `.mov` se enviaba a las plataformas **como imagen**
   (no matcheaba `mp4`), y en el frontend se renderizaba como `<img>` roto en
   vez de `<video>`.

## Solución: punto único de verdad

Se centralizó la definición de "qué extensiones son video" en un solo lugar:

- **`libraries/helpers/src/utils/has.extension.ts`**
  - `VIDEO_EXTENSIONS = ['mp4', 'mov', 'webm', 'mpeg', 'mpg']`
  - `isVideo(path)` → `true` si el path (tras quitar query-strings de URLs
    firmadas de R2/S3) **termina** en una extensión de video. Usa `endsWith`,
    no `indexOf`, para no dar falsos positivos con rutas tipo `.movies/`.

Todos los sitios de **detección de video** ahora usan `isVideo(path)` en lugar
de comprobar `mp4` a mano. La lista de extensiones válidas de subida
(`valid.url.path.ts`) reutiliza `VIDEO_EXTENSIONS`, así que **mantener ambos en
sync es automático**.

### Invariante clave: "uploadable ⟹ schedulable"

El set canónico (`VIDEO_EXTENSIONS` + las imágenes de `valid.url.path.ts`) debe
coincidir con lo que el **pipeline de subida** acepta por MIME. Si un formato se
puede subir pero no está en el allow-list del DTO, el post da **400 al
programar** (fue justo el bug del `.mov`). Formatos soportados de punta a punta:

| Tipo  | MIME              | Extensión(es) |
|-------|-------------------|---------------|
| Video | `video/mp4`       | `.mp4`        |
| Video | `video/quicktime` | `.mov`        |
| Video | `video/webm`      | `.webm`       |
| Video | `video/mpeg`      | `.mpeg`/`.mpg`|
| Img   | `image/jpeg`      | `.jpg`/`.jpeg`|
| Img   | `image/png`       | `.png`        |
| Img   | `image/gif`       | `.gif`        |
| Img   | `image/webp`      | `.webp`       |
| Img   | `image/avif`      | `.avif`       |
| Img   | `image/bmp`       | `.bmp`        |
| Img   | `image/tiff`      | `.tif`/`.tiff`|

**Allow-lists de subida que deben incluir estos MIME** (se alinearon todas):
`local.storage.ts`, `custom.upload.validation.ts`, `cloudflare.storage.ts`,
`r2.uploader.ts` (mapa ext→mime), `upload.from.url.tool.ts` y
`public.integrations.controller.ts`.

### Qué NO se tocó (a propósito)

- `'Content-Type': 'video/mp4'` en `bluesky.provider.ts` — cabecera de subida
  binaria; es formato-específico, no detección.
- `'upload mp4'` (label de log) en `facebook.provider.ts`.
- MIME allow-lists de subida ya expanden `video/*` a
  `['video/mp4','video/quicktime','video/webm','video/mpeg']`
  (`new.uploader.tsx`) y el API público lista los mismos MIME
  (`public.integrations.controller.ts`).

## Archivos afectados

- **Núcleo**: `has.extension.ts` (helper), `valid.url.path.ts` (DTO allow-list).
- **Frontend**: `video.or.image.tsx`, `media.component.tsx`,
  `media.settings.component.tsx`, `agent.chat.tsx`, `veo3.provider.tsx`,
  `new-launch/editor.tsx` (uploader `video/*`), `new-launch/providers/tiktok`.
- **Backend/providers**: `public.controller.ts` (`/stream`),
  `public.integrations.controller.ts` (MIME), y los providers sociales:
  instagram (+standalone), tiktok, x, threads, vk, mewe, farcaster, gmb,
  youtube, pinterest, reddit, linkedin, dribbble, bluesky, facebook.

## Notas de mantenimiento

- Para soportar un nuevo contenedor de video, **añádelo a `VIDEO_EXTENSIONS`**
  y (si aplica) al MIME allow-list del uploader/API. No vuelvas a comprobar
  `mp4` a mano.
- `linkedin.provider.ts` y `dribbble.provider.ts` tenían variables locales
  llamadas `isVideo`/`isMp4`; se renombraron a `isVideoFile` para no chocar con
  el import del helper.
