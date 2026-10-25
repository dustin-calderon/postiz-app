import { readFileSync } from 'fs';
import { resolve, sep } from 'path';
import { getSsrfSafeAxios } from '@gitroom/nestjs-libraries/dtos/webhooks/ssrf.safe.dispatcher';

// Media that isn't a remote url is read from the worker's disk. The stored
// path is user-influenced, so only a file inside UPLOAD_DIRECTORY is ever
// opened: resolve() collapses any `..` segments before the comparison, the
// same check the frontend /api/uploads route makes. Returns null otherwise.
export const localMediaPath = (path: string): string | null => {
  const base = process.env.UPLOAD_DIRECTORY
    ? resolve(process.env.UPLOAD_DIRECTORY)
    : '';
  const filePath = resolve(path);
  return base && filePath.startsWith(base + sep) ? filePath : null;
};

export const readOrFetch = async (path: string) => {
  if (path.indexOf('http') === 0) {
    // media paths come from the post payload: never fetch one unguarded
    return (
      await getSsrfSafeAxios()({
        url: path,
        method: 'GET',
        responseType: 'arraybuffer',
      })
    ).data;
  }

  const filePath = localMediaPath(path);
  if (!filePath) {
    throw new Error('The media for this post is not in the upload directory');
  }

  return readFileSync(filePath);
};
