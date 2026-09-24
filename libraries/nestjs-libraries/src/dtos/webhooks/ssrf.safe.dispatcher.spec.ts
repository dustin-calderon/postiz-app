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
 * A test cannot reach the internet, so a local server plays the "public"
 * origin: the IP guard is told that 127.0.0.1 (and only it) is public. Every
 * other address keeps the real verdict, so ::1, 10.x, 192.168.x... are still
 * the real blocked addresses the requests must never reach.
 */
const PUBLIC_STAND_IN = '127.0.0.1';

// Names the fake resolver answers, so no test depends on real DNS.
const FAKE_DNS: Record<string, string> = {
  'public.test': PUBLIC_STAND_IN,
  'internal.test': '192.168.1.10',
  'metadata.test': '169.254.169.254',
};

let server: http.Server;
let port: number;
let secretHits = 0;

const realLookup = dns.lookup;

beforeAll(async () => {
  server = http.createServer((req, res) => {
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
  await new Promise<void>((resolve) =>
    server.listen(0, '0.0.0.0', () => resolve())
  );
  port = (server.address() as AddressInfo).port;
});

afterAll(async () => {
  await new Promise((resolve) => server.close(resolve));
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
    const address = FAKE_DNS[hostname];
    if (!address) {
      return (realLookup as any)(hostname, options, callback);
    }
    return options?.all
      ? callback(null, [{ address, family: 4 }])
      : callback(null, address, 4);
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

const internalUrls = () => [
  `http://127.0.0.1:${port}/secret`,
  `http://10.0.0.1:${port}/secret`,
  `http://172.16.0.1:${port}/secret`,
  `http://172.31.0.1:${port}/secret`,
  `http://192.168.1.1:${port}/secret`,
  `http://169.254.169.254:${port}/secret`,
  `http://[::1]:${port}/secret`,
  `http://[::ffff:127.0.0.1]:${port}/secret`,
  `http://localhost:${port}/secret`,
  `http://internal.test:${port}/secret`,
  `http://metadata.test:${port}/secret`,
  `http://public.test:${port}/redirect?to=${encodeURIComponent(
    `http://[::1]:${port}/secret`
  )}`,
  `http://public.test:${port}/redirect?to=${encodeURIComponent(
    `http://internal.test:${port}/secret`
  )}`,
];

describe('ssrfSafeDispatcher (fetch)', () => {
  // 127.0.0.1 is the stand-in public origin inside these tests, so the literal
  // 127.0.0.1 case is covered by the real guard in the next test instead.
  const urls = () =>
    internalUrls().filter((u) => !u.startsWith('http://127.0.0.1'));

  it('refuses every internal destination, redirects included', async () => {
    for (const url of urls()) {
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
  });

  it('refuses a literal 127.0.0.1 with the real guard', async () => {
    jest.restoreAllMocks();
    const error = await fetch(`http://127.0.0.1:${port}/secret`, {
      dispatcher: ssrfSafeDispatcher,
    } as any).then(
      () => null,
      (err) => err
    );
    expect(error?.cause?.message).toBe('Blocked IP');
    expect(secretHits).toBe(0);
  });

  it('never lets a request reach the internal service', async () => {
    for (const url of urls()) {
      await fetch(url, {
        dispatcher: ssrfSafeDispatcher,
        signal: AbortSignal.timeout(3000),
      } as any).catch(() => null);
    }
    expect(secretHits).toBe(0);
  });

  it('reaches a public destination, by name and after a redirect', async () => {
    const direct = await fetch(`http://public.test:${port}/`, {
      dispatcher: ssrfSafeDispatcher,
    } as any);
    expect(await direct.text()).toBe('ok');

    const redirected = await fetch(
      `http://public.test:${port}/redirect?to=${encodeURIComponent(
        `http://public.test:${port}/`
      )}`,
      { dispatcher: ssrfSafeDispatcher } as any
    );
    expect(await redirected.text()).toBe('ok');
  });
});

describe('getSsrfSafeAxios', () => {
  it('refuses every internal destination, redirects included', async () => {
    for (const url of internalUrls().filter(
      (u) => !u.startsWith('http://127.0.0.1')
    )) {
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

  it('refuses a literal 127.0.0.1 with the real guard', async () => {
    jest.restoreAllMocks();
    await expect(
      getSsrfSafeAxios().get(`http://127.0.0.1:${port}/secret`)
    ).rejects.toThrow('Blocked IP');
    expect(secretHits).toBe(0);
  });

  it('reaches a public destination, by name and after a redirect', async () => {
    const { data } = await getSsrfSafeAxios().get(
      `http://public.test:${port}/redirect?to=${encodeURIComponent(
        `http://public.test:${port}/`
      )}`
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
