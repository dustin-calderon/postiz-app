import { HttpException } from '@nestjs/common';
import { ssrfSafeDispatcher } from '@gitroom/nestjs-libraries/dtos/webhooks/ssrf.safe.dispatcher';
import { PublicIntegrationsController } from '@gitroom/backend/public-api/routes/v1/public.integrations.controller';

// The real manager and PostsService load every social provider and ESM
// packages that jest does not transform (same as refresh.integration.service.spec.ts).
jest.mock('@gitroom/nestjs-libraries/integrations/integration.manager', () => ({
  IntegrationManager: class {},
  socialIntegrationList: [],
}));
jest.mock(
  '@gitroom/nestjs-libraries/database/prisma/posts/posts.service',
  () => ({ PostsService: class {} })
);
// file-type is ESM-only (production loads it with --experimental-require-module)
// and jest runs CommonJS. The failing downloads below never reach the sniffer.
jest.mock('file-type', () => ({}), { virtual: true });

const setup = () => {
  const saveFile = jest.fn();
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

afterEach(() => {
  jest.restoreAllMocks();
});

/**
 * What the SSRF guard refuses (internal IPs, names and redirects) is proven in
 * ssrf.safe.dispatcher.spec.ts. Here only the route's side: it downloads
 * through that guard, and a download that fails is the caller's bad URL.
 */
describe('upload-from-url', () => {
  it('downloads through the SSRF guard', async () => {
    const fetch = jest
      .spyOn(global, 'fetch')
      .mockRejectedValue(new TypeError('fetch failed'));
    const { controller } = setup();

    await controller
      .uploadsFromUrl({ id: 'org' } as any, { url: 'https://files.test/a.png' })
      .catch(() => null);

    expect(fetch).toHaveBeenCalledWith(
      'https://files.test/a.png',
      expect.objectContaining({ dispatcher: ssrfSafeDispatcher })
    );
  });

  it('answers 400 and stores nothing when the download is refused', async () => {
    jest.spyOn(global, 'fetch').mockRejectedValue(
      // what fetch rejects with when the guard refuses the connection
      Object.assign(new TypeError('fetch failed'), {
        cause: new Error('Blocked IP'),
      })
    );
    const { controller, saveFile } = setup();

    const error = await controller
      .uploadsFromUrl({ id: 'org' } as any, { url: 'https://files.test/a.png' })
      .then(
        () => null,
        (err) => err
      );

    expect(error).toBeInstanceOf(HttpException);
    expect(error.getStatus()).toBe(400);
    expect(error.getResponse()).toEqual({ msg: 'Failed to fetch URL' });
    expect(saveFile).not.toHaveBeenCalled();
  });
});
