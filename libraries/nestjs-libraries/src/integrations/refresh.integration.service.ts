import { forwardRef, Inject, Injectable } from '@nestjs/common';
import { Integration } from '@prisma/client';
import dayjs from 'dayjs';
import { IntegrationManager } from '@gitroom/nestjs-libraries/integrations/integration.manager';
import { IntegrationService } from '@gitroom/nestjs-libraries/database/prisma/integrations/integration.service';
import {
  AuthTokenDetails,
  SocialProvider,
} from '@gitroom/nestjs-libraries/integrations/social/social.integrations.interface';

// Providers with `refreshCron` hand out long-lived tokens (Instagram and
// Threads: 60 days, refreshable once they are a day old). Refreshing them in
// their last 30 days leaves a month of daily retries before they expire.
const REFRESH_WINDOW_DAYS = 30;

@Injectable()
export class RefreshIntegrationService {
  constructor(
    private _integrationManager: IntegrationManager,
    @Inject(forwardRef(() => IntegrationService))
    private _integrationService: IntegrationService
  ) {}
  async refresh(
    integration: Integration,
    cause = '',
    retryLater = false
  ): Promise<false | AuthTokenDetails> {
    const socialProvider = this._integrationManager.getSocialIntegration(
      integration.providerIdentifier
    );

    const refresh = await this.refreshProcess(
      integration,
      socialProvider,
      cause,
      retryLater
    );

    if (!refresh) {
      return false as const;
    }

    await this._integrationService.createOrUpdateIntegration(
      undefined,
      !!socialProvider.oneTimeToken,
      integration.organizationId,
      integration.name,
      // Prefer the avatar the provider just handed us over the one we have on
      // record. Every provider returns a fresh `picture` from this same refresh
      // call and it used to be thrown away, re-sending the stored URL instead —
      // so once that file went missing the refresh downloaded its own 404 page
      // and blew up, taking the new token with it.
      refresh.picture || integration.picture!,
      'social',
      integration.internalId,
      integration.providerIdentifier,
      refresh.accessToken,
      refresh.refreshToken,
      refresh.expiresIn
    );

    return refresh;
  }

  // A token refreshed before it expires can fail without consequences: the
  // current one still works, and tomorrow's pass tries again. Only a token
  // that has already expired disconnects its channel when the refresh fails.
  async refreshDueTokens() {
    const integrations = await this._integrationService.getIntegrationsToRefresh(
      this._integrationManager.getRefreshCronIntegrations(),
      dayjs().add(REFRESH_WINDOW_DAYS, 'day').toDate()
    );

    let refreshed = 0;
    for (const integration of integrations) {
      const expired = dayjs(integration.tokenExpiration).isBefore(dayjs());
      if (await this.refresh(integration, '', !expired)) {
        refreshed++;
      }
    }

    return { due: integrations.length, refreshed };
  }

  public async setBetweenSteps(integration: Integration, cause = '') {
    await this._integrationService.setBetweenRefreshSteps(integration.id);
    await this._integrationService.informAboutRefreshError(
      integration.organizationId,
      integration,
      cause
    );
  }

  private async refreshProcess(
    integration: Integration,
    socialProvider: SocialProvider,
    cause = '',
    retryLater = false
  ): Promise<AuthTokenDetails | false> {
    const refresh: false | AuthTokenDetails = await socialProvider
      .refreshToken(integration.refreshToken)
      .catch((err) => false);

    if (!refresh || !refresh.accessToken) {
      if (retryLater) {
        return false;
      }

      await this._integrationService.refreshNeeded(
        integration.organizationId,
        integration.id
      );

      await this._integrationService.informAboutRefreshError(
        integration.organizationId,
        integration,
        cause
      );

      await this._integrationService.disconnectChannel(
        integration.organizationId,
        integration
      );

      return false;
    }

    if (
      !socialProvider.reConnect ||
      integration.rootInternalId === integration.internalId
    ) {
      return refresh;
    }

    const reConnect = await socialProvider.reConnect(
      integration.rootInternalId,
      integration.internalId,
      refresh.accessToken
    );

    return {
      ...refresh,
      ...reConnect,
    };
  }
}
