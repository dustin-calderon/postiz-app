import dnsPromises from 'node:dns/promises';
import { plainToInstance } from 'class-transformer';
import { validate } from 'class-validator';
import { UploadDto } from '@gitroom/nestjs-libraries/dtos/media/upload.dto';

// Names the fake resolver answers, so no test depends on real DNS.
const FAKE_DNS: Record<string, string> = {
  'internal.test': '10.20.30.40',
  // Where Notion's signed file URLs point
  'prod-files-secure.s3.us-west-2.amazonaws.com': '3.5.78.244',
};

const realLookup = dnsPromises.lookup;

beforeEach(() => {
  jest.spyOn(dnsPromises, 'lookup').mockImplementation((async (
    hostname: string,
    options: any
  ) => {
    const address = FAKE_DNS[hostname];
    if (!address) {
      return (realLookup as any)(hostname, options);
    }
    return options?.all ? [{ address, family: 4 }] : { address, family: 4 };
  }) as any);
});

afterEach(() => {
  jest.restoreAllMocks();
});

// UploadDto is what /public/v1/upload-from-url validates its body with. It
// only sees the URL it is given: redirects are the dispatcher's job
// (ssrf.safe.dispatcher.spec.ts).
describe('IsSafeWebhookUrl on UploadDto', () => {
  const errorsFor = async (url: string) =>
    (await validate(plainToInstance(UploadDto, { url }))).length;

  it.each([
    'https://127.0.0.1/a.png',
    'https://10.0.0.1/a.png',
    'https://172.16.0.1/a.png',
    'https://192.168.1.1/a.png',
    'https://169.254.169.254/a.png',
    'https://[::1]/a.png',
    'https://[::ffff:127.0.0.1]/a.png',
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
