import { IUploadProvider } from './upload.interface';
import {
  createWriteStream,
  mkdirSync,
  unlink,
  unlinkSync,
  writeFileSync,
} from 'fs';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { isSafePublicHttpsUrl } from '@gitroom/nestjs-libraries/dtos/webhooks/webhook.url.validator';
import { ssrfSafeDispatcher } from '@gitroom/nestjs-libraries/dtos/webhooks/ssrf.safe.dispatcher';
import { parseDataUrl } from '@gitroom/nestjs-libraries/upload/data.url';
// eslint-disable-next-line @typescript-eslint/no-var-requires
const { fromBuffer } = require('file-type');

const LOCAL_STORAGE_ALLOWED_MIME = new Set<string>([
  'image/jpeg',
  'image/png',
  'image/gif',
  'image/webp',
  'image/avif',
  'image/bmp',
  'image/tiff',
  'video/mp4',
  'video/quicktime',
  'video/webm',
  'video/mpeg',
  'audio/mpeg',
  'audio/mp4',
  'audio/wav',
  'audio/ogg',
]);
export class LocalStorage implements IUploadProvider {
  constructor(private uploadDirectory: string) {}

  async uploadSimple(path: string) {
    const dataUrl = path.startsWith('data:') ? parseDataUrl(path) : null;

    let body: Buffer;
    if (dataUrl) {
      body = dataUrl.buffer;
    } else {
      if (!(await isSafePublicHttpsUrl(path))) {
        throw new Error('Unsafe URL');
      }
      const loadImage = await fetch(path, {
        // @ts-ignore — undici option, not in lib.dom fetch types
        dispatcher: ssrfSafeDispatcher,
      });
      // `fetch` only rejects on transport errors, so without this an error page
      // walks straight into the sniffer below and comes back out as
      // "Unsupported file type." — which sent a real incident chasing the mime
      // allow-list when the URL was simply a 404.
      if (!loadImage.ok) {
        throw new Error(`Could not fetch ${path}: HTTP ${loadImage.status}`);
      }
      body = Buffer.from(await loadImage.arrayBuffer());
    }

    // Never trust the claimed mime/extension (data URL header, remote
    // content-type, or URL path): sniff the real type from the bytes and
    // only accept the allow-list, otherwise an attacker could write an
    // arbitrary file (e.g. .html/.svg with embedded script) into the
    // publicly served uploads directory on the app's own origin.
    const detected = await fromBuffer(body);
    if (!detected || !LOCAL_STORAGE_ALLOWED_MIME.has(detected.mime)) {
      throw new Error('Unsupported file type.');
    }
    const findExtension = detected.ext;

    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');

    const innerPath = `/${year}/${month}/${day}`;
    const dir = `${this.uploadDirectory}${innerPath}`;
    mkdirSync(dir, { recursive: true });

    const randomName = Array(32)
      .fill(null)
      .map(() => Math.round(Math.random() * 16).toString(16))
      .join('');

    const filePath = `${dir}/${randomName}.${findExtension}`;
    const publicPath = `${innerPath}/${randomName}.${findExtension}`;
    // Logic to save the file to the filesystem goes here
    writeFileSync(filePath, body);

    return process.env.FRONTEND_URL + '/uploads' + publicPath;
  }

  /**
   * Resolves where a new file goes: `<uploadDirectory>/YYYY/MM/DD/<32 hex>.<ext>`.
   *
   * Shared by the buffered and the streaming paths so the naming scheme can
   * never drift between them — `removeFile()` and the cleanup job both parse
   * this layout back out of the public URL.
   */
  private buildTarget(safeExt: string) {
    const now = new Date();
    const year = now.getFullYear();
    const month = String(now.getMonth() + 1).padStart(2, '0');
    const day = String(now.getDate()).padStart(2, '0');

    const innerPath = `/${year}/${month}/${day}`;
    const dir = `${this.uploadDirectory}${innerPath}`;
    mkdirSync(dir, { recursive: true });

    const randomName = Array(32)
      .fill(null)
      .map(() => Math.round(Math.random() * 16).toString(16))
      .join('');

    const filename = `${randomName}${safeExt}`;

    return {
      filename,
      filePath: `${dir}/${filename}`,
      publicPath: `${innerPath}/${filename}`,
    };
  }

