import {
  continueAsNew,
  log,
  proxyActivities,
  sleep,
  workflowInfo,
} from '@temporalio/workflow';
import type { IntegrationsActivity } from '@gitroom/orchestrator/activities/integrations.activity';

const { refreshDueTokens } = proxyActivities<IntegrationsActivity>({
  startToCloseTimeout: '10 minute',
  retry: {
    maximumAttempts: 3,
    backoffCoefficient: 1,
    initialInterval: '2 minutes',
  },
});

/**
 * Refreshes, once a day, the tokens that are close to expiring
 * (RefreshIntegrationService.refreshDueTokens).
 *
 * Replaces refreshTokenWorkflow, which slept until the expiry date and
 * disconnected the channel when that single attempt failed. Here a failed
 * refresh is retried every day for as long as the current token works.
 *
 * One workflow for every channel, started by InfiniteWorkflowRegister, so it
 * does not depend on a workflow started when the channel was connected: a
 * Temporal that lost its history keeps refreshing.
 *
 * Continues as new when Temporal suggests it, so its history never reaches
 * the limit at which Temporal terminates a workflow.
 */
export async function refreshDueTokensWorkflow(): Promise<void> {
  while (!workflowInfo().continueAsNewSuggested) {
    try {
      await refreshDueTokens();
    } catch (err) {
      // Activity exhausted all retries — log and try again tomorrow.
      log.error('Token refresh activity failed after retries', {
        error: String(err),
      });
    }
    await sleep('24 hours');
  }
  await continueAsNew<typeof refreshDueTokensWorkflow>();
}
