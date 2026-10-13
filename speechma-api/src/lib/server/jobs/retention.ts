import type { Job } from '$lib/types/tts';
import type { AudioStorage } from '../audio-storage';
import type { Config } from '../config';
import { localTimestamp } from '../timestamps';
import { sendWebhook } from '../webhooks';

export class RetentionWorker {
  private timers = new Map<string, ReturnType<typeof setTimeout>>();
  private sweepTimer?: ReturnType<typeof setTimeout>;
  private sweeping?: Promise<void>;
  private stopped = false;

  constructor(
    private readonly config: Config,
    private readonly jobs: Map<string, Job>,
    private readonly storage: AudioStorage,
    private readonly signal: AbortSignal
  ) {}

  start() {
    const tick = () => {
      this.sweepTimer = setTimeout(() => {
        this.sweeping = this.sweep().catch(() => {
          console.error('Audio retention sweep failed');
        }).finally(() => { if (!this.stopped) tick(); });
      }, 60_000);
      this.sweepTimer.unref();
    };
    tick();
  }

  schedule(id: string) {
    if (this.stopped) return;
    this.cancel(id);
    const timer = setTimeout(() => {
      this.timers.delete(id);
      void this.deleteCompleted(id).catch(() => console.error(`Auto-deletion failed for job ${id}`));
    }, this.config.autoDeleteDelayMs);
    timer.unref();
    this.timers.set(id, timer);
  }

  cancel(id: string) {
    clearTimeout(this.timers.get(id));
    this.timers.delete(id);
  }

  async stop() {
    this.stopped = true;
    clearTimeout(this.sweepTimer);
    for (const id of this.timers.keys()) this.cancel(id);
    await this.sweeping;
  }

  private async deleteCompleted(id: string) {
    if (!this.jobs.has(id)) return;
    await this.storage.remove(id);
    // Another cleanup path may have won the race while disk deletion was pending.
    if (!this.jobs.delete(id)) return;
    await sendWebhook(this.config.webhookUrl, {
      job_id: id, status: 'deleted', timestamp: localTimestamp(),
      message: 'Job and audio file automatically deleted after timeout'
    }, this.signal);
  }

  private async sweep() {
    const active = new Set([...this.jobs.values()]
      .filter((job) => job.status === 'processing').map((job) => job.job_id));
    const expired = await this.storage.removeExpired(this.config.autoDeleteDelayMs, active);
    for (const id of expired) {
      this.jobs.delete(id);
      this.cancel(id);
    }
    const now = Date.now();
    for (const [id, job] of this.jobs) {
      if (job.status === 'processing') continue;
      if ((job.end_time && now - job.end_time > 3_600_000) || now - job.created_at > 7_200_000) {
        await this.storage.remove(id);
        this.jobs.delete(id);
        this.cancel(id);
      }
    }
  }
}
