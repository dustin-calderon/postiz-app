import {
  continueAsNew,
  log,
  proxyActivities,
  sleep,
  workflowInfo,
} from '@temporalio/workflow';
import type { PostActivity } from '@gitroom/orchestrator/activities/post.activity';

const { searchForMissingThreeHoursPosts } = proxyActivities<PostActivity>({
  startToCloseTimeout: '10 minute',
  retry: {
    maximumAttempts: 3,
    backoffCoefficient: 1,
    initialInterval: '2 minutes',
  },
});

/**
 * missingPostWorkflow, fixed for a workflow that never ends.
 *
 * Temporal terminates a workflow whose history reaches 51,200 events, and the
 * hourly loop of missingPostWorkflow adds about 260 a day: it would be
 * terminated after about 200 days, and nothing would start it again until the
 * backend restarts. It also failed for good the first time its activity ran
 * out of retries. This version continues as new when Temporal suggests it, and
 * a failed pass waits for the next hour.
 */
export async function missingPostWorkflowV2(): Promise<void> {
  while (!workflowInfo().continueAsNewSuggested) {
    try {
      await searchForMissingThreeHoursPosts();
    } catch (err) {
      // Activity exhausted all retries — log and try again in an hour.
      log.error('Missing posts activity failed after retries', {
        error: String(err),
      });
    }
    await sleep('1 hour');
  }
  await continueAsNew<typeof missingPostWorkflowV2>();
}
