import { randomUUID } from 'node:crypto';
import type { Job, ListedJob, TtsRequest } from '$lib/types/tts';
import type { Config } from '../config';
import type { AudioStorage } from '../audio-storage';
import type { SpeechProvider } from '../tts/provider';
import { localTimestamp } from '../timestamps';
import { RetentionWorker } from './retention';
import { processJob } from './processor';

export class JobManager {
  readonly jobs = new Map<string, Job>();
  private readonly queue: Job[] = [];
  private readonly active = new Set<Promise<void>>();
  private readonly shutdown = new AbortController();
  private readonly retention: RetentionWorker;

  constructor(
    readonly config: Config,
    readonly storage: AudioStorage,
    private readonly provider: SpeechProvider | null
  ) {
    this.retention = new RetentionWorker(config, this.jobs, storage, this.shutdown.signal);
  }

  get providerReady() { return this.provider !== null && !this.shutdown.signal.aborted; }
  get queueSize() { return this.queue.length; }
  get workerSlotsInUse() { return this.active.size; }
  get processingJobsCount() {
    let count = 0;
    for (const job of this.jobs.values()) if (job.status === 'processing') count++;
    return count;
  }

  start() { this.retention.start(); }

  add(request: TtsRequest) {
    if (!this.providerReady) throw new Error('Speech provider is not configured');
    const job: Job = { job_id: randomUUID(), request, status: 'queued', created_at: Date.now() };
    this.jobs.set(job.job_id, job);
    this.queue.push(job);
    queueMicrotask(() => this.dispatch());
    return job.job_id;
  }

  forget(id: string) {
    this.jobs.delete(id);
    this.retention.cancel(id);
  }

  async list(): Promise<ListedJob[]> {
    const files = await this.storage.list();
    const fileIds = new Set(files.map((job) => job.job_id));
    const memory: ListedJob[] = [...this.jobs.values()]
      .filter((job) => !fileIds.has(job.job_id))
      .map((job) => {
        const characters = [...job.request.text];
        return {
          job_id: job.job_id, status: job.status, audio_exists: false,
          created_at: localTimestamp(job.created_at),
          text: characters.slice(0, 100).join('') + (characters.length > 100 ? '...' : '')
        };
      });
    return [...files, ...memory]
      .sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 50);
  }

  async stop() {
    this.shutdown.abort(new Error('Server is shutting down'));
    this.queue.length = 0;
    await Promise.allSettled([...this.active, this.retention.stop()]);
  }

  private dispatch() {
    if (!this.providerReady || !this.provider) return;
    while (this.active.size < this.config.maxConcurrent && this.queue.length) {
      // All submissions have the same priority; FIFO avoids the source's aged-job requeue loop.
      const job = this.queue.shift()!;
      if (!this.jobs.has(job.job_id)) continue;
      const task = processJob(job, this.provider, this.storage, this.retention, this.config, this.shutdown.signal)
        .catch(() => console.error(`Job processing failed for ${job.job_id}`))
        .finally(() => {
          this.active.delete(task);
          this.dispatch();
        });
      this.active.add(task);
    }
  }
}
