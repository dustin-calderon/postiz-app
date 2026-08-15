import { isVideo } from '@gitroom/helpers/utils/has.extension';
import type {
  ValidityMedia,
  VideoMetadata,
} from '@gitroom/nestjs-libraries/integrations/social.abstract';

/**
 * Hard limits from the Instagram Graph API for video containers. A video past
 * any of these never finishes processing on Meta's side: the container stays
 * IN_PROGRESS until the bounded wait in waitForContainer gives up, which loses
 * the publishing slot. Rejecting at post creation surfaces the problem the day
 * the post is scheduled instead of the day it publishes.
 * https://developers.facebook.com/docs/instagram-platform/content-publishing/
 */
export const INSTAGRAM_VIDEO_LIMITS = {
  maxSidePx: 1920,
  maxVideoBitrateBps: 25_000_000,
  maxSizeBytes: 1_073_741_824,
  maxReelDurationSec: 900,
  maxStoryDurationSec: 60,
} as const;

const asMbps = (bps: number) => `${(bps / 1_000_000).toFixed(1)} Mbps`;
const asMb = (bytes: number) => `${(bytes / 1_048_576).toFixed(1)} MB`;

/** Pure: measured metadata → readable limit violations (empty = compliant). */
export function instagramVideoViolations(
  meta: VideoMetadata,
  postType: 'post' | 'story'
): string[] {
  const violations: string[] = [];
  const longestSide = Math.max(meta.width, meta.height);

  if (longestSide > INSTAGRAM_VIDEO_LIMITS.maxSidePx) {
    violations.push(
      `resolution ${longestSide}px exceeds ${INSTAGRAM_VIDEO_LIMITS.maxSidePx}px max on the longest side`
    );
  }
  if (meta.bitrateBps > INSTAGRAM_VIDEO_LIMITS.maxVideoBitrateBps) {
    violations.push(
      `video bitrate ${asMbps(meta.bitrateBps)} exceeds ${asMbps(
        INSTAGRAM_VIDEO_LIMITS.maxVideoBitrateBps
      )} max`
    );
  }
  if (meta.sizeBytes > INSTAGRAM_VIDEO_LIMITS.maxSizeBytes) {
    violations.push(`file size ${asMb(meta.sizeBytes)} exceeds 1 GB max`);
  }
  if (postType === 'story') {
    if (meta.durationSec > INSTAGRAM_VIDEO_LIMITS.maxStoryDurationSec) {
      violations.push(
        `duration ${Math.round(meta.durationSec)}s exceeds ${
          INSTAGRAM_VIDEO_LIMITS.maxStoryDurationSec
        }s max for stories`
      );
    }
  } else if (meta.durationSec > INSTAGRAM_VIDEO_LIMITS.maxReelDurationSec) {
    violations.push(
      `duration ${Math.round(meta.durationSec)}s exceeds 15 minutes max`
    );
  }

  return violations;
}

/**
 * Validates every video in a post's media against Instagram's limits using the
 * provided probe. Non-videos and anything the probe cannot measure are skipped
 * (fail-open: only actual evidence blocks a post). Returns true or an error
 * message with the measured values — that text travels via webhook into the
 * Notion error_log, so it must be actionable on its own.
 */
export async function checkInstagramVideos(
  media: ValidityMedia[],
  settings: { post_type?: string } | undefined,
  probe: (path: string) => Promise<VideoMetadata | null>
): Promise<string | true> {
  const postType = settings?.post_type === 'story' ? 'story' : 'post';
  const errors: string[] = [];

  for (let i = 0; i < (media?.length || 0); i++) {
    const item = media[i];
    if (!item?.path || !isVideo(item.path)) {
      continue;
    }
    const meta = await probe(item.path);
    if (!meta) {
      continue;
    }
    const violations = instagramVideoViolations(meta, postType);
    if (violations.length) {
      errors.push(
        `Video ${i + 1} (${meta.width}x${meta.height}, ${asMbps(
          meta.bitrateBps
        )}, ${asMb(meta.sizeBytes)}, ${Math.round(
          meta.durationSec
        )}s) exceeds Instagram limits: ${violations.join('; ')}.`
      );
    }
  }

  return errors.length
    ? `${errors.join(' ')} Re-export at 1080x1920 H.264 under 25 Mbps.`
    : true;
}
