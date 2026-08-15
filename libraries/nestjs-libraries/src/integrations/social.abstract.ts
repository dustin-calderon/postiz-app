import { timer } from '@gitroom/helpers/utils/timer';
import { Integration } from '@prisma/client';
import { ApplicationFailure } from '@temporalio/activity';
import { readOrFetch } from '@gitroom/helpers/utils/read.or.fetch';
import sharp from 'sharp';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { existsSync } from 'node:fs';
import { join, normalize, sep } from 'node:path';

const execFileAsync = promisify(execFile);

export type ValidityMedia = {
  path: string;
  thumbnail?: string;
};

export type VideoMetadata = {
  width: number;
  height: number;
  durationSec: number;
  bitrateBps: number;
  sizeBytes: number;
};

export class RefreshToken extends ApplicationFailure {
  constructor(identifier: string, json: string, body: BodyInit, message = '') {
    super(message, 'refresh_token', true, [
      {
        identifier,
        json,
        body,
      },
    ]);
  }
}

export class BadBody extends ApplicationFailure {
  constructor(identifier: string, json: string, body: BodyInit, message = '') {
    super(message, 'bad_body', true, [
      {
        identifier,
        json,
        body,
      },
    ]);
  }
}

export class NotEnoughScopes {
  constructor(
    public message = 'Not enough scopes, when choosing a provider, please add all the scopes'
  ) {}
}

function safeStringify(obj: any) {
  const seen = new WeakSet();

  return JSON.stringify(obj, (key, value) => {
    if (typeof value === 'object' && value !== null) {
      if (seen.has(value)) {
        return '[Circular]';
      }
      seen.add(value);
    }
    return value;
  });
}

export abstract class SocialAbstract {
  abstract identifier: string;
  maxConcurrentJob = 1;

  public handleErrors(
    body: string,
    status: number
  ):
    | { type: 'refresh-token' | 'bad-body' | 'retry'; value: string }
    | undefined {
    return undefined;
  }

  /**
   * Server-side replacement for the old client-side `checkValidity`.
   * Validates the media attached to a post (and its comments) against the
   * provider rules. Returns `true` when valid, or an error message string.
   *
   * `posts` mirrors the client shape: the outer array is the main post followed
   * by each comment, the inner array is the media items for that entry.
   *
   * Image-dimension checks use sharp; video checks use ffprobe when the media
   * resolves to a local upload (see `probeUploadedVideo`) and fail open when
   * the file cannot be measured.
   */
  async checkValidity(
    posts: Array<ValidityMedia[]>,
    settings: any,
    additionalSettings: any[]
  ): Promise<string | true> {
    return true;
  }

  /** Reads the pixel dimensions of an image via sharp (works for http or local paths). */
  protected async getImageDimensions(
    path: string
  ): Promise<{ width: number; height: number }> {
    // Stored media paths are relative (e.g. "uploads/x.png"); resolve them to a
    // fetchable URL the same way posts.service.updateMedia does.
    const url =
      path?.indexOf('http') === -1
        ? `${process.env.FRONTEND_URL}/${path}`
        : path;
    const { width = 0, height = 0 } = await sharp(
      await readOrFetch(url)
    ).metadata();
    return { width, height };
  }

  /**
   * Maps a stored media path (full public URL or relative path) to its file on
   * disk. Returns null whenever the file is not measurable locally: storage is
   * not local, UPLOAD_DIRECTORY is unset, the URL has no /uploads segment
   * (external media), the resolved path escapes the upload directory, or the
   * file does not exist. Mirrors the URL→disk mapping of LocalStorage.removeFile.
   */
  protected resolveLocalUploadPath(mediaPath: string): string | null {
    const uploadDirectory = process.env.UPLOAD_DIRECTORY;
    if (
      (process.env.STORAGE_PROVIDER || 'local') !== 'local' ||
      !uploadDirectory ||
      !mediaPath
    ) {
      return null;
    }

    let pathname: string;
    try {
      pathname = decodeURIComponent(new URL(mediaPath).pathname);
    } catch {
      if (mediaPath.startsWith('http')) {
        return null;
      }
      pathname = mediaPath.startsWith('/') ? mediaPath : `/${mediaPath}`;
    }

    const uploadsIdx = pathname.indexOf('/uploads/');
    const relativePath =
      uploadsIdx !== -1
        ? pathname.slice(uploadsIdx + '/uploads'.length)
        : pathname;

    const diskPath = normalize(join(uploadDirectory, `.${relativePath}`));
    // A path built from user input feeds a native binary: never allow it to
    // escape the upload directory.
    if (!diskPath.startsWith(normalize(uploadDirectory + sep))) {
      return null;
    }

    return existsSync(diskPath) ? diskPath : null;
  }

