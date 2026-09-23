import dayjs from 'dayjs';
import { Integration } from '@prisma/client';
import { RefreshIntegrationService } from '@gitroom/nestjs-libraries/integrations/refresh.integration.service';
import type { IntegrationManager } from '@gitroom/nestjs-libraries/integrations/integration.manager';
import type { IntegrationService } from '@gitroom/nestjs-libraries/database/prisma/integrations/integration.service';

// The real modules load every social provider, and some of them ship ESM that
// jest does not transform. The service only needs what the fakes below give.
jest.mock('@gitroom/nestjs-libraries/integrations/integration.manager', () => ({
  IntegrationManager: class {},
}));
jest.mock(
  '@gitroom/nestjs-libraries/database/prisma/integrations/integration.service',
  () => ({ IntegrationService: class {} })
);

const channel = (tokenExpiration: Date) =>
  ({
    id: 'i1',
    organizationId: 'org',
    name: 'CITEM',
    picture: 'https://example.com/old.png',
    internalId: 'ig1',
    rootInternalId: 'ig1',
    providerIdentifier: 'instagram-standalone',
    refreshToken: 'old-token',
    tokenExpiration,
  } as Integration);

const setup = (
  integration: Integration,
  refreshToken: (token: string) => Promise<unknown>
) => {
  const integrationService = {
    getIntegrationsToRefresh: jest.fn(async () => [integration]),
    createOrUpdateIntegration: jest.fn(async () => integration),
    refreshNeeded: jest.fn(),
    informAboutRefreshError: jest.fn(),
    disconnectChannel: jest.fn(),
  };
  const integrationManager = {
    getRefreshCronIntegrations: jest.fn(() => ['instagram-standalone']),
    getSocialIntegration: jest.fn(() => ({ refreshToken })),
  };
  const service = new RefreshIntegrationService(
    integrationManager as unknown as IntegrationManager,
    integrationService as unknown as IntegrationService
  );
  return { service, integrationService };
};

const failing = () => Promise.reject(new Error('Meta is down'));
const working = async () => ({
  id: 'ig1',
  name: 'CITEM',
  accessToken: 'new-token',
  refreshToken: 'new-token',
  expiresIn: 58 * 24 * 3600,
  picture: 'https://example.com/new.png',
  username: 'citem',
});

describe('RefreshIntegrationService.refreshDueTokens', () => {
  it('asks only for refreshCron providers expiring within 30 days', async () => {
    const { service, integrationService } = setup(
      channel(dayjs().add(9, 'day').toDate()),
      working
    );

    await service.refreshDueTokens();

    const [providers, before] =
      integrationService.getIntegrationsToRefresh.mock.calls[0] as unknown as [
        string[],
        Date
      ];
    expect(providers).toEqual(['instagram-standalone']);
    expect(Math.round(dayjs(before).diff(dayjs(), 'hour') / 24)).toBe(30);
  });

  it('stores the new token when the provider refreshes it', async () => {
    const { service, integrationService } = setup(
      channel(dayjs().add(9, 'day').toDate()),
      working
    );

    expect(await service.refreshDueTokens()).toEqual({ due: 1, refreshed: 1 });
    expect(integrationService.createOrUpdateIntegration).toHaveBeenCalledWith(
      undefined,
      false,
      'org',
      'CITEM',
      'https://example.com/new.png',
      'social',
      'ig1',
      'instagram-standalone',
      'new-token',
      'new-token',
      58 * 24 * 3600
    );
  });

  it('keeps the channel connected when a token that still works fails to refresh', async () => {
    const { service, integrationService } = setup(
      channel(dayjs().add(9, 'day').toDate()),
      failing
    );

    expect(await service.refreshDueTokens()).toEqual({ due: 1, refreshed: 0 });
    expect(integrationService.refreshNeeded).not.toHaveBeenCalled();
    expect(integrationService.informAboutRefreshError).not.toHaveBeenCalled();
    expect(integrationService.disconnectChannel).not.toHaveBeenCalled();
    expect(integrationService.createOrUpdateIntegration).not.toHaveBeenCalled();
  });

  it('disconnects the channel when an expired token fails to refresh', async () => {
    const { service, integrationService } = setup(
      channel(dayjs().subtract(1, 'hour').toDate()),
      failing
    );

    expect(await service.refreshDueTokens()).toEqual({ due: 1, refreshed: 0 });
    expect(integrationService.refreshNeeded).toHaveBeenCalledWith('org', 'i1');
    expect(integrationService.disconnectChannel).toHaveBeenCalled();
  });
});
