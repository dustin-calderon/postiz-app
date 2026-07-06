import { Global, Injectable, Module, OnModuleInit } from '@nestjs/common';
import { TemporalService } from 'nestjs-temporal-core';

@Injectable()
export class InfiniteWorkflowRegister implements OnModuleInit {
  constructor(private _temporalService: TemporalService) {}

  async onModuleInit(): Promise<void> {
    if (!!process.env.RUN_CRON) {
      try {
        await this._temporalService.client
          ?.getRawClient()
          ?.workflow?.start('missingPostWorkflow', {
            workflowId: 'missing-post-workflow',
            taskQueue: 'main',
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
