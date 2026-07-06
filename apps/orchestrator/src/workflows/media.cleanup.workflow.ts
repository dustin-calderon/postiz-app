import { proxyActivities, sleep, log } from '@temporalio/workflow';
import type { MediaCleanupActivity } from '@gitroom/orchestrator/activities/media.cleanup.activity';

const { cleanupStaleMedia } = proxyActivities<MediaCleanupActivity>({
  startToCloseTimeout: '15 minute',
  retry: {
    maximumAttempts: 3,
    backoffCoefficient: 2,
    initialInterval: '5 minutes',
  },
});

/**
 * Temporal infinite workflow that purges stale media files on a daily schedule.
 *
 * Media is considered "stale" when:
 *   - Created more than `retentionDays` ago
 *   - Not referenced by any active Post (QUEUE/DRAFT/ERROR/recent/recurring)
 *   - Not used as a User avatar, Agency logo, or OAuth app icon
 *
 * Follows the same `while(true) { doWork(); sleep(); }` pattern
 * used by `missingPostWorkflow`.
 *
 * NOTE: retentionDays is passed as a workflow argument because
 * Temporal workflows run in a deterministic V8 sandbox where
 * process.env is NOT available. The env var is read at registration
 * time in InfiniteWorkflowRegister.
 *
 * The try/catch inside the loop ensures that a non-retryable error
 * (e.g. schema mismatch) doesn't kill the workflow permanently.
 * It logs the failure and waits the full cycle before retrying.
 */
export async function mediaCleanupWorkflow(retentionDays = 30) {
  while (true) {
    try {
      await cleanupStaleMedia(retentionDays);
    } catch (err) {
      // Activity exhausted all retries — log and continue next cycle.
      // Without this catch, a non-retryable error would terminate
      // the infinite workflow permanently.
      log.error('Media cleanup activity failed after retries', {
        error: String(err),
      });
    }
    await sleep('24 hours');
  }
}
