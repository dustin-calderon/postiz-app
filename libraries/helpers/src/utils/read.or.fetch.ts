import { readFileSync } from 'fs';
import { getSsrfSafeAxios } from '@gitroom/nestjs-libraries/dtos/webhooks/ssrf.safe.dispatcher';

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

  return readFileSync(path);
};
