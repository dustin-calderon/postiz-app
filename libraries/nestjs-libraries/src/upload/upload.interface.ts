import type { Readable } from 'node:stream';

export interface IUploadProvider {
  uploadSimple(path: string): Promise<string>;
  uploadFile(file: Express.Multer.File): Promise<any>;
  removeFile(filePath: string): Promise<void>;

  /**
   * Writes a file straight from a stream, never holding it whole in memory.
   *
   * Optional on purpose: a provider that cannot stream (R2 would need multipart
   * uploads) simply omits it, and callers fall back to the buffered path. That
   * keeps this additive — no provider is forced to change.
   *
   * The caller is responsible for having already sniffed and validated the
   * type; `ext` and `mime` are what it decided.
   *
   * Implementations MUST abort and clean up the partial file when more than
   * `maxBytes` arrive, and signal it by throwing an error whose `message` is
   * exactly `FILE_TOO_LARGE`.
   */
  uploadStream?(
    stream: Readable,
    ext: string,
    mime: string,
    maxBytes: number
  ): Promise<any>;
}