  /**
   * Measures a local video file with ffprobe. Returns null when it cannot be
   * measured (ffprobe missing, timeout, unparseable output, no video stream):
   * callers must treat null as "no evidence", not as a failure.
   */
  protected async getVideoMetadata(
    localPath: string
  ): Promise<VideoMetadata | null> {
    try {
      const { stdout } = await execFileAsync(
        'ffprobe',
        [
          '-v',
          'error',
          '-print_format',
          'json',
          '-show_format',
          '-show_streams',
          localPath,
        ],
        { timeout: 5000, maxBuffer: 1024 * 1024 }
      );
      const probe = JSON.parse(stdout);
      const stream = (probe?.streams || []).find(
        (s: any) => s?.codec_type === 'video'
      );
      if (!stream) {
        return null;
      }
      // A field that cannot be read stays 0, which never exceeds a limit:
      // each rule only fires with actual evidence.
      return {
        width: +stream.width || 0,
        height: +stream.height || 0,
        durationSec: +(probe?.format?.duration ?? stream.duration) || 0,
        bitrateBps: +(stream.bit_rate ?? probe?.format?.bit_rate) || 0,
        sizeBytes: +probe?.format?.size || 0,
      };
    } catch {
      return null;
    }
  }

  /** resolveLocalUploadPath + getVideoMetadata; null = not measurable. */
  protected async probeUploadedVideo(
    mediaPath: string
  ): Promise<VideoMetadata | null> {
    const localPath = this.resolveLocalUploadPath(mediaPath);
    return localPath ? this.getVideoMetadata(localPath) : null;
  }

  public async mention(
    token: string,
    d: { query: string },
    id: string,
    integration: Integration
  ): Promise<
    | { id: string; label: string; image: string; doNotCache?: boolean }[]
    | { none: true }
  > {
    return { none: true };
  }

  async runInConcurrent<T>(
    func: (...args: any[]) => Promise<T>,
    ignoreConcurrency?: boolean
  ) {
    let globalErr = {};
    let value: any;
    try {
      value = await func();
    } catch (err) {
      const handle = this.handleErrors(safeStringify(err), 200);
      value = { err: true, value: 'Unknown Error', ...(handle || {}) };
      globalErr = err;
    }

    if (value && value?.err && value?.value) {
      if (value.type === 'refresh-token') {
        throw new RefreshToken(
          '',
          safeStringify({}),
          {} as any,
          value.value || ''
        );
      }
      throw new BadBody('', safeStringify(globalErr), {} as any, value.value || '');
    }

    return value;
  }

  async fetch(
    url: string,
    options: RequestInit = {},
    identifier = '',
    totalRetries = 0,
    ignoreConcurrency = false,
    message = '',
  ): Promise<Response> {
    const request = await fetch(url, options);

    if (request.status === 200 || request.status === 201) {
      return request;
    }

    if (totalRetries > 2) {
      throw new BadBody(identifier, '{}', options.body || '{}', message);
    }

    let json = '{}';
    try {
      json = await request.text();
    } catch (err) {
      json = '{}';
    }

    const handleError = this.handleErrors(json || '{}', request.status);

    if (
      request.status === 429 ||
      (request.status === 500 && !handleError) ||
      json.includes('rate_limit_exceeded') ||
      json.includes('Rate limit')
    ) {
      await timer(5000);
      return this.fetch(
        url,
        options,
        identifier,
        totalRetries + 1,
        ignoreConcurrency,
        handleError?.value || 'Unknown Error'
      );
    }

    if (handleError?.type === 'retry') {
      await timer(5000);
      return this.fetch(
        url,
        options,
        identifier,
        totalRetries + 1,
        ignoreConcurrency,
        handleError?.value || 'Unknown Error'
      );
    }

    if (
      (request.status === 401 &&
        (handleError?.type === 'refresh-token' || !handleError)) ||
      handleError?.type === 'refresh-token'
    ) {
      throw new RefreshToken(
        identifier,
        json,
        options.body!,
        handleError?.value
      );
    }

    throw new BadBody(
      identifier,
      json,
      options.body!,
      handleError?.value || 'Unknown Error'
    );
  }

  checkScopes(required: string[], got: string | string[]) {
    if (Array.isArray(got)) {
      if (!required.every((scope) => got.includes(scope))) {
        throw new NotEnoughScopes();
      }

      return true;
    }

    const newGot = decodeURIComponent(got);

    const splitType = newGot.indexOf(',') > -1 ? ',' : ' ';
    const gotArray = newGot.split(splitType);
    if (!required.every((scope) => gotArray.includes(scope))) {
      throw new NotEnoughScopes();
    }

    return true;
  }
}
