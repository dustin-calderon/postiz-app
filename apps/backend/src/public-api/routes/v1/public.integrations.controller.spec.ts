import http from 'node:http';
import dns from 'node:dns';
import dnsPromises from 'node:dns/promises';
import { AddressInfo } from 'node:net';
import { mkdtempSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { HttpException } from '@nestjs/common';
import { plainToInstance } from 'class-transformer';
import { validate } from 'class-validator';
import * as validator from '@gitroom/nestjs-libraries/dtos/webhooks/webhook.url.validator';
import { ssrfSafeDispatcher } from '@gitroom/nestjs-libraries/dtos/webhooks/ssrf.safe.dispatcher';
import { UploadDto } from '@gitroom/nestjs-libraries/dtos/media/upload.dto';
import { PublicIntegrationsController } from '@gitroom/backend/public-api/routes/v1/public.integrations.controller';

// The real modules load every social provider, and some of them ship ESM that
// jest does not transform. upload-from-url only needs MediaService.saveFile,
// which the fake below gives.
jest.mock('@gitroom/nestjs-libraries/integrations/integration.manager', () => ({
  IntegrationManager: class {},
  socialIntegrationList: [],
}));
jest.mock(
  '@gitroom/nestjs-libraries/integrations/refresh.integration.service',
  () => ({ RefreshIntegrationService: class {} })
);
jest.mock(
  '@gitroom/nestjs-libraries/database/prisma/integrations/integration.service',
  () => ({ IntegrationService: class {} })
);
jest.mock(
  '@gitroom/nestjs-libraries/database/prisma/posts/posts.service',
  () => ({ PostsService: class {} })
);
jest.mock(
  '@gitroom/nestjs-libraries/database/prisma/media/media.service',
  () => ({ MediaService: class {} })
);
jest.mock(
  '@gitroom/nestjs-libraries/database/prisma/notifications/notification.service',
  () => ({ NotificationService: class {} })
);

// file-type is ESM-only (production loads it with --experimental-require-module)
// and jest runs CommonJS. The sniffer is not what these tests are about, so a
// stand-in recognises the one type they upload: PNG.
jest.mock(
  'file-type',
  () => {
    const { PassThrough } = jest.requireActual('node:stream');
    const sniff = (head: Buffer) =>
      head.subarray(0, 4).toString('hex') === '89504e47'
        ? { ext: 'png', mime: 'image/png' }
        : undefined;
    return {
      fileTypeFromBuffer: async (buffer: Buffer) => sniff(buffer),
      fileTypeStream: (source: any) =>
        new Promise((resolve, reject) => {
          source.once('error', reject);
          source.once('readable', () => {
            const head: Buffer = source.read() ?? Buffer.alloc(0);
            const replay = new PassThrough();
            replay.fileType = sniff(head);
            replay.write(head);
            source.pipe(replay);
            resolve(replay);
          });
        }),
    };
  },
  { virtual: true }
);

const { isBlockedIp } = validator;

// 1x1 PNG: enough for the type sniffer to accept it as an image.
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=',
  'base64'
);

/**
 * A test cannot reach the internet, so a server on 127.0.0.1 plays the public
 * origin (Notion's bucket, in production): the IP guard is told that
 * 127.0.0.1, and only it, is public. The internal service lives on ::1 and
 * keeps the real verdict, so a download that slipped past the guard would
 * really reach it and count a hit on /secret.
 */
const PUBLIC_STAND_IN = '127.0.0.1';

const FAKE_DNS: Record<string, { address: string; family: number }> = {
  'public.test': { address: PUBLIC_STAND_IN, family: 4 },
  'internal.test': { address: '::1', family: 6 },
  // Where Notion's signed file URLs point
  'prod-files-secure.s3.us-west-2.amazonaws.com': {
    address: '3.5.78.244',
    family: 4,
  },
};

const realLookup = dns.lookup;
const realPromisesLookup = dnsPromises.lookup;

let secretHits = 0;
const servers: http.Server[] = [];
let publicPort: number;
let internalPort: number;
let uploadDirectory: string;

const org = { id: 'org' } as any;

const listen = async (host: string) => {
  const server = http.createServer((req, res) => {
    const target = req.url?.startsWith('/redirect?to=')
      ? decodeURIComponent(req.url.slice('/redirect?to='.length))
      : '';
    if (target) {
      res.writeHead(302, { Location: target });
      res.end();
      return;
    }
    if (req.url === '/secret') {
      secretHits++;
    }
    res.writeHead(200, { 'Content-Type': 'image/png' });
    res.end(PNG);
  });
  await new Promise<void>((resolve) => server.listen(0, host, () => resolve()));
  servers.push(server);
  return (server.address() as AddressInfo).port;
};

const redirectTo = (target: string) =>
  `http://public.test:${publicPort}/redirect?to=${encodeURIComponent(target)}`;

const setup = () => {
  const saveFile = jest.fn(
    async (_org: string, name: string, path: string) => ({
      id: 'media',
      name,
      path,
    })
  );
  const controller = new PublicIntegrationsController(
    {} as any,
    {} as any,
    { saveFile } as any,
    {} as any,
    {} as any,
    {} as any
  );
  return { controller, saveFile };
};

const uploadError = (controller: PublicIntegrationsController, url: string) =>
  controller.uploadsFromUrl(org, { url }).then(
    () => null,
    (err) => err
  );

