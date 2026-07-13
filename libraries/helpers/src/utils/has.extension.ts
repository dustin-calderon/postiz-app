export const hasExtension = (
  path: string | undefined | null,
  extension: string
): boolean => {
  if (!path) {
    return false;
  }
  const ext = extension.startsWith('.') ? extension : `.${extension}`;
  return path.toLowerCase().indexOf(ext.toLowerCase()) > -1;
};

/**
 * Canonical set of video file extensions recognised across the whole system
 * (frontend rendering, DTO validation and every social provider).
 *
 * Historically Postiz treated ONLY `.mp4` as video, so any other container
 * (notably `.mov` from Apple devices) was handled as an image: it failed the
 * media DTO extension allow-list (→ 400 on schedule, post never saved) and,
 * even if saved, was sent to the platforms as an image.
 *
 * This list mirrors the video MIME types the upload pipeline accepts
 * (`video/mp4`, `video/quicktime`, `video/webm`, `video/mpeg` — see
 * `local.storage.ts` / `custom.upload.validation.ts` and the corresponding
 * extensions produced by `file-type`). Keeping detection, the DTO allow-list
 * (`valid.url.path.ts`) and the uploader MIME sets aligned guarantees the
 * invariant "whatever can be uploaded can also be scheduled".
 */
export const VIDEO_EXTENSIONS = ['mp4', 'mov', 'webm', 'mpeg', 'mpg'] as const;

/**
 * Returns true when `path` points at a video file.
 *
 * Matches on the real trailing extension after stripping any query string
 * (R2/S3 signed URLs look like `.../video.mov?X-Amz-...`), so it never
 * false-matches an extension that merely appears mid-path (e.g. a folder named
 * `.movies/`). This is the same semantics as the DTO validator in
 * `valid.url.path.ts`.
 */
export const isVideo = (path: string | undefined | null): boolean => {
  if (!path) {
    return false;
  }
  const clean = path.split('?')[0].toLowerCase();
  return VIDEO_EXTENSIONS.some((ext) => clean.endsWith(`.${ext}`));
};
