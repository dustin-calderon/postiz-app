import { HttpException, Injectable } from '@nestjs/common';
import { MediaRepository } from '@gitroom/nestjs-libraries/database/prisma/media/media.repository';
import { OpenaiService } from '@gitroom/nestjs-libraries/openai/openai.service';
import { SubscriptionService } from '@gitroom/nestjs-libraries/database/prisma/subscriptions/subscription.service';
import { Organization } from '@prisma/client';
import { SaveMediaInformationDto } from '@gitroom/nestjs-libraries/dtos/media/save.media.information.dto';
import { MoveMediaDto } from '@gitroom/nestjs-libraries/dtos/media/move.media.dto';
import { RenameFolderDto } from '@gitroom/nestjs-libraries/dtos/media/rename.folder.dto';
import { VideoManager } from '@gitroom/nestjs-libraries/videos/video.manager';
import { VideoDto } from '@gitroom/nestjs-libraries/dtos/videos/video.dto';
import { UploadFactory } from '@gitroom/nestjs-libraries/upload/upload.factory';
import {
  AuthorizationActions,
  Sections,
  SubscriptionException,
} from '@gitroom/backend/services/auth/permissions/permission.exception.class';

@Injectable()
export class MediaService {
  private storage = UploadFactory.createStorage();

  constructor(
    private _mediaRepository: MediaRepository,
    private _openAi: OpenaiService,
    private _subscriptionService: SubscriptionService,
    private _videoManager: VideoManager
  ) {}

  async deleteMedia(org: string, id: string) {
    return this._mediaRepository.deleteMedia(org, id);
  }

  getMediaById(id: string) {
    return this._mediaRepository.getMediaById(id);
  }

  async generateImage(
    prompt: string,
    org: Organization,
    generatePromptFirst?: boolean
  ) {
    const generating = await this._subscriptionService.useCredit(
      org,
      'ai_images',
      async () => {
        if (generatePromptFirst) {
          prompt = await this._openAi.generatePromptForPicture(prompt);
          console.log('Prompt:', prompt);
        }
        return this._openAi.generateImage(prompt);
      }
    );

    return generating;
  }

  saveFile(org: string, fileName: string, filePath: string, originalName?: string, folder?: string) {
    return this._mediaRepository.saveFile(org, fileName, filePath, originalName, folder);
  }

  getMedia(org: string, page: number, search?: string, folder?: string) {
    return this._mediaRepository.getMedia(org, page, search, folder);
  }

  getFolders(org: string) {
    return this._mediaRepository.getFolders(org);
  }

  moveMedia(org: string, dto: MoveMediaDto) {
    return this._mediaRepository.moveMedia(org, dto);
  }

  renameFolder(org: string, dto: RenameFolderDto) {
    return this._mediaRepository.renameFolder(org, dto);
  }

  saveMediaInformation(org: string, data: SaveMediaInformationDto) {
    return this._mediaRepository.saveMediaInformation(org, data);
  }

  getVideoOptions() {
    return this._videoManager.getAllVideos();
  }

  async generateVideoAllowed(org: Organization, type: string) {
    const video = this._videoManager.getVideoByName(type);
    if (!video) {
      throw new Error(`Video type ${type} not found`);
    }

    if (!video.trial && org.isTrailing) {
      throw new HttpException('This video is not available in trial mode', 406);
    }

    return true;
  }

