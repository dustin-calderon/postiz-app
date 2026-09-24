import { isVideo } from '@gitroom/helpers/utils/has.extension';
import type {
  ImageMetadata,
  ValidityMedia,
  VideoMetadata,
} from '@gitroom/nestjs-libraries/integrations/social.abstract';

/**
 * Instagram's limits for published media, from Meta's reference (IG User
 * Media: image, reel and story specifications) and the errors it answers with
 * (2207009 for the aspect ratio of an image). Meta applies them when the post
 * publishes, hours after it was scheduled; checking them at post creation
 * surfaces the problem while it can still be fixed.
 * https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media
 *
 * Only what needs a person to decide is checked here: a duration, how to crop
 * an image. What a conversion fixes (format, codec, bitrate) is fixed before
 * upload, not rejected here.
 *
 * Sizes are read as MiB: Meta writes "300MB" without saying which, and a rule
 * that blocks must not block what Meta may accept.
 */
export const INSTAGRAM_MEDIA_LIMITS = {
  maxVideoWidthPx: 1920,
  maxVideoBitrateBps: 25_000_000,
  // Reel and story specifications. A video inside a carousel is neither, and
  // the reference gives it no size or duration of its own.
  maxReelBytes: 300 * 1_048_576,
  maxStoryVideoBytes: 100 * 1_048_576,
  minVideoDurationSec: 3,
  maxReelDurationSec: 900,
  maxStoryDurationSec: 60,
  // Feed images, carousel items included. Stories only have a recommendation.
  minImageAspect: 4 / 5,
  maxImageAspect: 1.91,
} as const;

// An image a hair outside the range (1080x1352) is not evidence enough to
// block: Meta's own rounding is not documented.
const ASPECT_TOLERANCE = 0.01;

const asMbps = (bps: number) => `${(bps / 1_000_000).toFixed(1)} Mbps`;
const asMb = (bytes: number) => `${(bytes / 1_048_576).toFixed(1)} MB`;

export type InstagramVideoKind = 'reel' | 'story' | 'carousel';

/** Pure: measured metadata → readable limit violations (empty = compliant). */
export function instagramVideoViolations(
  meta: VideoMetadata,
  kind: InstagramVideoKind
): string[] {
  const limits = INSTAGRAM_MEDIA_LIMITS;
  const violations: string[] = [];

  if (meta.width > limits.maxVideoWidthPx) {
    violations.push(
      `width ${meta.width}px exceeds ${limits.maxVideoWidthPx}px max`
    );
  }
  if (meta.bitrateBps > limits.maxVideoBitrateBps) {
    violations.push(
      `video bitrate ${asMbps(meta.bitrateBps)} exceeds ${asMbps(
        limits.maxVideoBitrateBps
      )} max`
    );
  }
  if (kind === 'carousel') {
    return violations;
  }

  const maxBytes =
    kind === 'story' ? limits.maxStoryVideoBytes : limits.maxReelBytes;
  if (meta.sizeBytes > maxBytes) {
    violations.push(
      `file size ${asMb(meta.sizeBytes)} exceeds ${asMb(maxBytes)} max for ${
        kind === 'story' ? 'stories' : 'reels'
      }`
    );
  }
  // 0 means the duration could not be read: no evidence, no violation.
  if (meta.durationSec > 0 && meta.durationSec < limits.minVideoDurationSec) {
    violations.push(
      `duration ${meta.durationSec.toFixed(1)}s is under the ${
        limits.minVideoDurationSec
      }s minimum`
    );
  }
  const maxDuration =
    kind === 'story' ? limits.maxStoryDurationSec : limits.maxReelDurationSec;
  if (meta.durationSec > maxDuration) {
    violations.push(
      `duration ${Math.round(meta.durationSec)}s exceeds ${
        kind === 'story' ? '60 seconds max for stories' : '15 minutes max'
      }`
    );
  }

  return violations;
}

/**
 * Pure: a feed image's aspect ratio outside Instagram's range, or null. An
 * EXIF orientation that turns the image (5 to 8) is not judged: which of the
 * two sizes Meta checks is not documented, and a guess would block valid posts.
 */
export function instagramImageViolation(meta: ImageMetadata): string | null {
  const { minImageAspect, maxImageAspect } = INSTAGRAM_MEDIA_LIMITS;
  if (!meta.width || !meta.height || meta.orientation >= 5) {
    return null;
  }
  const aspect = meta.width / meta.height;
  if (
    aspect >= minImageAspect * (1 - ASPECT_TOLERANCE) &&
    aspect <= maxImageAspect * (1 + ASPECT_TOLERANCE)
  ) {
    return null;
  }
  return `aspect ratio ${aspect.toFixed(2)} is outside the 4:5 (0.80) to 1.91:1 range Instagram accepts in the feed; crop it`;
}

/**
 * Validates a post's media against Instagram's limits using the provided
 * probes. Anything a probe cannot measure is skipped (fail-open: only actual
 * evidence blocks a post). Returns true or an error message with the measured
 * values — that text travels into the Notion error_log, so it must be
 * actionable on its own.
 */
export async function checkInstagramMedia(
  media: ValidityMedia[],
  settings: { post_type?: string } | undefined,
  probeVideo: (path: string) => Promise<VideoMetadata | null>,
  probeImage: (path: string) => Promise<ImageMetadata | null>
): Promise<string | true> {
  const isStory = settings?.post_type === 'story';
  const kind: InstagramVideoKind = isStory
    ? 'story'
    : (media?.length || 0) > 1
    ? 'carousel'
    : 'reel';
  const errors: string[] = [];

  for (let i = 0; i < (media?.length || 0); i++) {
    const item = media[i];
    if (!item?.path) {
      continue;
    }
    if (isVideo(item.path)) {
      const meta = await probeVideo(item.path);
      if (!meta) {
        continue;
      }
      const violations = instagramVideoViolations(meta, kind);
      if (violations.length) {
        errors.push(
          `Video ${i + 1} (${meta.width}x${meta.height}, ${asMbps(
            meta.bitrateBps
          )}, ${asMb(meta.sizeBytes)}, ${Math.round(
            meta.durationSec
          )}s) exceeds Instagram limits: ${violations.join('; ')}.`
        );
      }
      continue;
    }
    if (isStory) {
      continue;
    }
    const meta = await probeImage(item.path);
    if (!meta) {
      continue;
    }
    const violation = instagramImageViolation(meta);
    if (violation) {
      errors.push(
        `Image ${i + 1} (${meta.width}x${meta.height}): ${violation}.`
      );
    }
  }

  return errors.length ? errors.join(' ') : true;
}
