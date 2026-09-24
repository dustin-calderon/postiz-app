import {
  checkInstagramMedia,
  instagramImageViolation,
  instagramVideoViolations,
} from '@gitroom/nestjs-libraries/integrations/social/instagram.media.rules';
import type {
  ImageMetadata,
  VideoMetadata,
} from '@gitroom/nestjs-libraries/integrations/social.abstract';

const MiB = 1_048_576;

// A 1080x1920 reel like the ones the pipeline publishes.
const video = (over: Partial<VideoMetadata> = {}): VideoMetadata => ({
  width: 1080,
  height: 1920,
  durationSec: 30,
  bitrateBps: 8_000_000,
  sizeBytes: 30 * MiB,
  rotated: false,
  ...over,
});

const image = (over: Partial<ImageMetadata> = {}): ImageMetadata => ({
  width: 1080,
  height: 1350,
  orientation: 1,
  ...over,
});

describe('instagramVideoViolations', () => {
  it('accepts a reel within every limit', () => {
    expect(instagramVideoViolations(video(), 'reel')).toEqual([]);
  });

  it('limits the width, not the longest side', () => {
    expect(instagramVideoViolations(video({ height: 2340 }), 'reel')).toEqual(
      []
    );
    expect(
      instagramVideoViolations(video({ width: 3840, height: 2160 }), 'reel')
    ).toEqual([expect.stringContaining('width 3840px')]);
  });

  it('does not judge the width of a video turned 90°', () => {
    expect(
      instagramVideoViolations(
        video({ width: 2560, height: 1440, rotated: true }),
        'reel'
      )
    ).toEqual([]);
  });

  it('caps reels at 300 MiB and stories at 100 MiB', () => {
    expect(
      instagramVideoViolations(video({ sizeBytes: 300 * MiB }), 'reel')
    ).toEqual([]);
    expect(
      instagramVideoViolations(video({ sizeBytes: 301 * MiB }), 'reel')
    ).toEqual([expect.stringContaining('max for reels')]);
    expect(
      instagramVideoViolations(
        video({ sizeBytes: 101 * MiB, durationSec: 50 }),
        'story'
      )
    ).toEqual([expect.stringContaining('max for stories')]);
  });

  it('rejects under 3 s, but not when the duration could not be read', () => {
    expect(
      instagramVideoViolations(video({ durationSec: 2.5 }), 'reel')
    ).toEqual([expect.stringContaining('under the 3s minimum')]);
    expect(
      instagramVideoViolations(video({ durationSec: 0 }), 'reel')
    ).toEqual([]);
  });

  it('caps reels at 15 minutes and stories at 60 seconds', () => {
    expect(
      instagramVideoViolations(video({ durationSec: 901 }), 'reel')
    ).toEqual([expect.stringContaining('15 minutes')]);
    expect(
      instagramVideoViolations(video({ durationSec: 61 }), 'story')
    ).toEqual([expect.stringContaining('60 seconds')]);
  });

  it('holds a carousel video only to width and bitrate', () => {
    expect(
      instagramVideoViolations(
        video({ durationSec: 1, sizeBytes: 900 * MiB }),
        'carousel'
      )
    ).toEqual([]);
    expect(
      instagramVideoViolations(video({ bitrateBps: 30_000_000 }), 'carousel')
    ).toEqual([expect.stringContaining('bitrate')]);
  });
});

describe('instagramImageViolation', () => {
  it.each([
    ['4:5', 1080, 1350],
    ['1:1', 1080, 1080],
    ['1.91:1', 1080, 565],
    ['a hair taller than 4:5', 1080, 1352],
  ])('accepts %s', (_, width, height) => {
    expect(instagramImageViolation(image({ width, height }))).toBeNull();
  });

  it.each([
    ['3:4, an iPhone portrait photo', 3024, 4032],
    ['9:16', 1080, 1920],
    ['2:1', 2000, 1000],
  ])('rejects %s', (_, width, height) => {
    expect(instagramImageViolation(image({ width, height }))).toContain(
      'crop it'
    );
  });

  it('does not judge an image turned by its EXIF orientation', () => {
    expect(
      instagramImageViolation(
        image({ width: 4032, height: 3024, orientation: 6 })
      )
    ).toBeNull();
  });

  it('does not judge an image it could not measure', () => {
    expect(instagramImageViolation(image({ width: 0, height: 0 }))).toBeNull();
  });
});

describe('checkInstagramMedia', () => {
  const probes = (
    videos: Record<string, VideoMetadata | null>,
    images: Record<string, ImageMetadata | null>
  ) =>
    [
      async (p: string) => videos[p] ?? null,
      async (p: string) => images[p] ?? null,
    ] as const;

  it('passes a post whose media is within the limits', async () => {
    const [v, i] = probes({}, { 'a.jpg': image() });
    await expect(
      checkInstagramMedia([{ path: 'a.jpg' }], { post_type: 'post' }, v, i)
    ).resolves.toBe(true);
  });

  it('names the image that is out of range', async () => {
    const [v, i] = probes(
      {},
      { 'a.jpg': image(), 'b.jpg': image({ width: 1080, height: 1920 }) }
    );
    await expect(
      checkInstagramMedia(
        [{ path: 'a.jpg' }, { path: 'b.jpg' }],
        { post_type: 'post' },
        v,
        i
      )
    ).resolves.toContain('Image 2 (1080x1920)');
  });

  it('does not judge the images of a story', async () => {
    const [v, i] = probes(
      {},
      { 'a.jpg': image({ width: 1080, height: 1920 }) }
    );
    await expect(
      checkInstagramMedia([{ path: 'a.jpg' }], { post_type: 'story' }, v, i)
    ).resolves.toBe(true);
  });

  it('treats a single video as a reel and several as a carousel', async () => {
    const short = video({ durationSec: 2 });
    const [v, i] = probes({ 'a.mp4': short, 'b.mp4': short }, {});
    await expect(
      checkInstagramMedia([{ path: 'a.mp4' }], { post_type: 'post' }, v, i)
    ).resolves.toContain('Video 1');
    await expect(
      checkInstagramMedia(
        [{ path: 'a.mp4' }, { path: 'b.mp4' }],
        { post_type: 'post' },
        v,
        i
      )
    ).resolves.toBe(true);
  });

  it('lets through what cannot be measured', async () => {
    const [v, i] = probes({}, {});
    await expect(
      checkInstagramMedia(
        [{ path: 'a.mp4' }, { path: 'b.jpg' }],
        { post_type: 'post' },
        v,
        i
      )
    ).resolves.toBe(true);
  });
});