  async generateVideo(org: Organization, body: VideoDto) {
    const totalCredits = await this._subscriptionService.checkCredits(
      org,
      'ai_videos'
    );

    if (totalCredits.credits <= 0) {
      throw new SubscriptionException({
        action: AuthorizationActions.Create,
        section: Sections.VIDEOS_PER_MONTH,
      });
    }

    const video = this._videoManager.getVideoByName(body.type);
    if (!video) {
      throw new Error(`Video type ${body.type} not found`);
    }

    if (!video.trial && org.isTrailing) {
      throw new HttpException('This video is not available in trial mode', 406);
    }

    console.log(body.customParams);
    await video.instance.processAndValidate(body.customParams);
    console.log('no err');

    return await this._subscriptionService.useCredit(
      org,
      'ai_videos',
      async () => {
        const loadedData = await video.instance.process(
          body.output,
          body.customParams
        );

        const file = await this.storage.uploadSimple(loadedData);
        return this.saveFile(org.id, file.split('/').pop(), file);
      }
    );
  }

  async videoFunction(identifier: string, functionName: string, body: any) {
    const video = this._videoManager.getVideoByName(identifier);
    if (!video) {
      throw new Error(`Video with identifier ${identifier} not found`);
    }

    // @ts-ignore
    const functionToCall = video.instance[functionName];
    if (
      typeof functionToCall !== 'function' ||
      this._videoManager.checkAvailableVideoFunction(functionToCall)
    ) {
      throw new HttpException(
        `Function ${functionName} not found on video instance`,
        400
      );
    }

    return functionToCall(body);
  }

  /**
   * Finds and removes media files that are no longer needed.
   *
   * Phase 1 — Stale active media:
   *   1. Query stale media candidates (old, no FK refs, no active Post.image reference)
   *   2. Remove physical files from storage (R2/local)
   *   3. Soft-delete DB records
   *
   * Phase 2 — Orphaned soft-deleted media:
   *   1. Find media that was manually deleted by users (deletedAt set) but whose
   *      physical blobs were never cleaned up (the existing DELETE endpoint only
   *      sets deletedAt without removing the file)
   *   2. Remove physical files from storage
   *   3. Hard-delete DB records (already soft-deleted, no longer auditable)
   *
   * @param retentionDays Minimum age (in days) before media becomes eligible. Default: 30.
   * @returns Summary with counts of processed, removed, and failed items.
   */
  async cleanupStaleMedia(retentionDays = 30): Promise<{
    candidates: number;
    removed: number;
    failed: number;
    orphansRemoved: number;
    errors: string[];
  }> {
    const errors: string[] = [];

    // === Phase 1: Stale active media ===
    const staleMedia = await this._mediaRepository.findStalePublishedMedia(retentionDays);

    const removedIds: string[] = [];
    for (const media of staleMedia) {
      try {
        await this.storage.removeFile(media.path);

        if (media.thumbnail && media.thumbnail !== media.path) {
          try {
            await this.storage.removeFile(media.thumbnail);
          } catch {
            // Thumbnail removal failure is non-critical
          }
        }

        removedIds.push(media.id);
      } catch (err: any) {
        errors.push(`Phase1 ${media.id} (${media.path}): ${err?.message || 'unknown'}`);
      }
    }

    if (removedIds.length > 0) {
      await this._mediaRepository.softDeleteMediaBatch(removedIds);
    }

    // === Phase 2: Orphaned soft-deleted media (blobs never cleaned) ===
    const orphanedMedia = await this._mediaRepository.findOrphanedSoftDeletedMedia();

    const purgedIds: string[] = [];
    for (const media of orphanedMedia) {
      try {
        await this.storage.removeFile(media.path);

        if (media.thumbnail && media.thumbnail !== media.path) {
          try {
            await this.storage.removeFile(media.thumbnail);
          } catch {
            // Thumbnail removal failure is non-critical
          }
        }

        purgedIds.push(media.id);
      } catch (err: any) {
        errors.push(`Phase2 ${media.id} (${media.path}): ${err?.message || 'unknown'}`);
      }
    }

    if (purgedIds.length > 0) {
      await this._mediaRepository.hardDeleteMediaBatch(purgedIds);
    }

    return {
      candidates: staleMedia.length,
      removed: removedIds.length,
      failed: errors.length,
      orphansRemoved: purgedIds.length,
      errors,
    };
  }
}
