import { Injectable, Logger } from '@nestjs/common';
import { Activity, ActivityMethod } from 'nestjs-temporal-core';
import { MediaService } from '@gitroom/nestjs-libraries/database/prisma/media/media.service';

/**
 * Temporal activity for the media cleanup workflow.
 *
 * Wraps MediaService.cleanupStaleMedia() so it can be invoked
 * as a durable, retryable Temporal activity with proper timeouts.
 */
@Injectable()
@Activity()
export class MediaCleanupActivity {
  private readonly _logger = new Logger(MediaCleanupActivity.name);

  constructor(private _mediaService: MediaService) {}

  /**
   * Runs a single media cleanup pass.
   *
   * @param retentionDays Number of days to retain media after last active use. Default: 30.
   * @returns Summary of the cleanup operation.
   */
  @ActivityMethod()
  async cleanupStaleMedia(retentionDays = 30): Promise<{
    candidates: number;
    removed: number;
    failed: number;
    orphansRemoved: number;
    errors: string[];
  }> {
    this._logger.log(
      `Starting media cleanup (retention: ${retentionDays} days)...`
    );

    const result = await this._mediaService.cleanupStaleMedia(retentionDays);

    this._logger.log(
      `Media cleanup pass — candidates: ${result.candidates}, removed: ${result.removed}, orphans: ${result.orphansRemoved}, failed: ${result.failed}`
    );

    if (result.errors.length > 0) {
      this._logger.warn(
        `Media cleanup errors:\n${result.errors.join('\n')}`
      );
    }

    return result;
  }
}
