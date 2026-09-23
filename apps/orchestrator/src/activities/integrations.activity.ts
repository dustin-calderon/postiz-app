import { Injectable, Logger } from '@nestjs/common';
import { Activity, ActivityMethod } from 'nestjs-temporal-core';
import { IntegrationService } from '@gitroom/nestjs-libraries/database/prisma/integrations/integration.service';
import { Integration } from '@prisma/client';
import dayjs from 'dayjs';
import { RefreshIntegrationService } from '@gitroom/nestjs-libraries/integrations/refresh.integration.service';

@Injectable()
@Activity()
export class IntegrationsActivity {
  private readonly _logger = new Logger(IntegrationsActivity.name);

  constructor(
    private _integrationService: IntegrationService,
    private _refreshIntegrationService: RefreshIntegrationService
  ) {}

  @ActivityMethod()
  async getIntegrationsById(id: string, orgId: string) {
    return this._integrationService.getIntegrationById(orgId, id);
  }

  // Only refreshTokenWorkflow calls it, the per-channel workflow that
  // refreshDueTokensWorkflow replaced. One still running wakes up at the expiry
  // date it read when it started, by which time the daily pass has usually
  // renewed the token: a failure then must not disconnect a channel whose
  // token still works.
  async refreshToken(integration: Integration) {
    return this._refreshIntegrationService.refresh(
      integration,
      '',
      !dayjs(integration.tokenExpiration).isBefore(dayjs())
    );
  }

  @ActivityMethod()
  async refreshDueTokens() {
    const result = await this._refreshIntegrationService.refreshDueTokens();

    this._logger.log(
      `Token refresh pass — due: ${result.due}, refreshed: ${result.refreshed}`
    );

    return result;
  }
}