const storedFiles = (dir = uploadDirectory): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? storedFiles(join(dir, entry.name)) : [entry.name]
  );

beforeAll(async () => {
  uploadDirectory = mkdtempSync(join(tmpdir(), 'upload-from-url-'));
  process.env.STORAGE_PROVIDER = 'local';
  process.env.UPLOAD_DIRECTORY = uploadDirectory;
  process.env.FRONTEND_URL = 'https://postiz.test';
  publicPort = await listen(PUBLIC_STAND_IN);
  internalPort = await listen('::1');
});

afterAll(async () => {
  await Promise.all(
    servers.map((server) => new Promise((resolve) => server.close(resolve)))
  );
  await ssrfSafeDispatcher.close();
  rmSync(uploadDirectory, { recursive: true, force: true });
});

beforeEach(() => {
  secretHits = 0;
  jest
    .spyOn(validator, 'isBlockedIp')
    .mockImplementation((ip) =>
      ip === PUBLIC_STAND_IN ? false : isBlockedIp(ip)
    );
  jest.spyOn(dns, 'lookup').mockImplementation(((
    hostname: string,
    options: any,
    callback: any
  ) => {
    const fake = FAKE_DNS[hostname];
    if (!fake) {
      return (realLookup as any)(hostname, options, callback);
    }
    return options?.all
      ? callback(null, [fake])
      : callback(null, fake.address, fake.family);
  }) as any);
  jest.spyOn(dnsPromises, 'lookup').mockImplementation((async (
    hostname: string,
    options: any
  ) => {
    const fake = FAKE_DNS[hostname];
    if (!fake) {
      return (realPromisesLookup as any)(hostname, options);
    }
    return options?.all ? [fake] : fake;
  }) as any);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('upload-from-url: the URL it is given (UploadDto)', () => {
  const errorsFor = async (url: string) =>
    (await validate(plainToInstance(UploadDto, { url }))).length;

  it.each([
    'https://127.0.0.1/a.png',
    'https://10.0.0.1/a.png',
    'https://172.16.0.1/a.png',
    'https://192.168.1.1/a.png',
    'https://169.254.169.254/a.png',
    'https://[::1]/a.png',
    'https://localhost/a.png',
    'https://internal.test/a.png',
  ])('rejects %s', async (url) => {
    expect(await errorsFor(url)).toBeGreaterThan(0);
  });

  it('accepts a signed Notion file URL, as the pipeline sends it', async () => {
    expect(
      await errorsFor(
        'https://prod-files-secure.s3.us-west-2.amazonaws.com/a1b2/c3d4/reel.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc'
      )
    ).toBe(0);
  });
});

describe('upload-from-url: what it actually downloads', () => {
  it('stores a public file, also after a redirect', async () => {
    const { controller, saveFile } = setup();

    await controller.uploadsFromUrl(org, {
      url: `http://public.test:${publicPort}/image.png`,
    });
    await controller.uploadsFromUrl(org, {
      url: redirectTo(`http://public.test:${publicPort}/image.png`),
    });

    expect(saveFile).toHaveBeenCalledTimes(2);
    expect(saveFile).toHaveBeenCalledWith(
      'org',
      expect.stringMatching(/\.png$/),
      expect.stringMatching(/^https:\/\/postiz\.test\/uploads\/.*\.png$/)
    );
  });

  // The DTO only sees the first URL: these are what it cannot catch.
  it.each([
    ['a literal internal IP', () => `http://[::1]:${internalPort}/secret`],
    [
      'a name that resolves inside',
      () => `http://internal.test:${internalPort}/secret`,
    ],
    ['cloud metadata', () => `http://169.254.169.254:${internalPort}/secret`],
  ])(
    'refuses a public URL that redirects to %s, and stores nothing',
    async (_label, target) => {
      const { controller, saveFile } = setup();
      const before = storedFiles().length;

      const error = await uploadError(controller, redirectTo(target()));

      expect(error).toBeInstanceOf(HttpException);
      expect(error.getStatus()).toBe(400);
      expect(error.getResponse()).toEqual({ msg: 'Failed to fetch URL' });
      expect(saveFile).not.toHaveBeenCalled();
      expect(storedFiles().length).toBe(before);
      expect(secretHits).toBe(0);
    }
  );

  it.each([
    () => `http://[::1]:${internalPort}/secret`,
    () => `http://internal.test:${internalPort}/secret`,
    () => `http://10.0.0.1:${internalPort}/secret`,
    () => `http://172.16.0.1:${internalPort}/secret`,
    () => `http://192.168.1.1:${internalPort}/secret`,
  ])('refuses an internal URL even past the DTO (%#)', async (url) => {
    const { controller, saveFile } = setup();

    const error = await uploadError(controller, url());

    expect(error?.getStatus?.()).toBe(400);
    expect(saveFile).not.toHaveBeenCalled();
    expect(secretHits).toBe(0);
  });

  it('refuses 127.0.0.1 and localhost with the real guard', async () => {
    jest.restoreAllMocks();
    const { controller, saveFile } = setup();

    for (const url of [
      `http://127.0.0.1:${publicPort}/secret`,
      `http://localhost:${publicPort}/secret`,
    ]) {
      const error = await uploadError(controller, url);
      expect(error?.getStatus?.()).toBe(400);
    }
    expect(saveFile).not.toHaveBeenCalled();
    expect(secretHits).toBe(0);
  });
});