  async uploadFile(file: Express.Multer.File): Promise<any> {
    try {
      const detected = await fromBuffer(file.buffer);
      if (!detected || !LOCAL_STORAGE_ALLOWED_MIME.has(detected.mime)) {
        throw new Error('Unsupported file type.');
      }
      const safeExt = `.${detected.ext}`;
      const safeMime = detected.mime;

      const { filename, filePath, publicPath } = this.buildTarget(safeExt);

      writeFileSync(filePath, file.buffer);

      return {
        filename,
        path: process.env.FRONTEND_URL + '/uploads' + publicPath,
        mimetype: safeMime,
        originalname: filename,
      };
    } catch (err) {
      console.error('Error uploading file to Local Storage:', err);
      throw err;
    }
  }

  /**
   * Streams a file to disk without ever holding it whole in memory.
   *
   * The buffered path needs RAM proportional to the file, which puts a hard
   * ceiling on how big a video can be — and this process also runs the
   * orchestrator, so an oversized upload takes scheduled posting down with it.
   * Streaming makes memory use constant, so the only real limit becomes
   * `maxBytes`.
   *
   * The type has already been sniffed and validated by the caller: this method
   * only writes bytes.
   */
  async uploadStream(
    stream: Readable,
    ext: string,
    mime: string,
    maxBytes: number
  ): Promise<any> {
    const safeExt = `.${ext}`;
    const { filename, filePath, publicPath } = this.buildTarget(safeExt);

    let written = 0;
    const limiter = new Transform({
      transform(chunk, _encoding, callback) {
        written += chunk.length;
        if (written > maxBytes) {
          // Aborts the pipeline, which tears down the download too — we stop
          // pulling bytes instead of draining a huge file just to reject it.
          callback(new Error('FILE_TOO_LARGE'));
          return;
        }
        callback(null, chunk);
      },
    });

    try {
      await pipeline(stream, limiter, createWriteStream(filePath));
    } catch (err) {
      // A partial file left behind would be served as a corrupt media and
      // would never be cleaned up: nothing references it.
      try {
        unlinkSync(filePath);
      } catch {
        /** the file may not exist yet */
      }
      throw err;
    }

    return {
      filename,
      path: process.env.FRONTEND_URL + '/uploads' + publicPath,
      mimetype: mime,
      originalname: filename,
      size: written,
    };
  }

  /**
   * Removes a file from local filesystem storage.
   *
   * Accepts either:
   *   - A full URL (http://localhost:4200/uploads/2026/07/06/abc.png)
   *   - A bare filesystem path (/var/uploads/2026/07/06/abc.png)
   *
   * When receiving a URL (which is how Media.path stores local paths),
   * extracts the relative path after '/uploads' and resolves it against
   * the configured uploadDirectory.
   */
  async removeFile(filePath: string): Promise<void> {
    let diskPath: string;

    try {
      const url = new URL(filePath);
      // URL like http://host/uploads/2026/07/06/abc.png
      // Extract everything after '/uploads' → /2026/07/06/abc.png
      const uploadsIdx = url.pathname.indexOf('/uploads');
      if (uploadsIdx !== -1) {
        const relativePath = url.pathname.slice(uploadsIdx + '/uploads'.length);
        diskPath = this.uploadDirectory + relativePath;
      } else {
        // URL without /uploads segment — use full pathname
        diskPath = this.uploadDirectory + url.pathname;
      }
    } catch {
      // Not a valid URL — treat as a bare filesystem path
      diskPath = filePath;
    }

    if (!diskPath) {
      return;
    }

    return new Promise((resolve, reject) => {
      unlink(diskPath, (err) => {
        if (err && (err as NodeJS.ErrnoException).code === 'ENOENT') {
          // File already gone — not an error for cleanup
          resolve();
        } else if (err) {
          reject(err);
        } else {
          resolve();
        }
      });
    });
  }
}
