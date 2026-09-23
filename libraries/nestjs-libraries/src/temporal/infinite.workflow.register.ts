import { Global, Injectable, Module, OnModuleInit } from '@nestjs/common';
import { TemporalService } from 'nestjs-temporal-core';

@Injectable()
export class InfiniteWorkflowRegister implements OnModuleInit {
  constructor(private _temporalService: TemporalService) {}

  async onModuleInit(): Promise<void> {
    if (!!process.env.RUN_CRON) {
      // It holds no state between passes, so each start replaces the running
      // execution: after a deploy it runs the code just deployed, and the old
      // missingPostWorkflow gives way to its V2 under the same id.
      try {
        await this._temporalService.client
          ?.getRawClient()
          ?.workflow?.start('missingPostWorkflowV2', {
            workflowId: 'missing-post-workflow',
            taskQueue: 'main',
            workflowIdConflictPolicy: 'TERMINATE_EXISTING',
          });
      } catch (err) {}

      try {
        const retentionDays = Number(process.env.MEDIA_RETENTION_DAYS) || 30;
        await this._temporalService.client
          ?.getRawClient()
          ?.workflow?.start('mediaCleanupWorkflow', {
            workflowId: 'media-cleanup-workflow',
            taskQueue: 'main',
            args: [retentionDays],
          });
      } catch (err) {
        // Workflow already running — expected on restart
      }
    }
  }
}

@Global()
@Module({
  imports: [],
  controllers: [],
  providers: [InfiniteWorkflowRegister],
  get exports() {
    return this.providers;
  },
})
export class InfiniteWorkflowRegisterModule {}
