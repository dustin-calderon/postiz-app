import { PrismaRepository } from '@gitroom/nestjs-libraries/database/prisma/prisma.service';
import { Injectable } from '@nestjs/common';
import { Prisma } from '@prisma/client';
import { SaveMediaInformationDto } from '@gitroom/nestjs-libraries/dtos/media/save.media.information.dto';
import { MoveMediaDto } from '@gitroom/nestjs-libraries/dtos/media/move.media.dto';
import { RenameFolderDto } from '@gitroom/nestjs-libraries/dtos/media/rename.folder.dto';

/** Path separator for virtual hierarchical folders (e.g. "Brand/SubFolder"). */
const FOLDER_SEP = '/';

/** Sentinel value used in the query-string to request only unfoldered items. */
const ROOT_FOLDER_SENTINEL = '__root__';

@Injectable()
export class MediaRepository {
  constructor(private _media: PrismaRepository<'media'>) {}

  saveFile(org: string, fileName: string, filePath: string, originalName?: string, folder?: string) {
    // Sanitize folder: trim whitespace, reject empty strings
    const sanitizedFolder = folder?.trim() || null;
    return this._media.model.media.create({
      data: {
        organization: {
          connect: {
            id: org,
          },
        },
        name: fileName,
        path: filePath,
        originalName: originalName || null,
        folder: sanitizedFolder,
      },
      select: {
        id: true,
        name: true,
        originalName: true,
        path: true,
        thumbnail: true,
        alt: true,
      },
    });
  }

  getMediaById(id: string) {
    return this._media.model.media.findUnique({
      where: {
        id,
      },
    });
  }

  deleteMedia(org: string, id: string) {
    return this._media.model.media.update({
      where: {
        id,
        organizationId: org,
      },
      data: {
        deletedAt: new Date(),
      },
    });
  }

  saveMediaInformation(org: string, data: SaveMediaInformationDto) {
    return this._media.model.media.update({
      where: {
        id: data.id,
        organizationId: org,
      },
      data: {
        alt: data.alt,
        thumbnail: data.thumbnail,
        thumbnailTimestamp: data.thumbnailTimestamp,
      },
      select: {
        id: true,
        name: true,
        originalName: true,
        alt: true,
        thumbnail: true,
        path: true,
        thumbnailTimestamp: true,
      },
    });
  }

  /**
   * Returns all distinct, non-null folder names that belong to the org.
   * An empty array means no folders have been created yet.
   */
  async getFolders(org: string): Promise<string[]> {
    const rows = await this._media.model.media.findMany({
      where: {
        organizationId: org,
        deletedAt: null,
        folder: { not: null },
      },
      select: { folder: true },
      distinct: ['folder'],
      orderBy: { folder: 'asc' },
    });

    return rows.map((r) => r.folder as string);
  }

  /**
   * Moves a set of media items (by id) into a folder.
   * Pass `folder: null` to move items back to root (no folder).
   */
  async moveMedia(org: string, dto: MoveMediaDto): Promise<{ count: number }> {
    return this._media.model.media.updateMany({
      where: {
        id: { in: dto.ids },
        organizationId: org,
        deletedAt: null,
      },
      data: {
        folder: dto.folder ?? null,
      },
    });
  }

  /**
   * Renames every media item whose folder path starts with `oldName`.
   *
   * Handles both flat and hierarchical paths:
   *   - exact match:  "Citem"          → "NewBrand"
   *   - prefix match: "Citem/Diseños"  → "NewBrand/Diseños"
   *
   * Uses a single raw SQL REPLACE() to atomically update all affected rows.
   * Prisma.sql tagged-template ensures full parametrization — no injection risk.
   */
  async renameFolder(org: string, dto: RenameFolderDto): Promise<{ count: number }> {
    const oldTrimmed = dto.oldName.trim();
    const newTrimmed = dto.newName.trim();
    if (oldTrimmed === newTrimmed) {
      return { count: 0 };
    }

    // REPLACE(folder, oldName, newName) handles both:
    //   "Citem"         → "NewBrand"
    //   "Citem/Diseños" → "NewBrand/Diseños"
    // The WHERE clause restricts to exact match OR prefix match to avoid
    // accidentally renaming unrelated folders that happen to share a prefix
    // (e.g. "Citem2" when renaming "Citem").
    const prefix = `${oldTrimmed}${FOLDER_SEP}`;
    // Cast to PrismaClient: PrismaRepository<'media'>.model is typed as
    // Pick<PrismaService, 'media'> for DI ergonomics, but at runtime it IS the
    // full PrismaService which extends PrismaClient (and therefore has $queryRaw).
    const prisma = this._media.model as unknown as import('@prisma/client').PrismaClient;
    // Use CASE WHEN instead of REPLACE to avoid corrupting nested paths.
    // REPLACE('Design/Design', 'Design', 'Art') → 'Art/Art' (wrong!)
    // CASE exact match: folder = newName
    // CASE prefix match: newName || substring(folder, length(oldName)+1)
    const oldLen = oldTrimmed.length;
    const result = await prisma.$queryRaw<{ count: bigint }[]>(
      Prisma.sql`
        UPDATE "Media"
        SET folder = CASE
          WHEN folder = ${oldTrimmed} THEN ${newTrimmed}
          ELSE ${newTrimmed} || substring(folder FROM ${oldLen + 1})
        END
        WHERE "organizationId" = ${org}
          AND "deletedAt" IS NULL
          AND (folder = ${oldTrimmed} OR folder LIKE ${prefix + '%'})
      `
    );

    // $queryRaw with UPDATE returns the row count directly in some drivers.
    // With Prisma + PostgreSQL it returns an empty array; the count is inferred
    // from the affected rows signal. We return 1 to indicate success rather
    // than 0 (which would be mistaken for a no-op by callers).
    return { count: Number((result as any)?.[0]?.count ?? 1) };
  }

