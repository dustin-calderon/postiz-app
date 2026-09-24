import http from 'node:http';
import dns from 'node:dns';
import { AddressInfo } from 'node:net';
import axios from 'axios';
import * as validator from '@gitroom/nestjs-libraries/dtos/webhooks/webhook.url.validator';
import {
  getSsrfSafeAxios,
  getSsrfSafeDispatcher,
  ssrfSafeDispatcher,
} from '@gitroom/nestjs-libraries/dtos/webhooks/ssrf.safe.dispatcher';

const { isBlockedIp } = validator;

/**
 * A test cannot reach the internet, so a server on 127.0.0.1 plays the public
 * origin: the IP guard is told that 127.0.0.1, and only it, is public. The
 * internal service lives on ::1 and keeps the real verdict, so a request that
 * slipped past the guard would really reach it and count a hit on /secret.
 */
const PUBLIC_STAND_IN = '127.0.0.1';

// Names the fake resolver answers, so no test depends on real DNS.
const FAKE_DNS: Record<string, { address: string; family: number }> = {
  'public.test': { address: PUBLIC_STAND_IN, family: 4 },
  'internal.test': { address: '::1', family: 6 },
  'metadata.test': { address: '169.254.169.254', family: 4 },
};

const realLookup = dns.lookup;

let secretHits = 0;
const servers: http.Server[] = [];
let publicPort: number;
let internalPort: number;

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
    res.end('ok');
  });
  await new Promise<void>((resolve) => server.listen(0, host, () => resolve()));
  servers.push(server);
  return (server.address() as AddressInfo).port;
};

const redirectTo = (target: string) =>
  `http://public.test:${publicPort}/redirect?to=${encodeURIComponent(target)}`;

beforeAll(async () => {
  publicPort = await listen(PUBLIC_STAND_IN);
  internalPort = await listen('::1');
});

afterAll(async () => {
  await Promise.all(
    servers.map((server) => new Promise((resolve) => server.close(resolve)))
  );
  await ssrfSafeDispatcher.close();
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
});

afterEach(() => {
  jest.restoreAllMocks();
  delete process.env.DISABLE_SSRF_PROTECTION;
});

describe('isBlockedIp', () => {
  it.each([
    '127.0.0.1',
    '10.1.2.3',
    '172.16.0.1',
    '172.31.255.255',
    '192.168.1.1',
    '169.254.169.254',
    '0.0.0.0',
    '::1',
    'fd00::1',
    'fe80::1',
    '::ffff:127.0.0.1',
    // What the URL parser turns [::ffff:127.0.0.1] and [::ffff:10.0.0.1] into
    '::ffff:7f00:1',
    '::ffff:a00:1',
  ])('blocks %s', (ip) => {
    expect(isBlockedIp(ip)).toBe(true);
  });

  it.each([
    '8.8.8.8',
    '172.15.255.255',
    '172.32.0.1',
    // Cloudflare, where auto.dustincalderon.com and postiz.dustincalderon.com resolve
    '172.67.205.26',
    '104.21.22.136',
    '2606:4700:3033::6815:1688',
    // Notion's signed file bucket
    '3.5.78.244',
    '::ffff:8.8.8.8',
  ])('lets %s through', (ip) => {
    expect(isBlockedIp(ip)).toBe(false);
  });
});

// Every one of these is refused. The ::1 ones are reachable, so a request
// that got through would show up in `secretHits`.
const internalUrls = () => [
  `http://10.0.0.1:${internalPort}/secret`,
  `http://172.16.0.1:${internalPort}/secret`,
  `http://172.31.0.1:${internalPort}/secret`,
  `http://192.168.1.1:${internalPort}/secret`,
  `http://169.254.169.254:${internalPort}/secret`,
  `http://[::1]:${internalPort}/secret`,
  `http://[::ffff:127.0.0.1]:${publicPort}/secret`,
  `http://internal.test:${internalPort}/secret`,
  `http://metadata.test:${internalPort}/secret`,
  redirectTo(`http://[::1]:${internalPort}/secret`),
  redirectTo(`http://internal.test:${internalPort}/secret`),
  redirectTo(`http://169.254.169.254:${internalPort}/secret`),
];

describe('ssrfSafeDispatcher (fetch)', () => {
  it('refuses every internal destination, redirects included', async () => {
    for (const url of internalUrls()) {
      const error = await fetch(url, {
        dispatcher: ssrfSafeDispatcher,
        // an unguarded 10.x/172.16.x would hang instead of failing
        signal: AbortSignal.timeout(3000),
      } as any).then(
        () => null,
        (err) => err
      );
      expect({ url, cause: error?.cause?.message }).toEqual({
        url,
        cause: 'Blocked IP',
      });
    }
    expect(secretHits).toBe(0);
  });

  it('refuses 127.0.0.1 and localhost with the real guard', async () => {
    jest.restoreAllMocks();
    for (const url of [
      `http://127.0.0.1:${publicPort}/secret`,
      `http://localhost:${publicPort}/secret`,
    ]) {
      const error = await fetch(url, {
        dispatcher: ssrfSafeDispatcher,
      } as any).then(
        () => null,
        (err) => err
      );
      expect({ url, cause: error?.cause?.message }).toEqual({
        url,
        cause: 'Blocked IP',
      });
    }
    expect(secretHits).toBe(0);
  });

  it('reaches a public destination, by name and after a redirect', async () => {
    const direct = await fetch(`http://public.test:${publicPort}/`, {
      dispatcher: ssrfSafeDispatcher,
    } as any);
    expect(await direct.text()).toBe('ok');

    const redirected = await fetch(
      redirectTo(`http://public.test:${publicPort}/`),
      { dispatcher: ssrfSafeDispatcher } as any
    );
    expect(await redirected.text()).toBe('ok');
  });
});

describe('getSsrfSafeAxios', () => {
  it('refuses every internal destination, redirects included', async () => {
    for (const url of internalUrls()) {
      const error = await getSsrfSafeAxios()
        .get(url, { timeout: 3000 })
        .then(
          () => null,
          (err) => err
        );
      expect({ url, message: error?.message }).toEqual({
        url,
        message: 'Blocked IP',
      });
    }
    expect(secretHits).toBe(0);
  });

  it('refuses 127.0.0.1 and localhost with the real guard', async () => {
    jest.restoreAllMocks();
    for (const url of [
      `http://127.0.0.1:${publicPort}/secret`,
      `http://localhost:${publicPort}/secret`,
    ]) {
      await expect(getSsrfSafeAxios().get(url)).rejects.toThrow('Blocked IP');
    }
    expect(secretHits).toBe(0);
  });

  it('reaches a public destination, by name and after a redirect', async () => {
    const { data } = await getSsrfSafeAxios().get(
      redirectTo(`http://public.test:${publicPort}/`)
    );
    expect(data).toBe('ok');
  });
});

describe('DISABLE_SSRF_PROTECTION', () => {
  it('is off by default', () => {
    expect(getSsrfSafeDispatcher()).toBe(ssrfSafeDispatcher);
    expect(getSsrfSafeAxios()).not.toBe(axios);
  });

  it('opts providers and webhooks out when set to true', () => {
    process.env.DISABLE_SSRF_PROTECTION = 'true';
    expect(getSsrfSafeDispatcher()).toBeUndefined();
    expect(getSsrfSafeAxios()).toBe(axios);
  });
});
