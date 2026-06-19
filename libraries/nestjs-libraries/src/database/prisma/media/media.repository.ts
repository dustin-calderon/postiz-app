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

  saveFile(org: string, fileName: string, filePath: string, originalName?: string) {
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
    const result = await prisma.$queryRaw<{ count: bigint }[]>(
      Prisma.sql`
        UPDATE "Media"
        SET folder = REPLACE(folder, ${oldTrimmed}, ${newTrimmed})
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
}