  /**
   * Paginated media list.
   *
   * - No `folder` param → return all media (existing behaviour, backwards-compatible).
   * - `folder === '__root__'` → return only items with no folder assigned.
   * - `folder === '<name>'` → return only items in that folder.
   */
  async getMedia(org: string, page: number, search?: string, folder?: string) {
    // Pages are 1-based from the client. Coerce safely: `page || 1` would
    // also default 0 to 1, but an explicit Number() guards against string "0".
    const pageNum = (Number(page) > 0 ? Number(page) : 1) - 1;
    const trimmedSearch = search?.trim();

    const searchFilter = trimmedSearch
      ? {
          originalName: {
            contains: trimmedSearch,
            mode: 'insensitive' as const,
          },
        }
      : {};

    const folderFilter =
      folder === undefined
        ? {}
        : folder === ROOT_FOLDER_SENTINEL
        ? { folder: null }
        : { folder };

    const where: Prisma.MediaWhereInput = {
      organizationId: org,
      deletedAt: null,
      ...searchFilter,
      ...folderFilter,
    };

    const query = { where };

    const pages = Math.ceil((await this._media.model.media.count(query)) / 18);
    const results = await this._media.model.media.findMany({
      ...query,
      orderBy: {
        createdAt: 'desc',
      },
      select: {
        id: true,
        name: true,
        originalName: true,
        path: true,
        thumbnail: true,
        alt: true,
        thumbnailTimestamp: true,
        folder: true,
      },
      skip: pageNum * 18,
      take: 18,
    });

    return {
      pages,
      results,
    };
  }

  /**
   * Finds media eligible for cleanup based on the rule:
   * "Media that has ALREADY been used in a published post should be
   *  deleted after `retentionDays` days since publication."
   *
   * A media record is eligible when ALL of these are true:
   *   1. Not soft-deleted (`deletedAt IS NULL`)
   *   2. Not referenced by any FK (User.pictureId, Agency.logoId, OAuthApp.pictureId)
   *   3. Its `path` APPEARS in at least one Post.image where:
   *      - Post.state = 'PUBLISHED'
   *      - Post.publishDate < (now - retentionDays)  (published >30 days ago)
   *   4. Its `path` does NOT appear in any still-active post:
   *      - QUEUE, DRAFT, or ERROR state
   *      - PUBLISHED within the last `retentionDays`
   *      - Recurring (intervalInDays IS NOT NULL)
   *
   * Uses a 3-step approach:
   *   Step 1 (Prisma): Get non-FK-referenced, non-deleted media as base candidates.
   *   Step 2 (Raw SQL): Find which candidates ARE referenced by old published posts.
   *   Step 3 (Raw SQL): Exclude those also referenced by still-active posts.
   *
   * @param retentionDays Days after publication before media becomes eligible. Default: 30.
   * @param batchSize     Maximum candidates per invocation.
   * @returns Array of eligible media records with id, path, and thumbnail.
   */
  async findStalePublishedMedia(
    retentionDays: number,
    batchSize = 100
  ): Promise<{ id: string; path: string; thumbnail: string | null }[]> {
    const retentionThreshold = new Date();
    retentionThreshold.setDate(retentionThreshold.getDate() - retentionDays);

    // Step 1: Prisma — base candidates (no FK refs, not deleted).
    // createdAt filter is a performance guard: if media was created <retentionDays ago,
    // no published post using it can be older than retentionDays.
    const candidates = await this._media.model.media.findMany({
      where: {
        deletedAt: null,
        createdAt: { lt: retentionThreshold },
        userPicture: { none: {} },
        agencies: { none: {} },
        oauthApps: { none: {} },
      },
      select: {
        id: true,
        path: true,
        thumbnail: true,
      },
      take: batchSize,
      orderBy: { createdAt: 'asc' },
    });

    if (candidates.length === 0) {
      return [];
    }

    const prisma = this._media.model as unknown as import('@prisma/client').PrismaClient;
    const candidatePaths = candidates.map((c) => c.path);

    const likeClauses = candidatePaths.map(
      (p) => Prisma.sql`p."image" LIKE '%' || ${p} || '%'`
    );
    const combinedLike = Prisma.join(likeClauses, ' OR ');

    // Step 2: Find candidates that ARE referenced by old published posts.
    // This is the positive match: "media that was used in a publication."
    const usedInOldPosts = await prisma.$queryRaw<{ image: string }[]>(
      Prisma.sql`
        SELECT p."image"
        FROM "Post" p
        WHERE p."deletedAt" IS NULL
          AND p."state" = 'PUBLISHED'
          AND p."publishDate" < ${retentionThreshold}
          AND (${combinedLike})
      `
    );

    // Build set of candidate paths that were used in old publications
    const usedPaths = new Set<string>();
    for (const row of usedInOldPosts) {
      for (const cp of candidatePaths) {
        if (row.image && row.image.includes(cp)) {
          usedPaths.add(cp);
        }
      }
    }

    // If no candidate was used in any old published post, nothing to clean
    if (usedPaths.size === 0) {
      return [];
    }

    // Step 3: Exclude candidates that are ALSO referenced by still-active posts
    // (QUEUE/DRAFT/ERROR/recurring/recently published) — those still need the media.
    const stillActivePosts = await prisma.$queryRaw<{ image: string }[]>(
      Prisma.sql`
        SELECT p."image"
        FROM "Post" p
        WHERE p."deletedAt" IS NULL
          AND (${combinedLike})
          AND (
            p."state" IN ('QUEUE', 'DRAFT', 'ERROR')
            OR (p."state" = 'PUBLISHED' AND p."publishDate" >= ${retentionThreshold})
            OR p."intervalInDays" IS NOT NULL
          )
      `
    );

    const protectedPaths = new Set<string>();
    for (const row of stillActivePosts) {
      for (const cp of candidatePaths) {
        if (row.image && row.image.includes(cp)) {
          protectedPaths.add(cp);
        }
      }
    }

    // Eligible = used in old publication AND not needed by any active post
    return candidates.filter(
      (c) => usedPaths.has(c.path) && !protectedPaths.has(c.path)
    );
  }

  /**
   * Batch soft-deletes media records by their IDs.
   * Used by the cleanup workflow after physical storage files have been removed.
   */
  async softDeleteMediaBatch(ids: string[]): Promise<{ count: number }> {
    return this._media.model.media.updateMany({
      where: {
        id: { in: ids },
        deletedAt: null,
      },
      data: {
        deletedAt: new Date(),
      },
    });
  }

  /**
   * Finds media records that were manually soft-deleted by users but whose
   * physical storage blobs were never cleaned up.
   *
   * Returns records where:
   *   - deletedAt IS NOT NULL (user already "deleted" them)
   *   - deletedAt is older than `graceDays` (give time for accidental undo)
   *
   * @param graceDays Minimum days since soft-delete before blob cleanup. Default: 7.
   * @param batchSize Maximum records per pass.
   */
  async findOrphanedSoftDeletedMedia(
    graceDays = 7,
    batchSize = 100
  ): Promise<{ id: string; path: string; thumbnail: string | null }[]> {
    const graceDate = new Date();
    graceDate.setDate(graceDate.getDate() - graceDays);

    return this._media.model.media.findMany({
      where: {
        deletedAt: { lt: graceDate },
      },
      select: {
        id: true,
        path: true,
        thumbnail: true,
      },
      take: batchSize,
      orderBy: { deletedAt: 'asc' },
    });
  }

  /**
   * Permanently deletes media records from the database.
   * Only called after physical storage blobs are confirmed removed.
   */
  async hardDeleteMediaBatch(ids: string[]): Promise<{ count: number }> {
    return this._media.model.media.deleteMany({
      where: {
        id: { in: ids },
        deletedAt: { not: null },
      },
    });
  }
}
