import { requestJson } from './test-api';
import type { TtsRequest } from '$lib/types/tts';
import type { LoadJob, LoadLimits, LoadSnapshot, ServerMetrics } from '$lib/types/load-test';

export const emptyLoadSnapshot = (): LoadSnapshot => ({
  started: null, target: 0, pending: 0, outstanding: 0, attempted: 0,
  completed: 0, failed: 0, unknown: 0, rejected: 0, peakOutstanding: 0,
  p50Seconds: null, p95Seconds: null, draining: false, ended: false, locked: false,
  message: 'Ready. Add a batch or set a maintained target to start.', jobs: []
});

// This client controls submissions only. Every job still passes through the normal API queue.
export class BrowserLoadTest {
  private state = emptyLoadSnapshot();
  private jobs: LoadJob[] = [];
  private active = new Map<number, LoadJob>();
  private controller = new AbortController();
  private deadlineTimer?: ReturnType<typeof setTimeout>;
  private disposed = false;
  private samples: Array<{ metrics: ServerMetrics; completed: number; outstanding: number; target: number }> = [];

  constructor(
    private apiKey: string,
    private speeches: TtsRequest[],
    readonly limits: LoadLimits,
    private onchange: (snapshot: LoadSnapshot) => void
  ) {}

  setTarget(count: number) {
    if (!this.canSubmit()) return;
    this.start();
    this.state.target = count;
    this.state.message = count ? `Maintaining ${count} outstanding test jobs.` : 'Maintained target is zero.';
    this.pump();
    this.publish();
  }

  add(count: number) {
    if (!this.canSubmit()) return;
    this.start();
    this.state.pending += count;
    this.state.message = `Added ${count} jobs to this batch.`;
    this.pump();
    this.publish();
  }

  pause(message = 'Paused. Accepted jobs continue; no new jobs will be submitted.') {
    this.state.target = 0;
    this.state.pending = 0;
    this.state.message = message;
    this.publish();
  }

  drain() {
    this.state.draining = true;
    this.pause('Draining accepted jobs.');
    this.finishIfDrained();
  }

  recordMetrics(metrics: ServerMetrics) {
    if (this.state.started && !this.state.ended) {
      this.samples.push({ metrics, completed: this.state.completed, outstanding: this.active.size, target: this.state.target });
    }
  }

  report() {
    return {
      createdAt: new Date().toISOString(), limits: this.limits,
      scriptCharacters: this.speeches.map((speech) => [...speech.text].length),
      summary: this.snapshot(), jobs: this.jobs, samples: this.samples,
      note: 'API-reported completion only; audio validity/content were not checked. Server metrics are per process. Speech text and API key are excluded.'
    };
  }

  dispose() {
    this.disposed = true;
    clearTimeout(this.deadlineTimer);
    this.controller.abort();
  }

  private canSubmit() { return !this.disposed && !this.state.ended && !this.state.draining && !this.state.locked; }

  private start() {
    if (this.state.started) return;
    this.state.started = Date.now();
    this.deadlineTimer = setTimeout(() => {
      this.state.draining = true;
      this.pause('Time limit reached. Draining accepted jobs.');
      this.finishIfDrained();
    }, this.limits.durationSeconds * 1000);
  }

  private pump() {
    if (!this.canSubmit()) return;
    if (this.state.started && Date.now() >= this.state.started + this.limits.durationSeconds * 1000) {
      this.drain(); return;
    }
    while (this.active.size < this.limits.maxConcurrent && (this.state.pending > 0 || this.active.size < this.state.target)) {
      if (this.state.attempted >= this.limits.maxJobs) {
        this.state.draining = true;
        this.pause('Job budget reached. Draining accepted jobs.');
        this.finishIfDrained();
        return;
      }
      if (this.state.pending > 0) this.state.pending--;
      const job: LoadJob = { attempt: ++this.state.attempted, id: null, status: 'submitting', started: Date.now() };
      this.jobs.push(job);
      this.active.set(job.attempt, job);
      this.state.peakOutstanding = Math.max(this.state.peakOutstanding, this.active.size);
      void this.run(job);
    }
  }

  private async api(path: string, options: RequestInit = {}) {
    return requestJson(path, this.apiKey, {
      ...options, redirect: 'error',
      signal: AbortSignal.any([this.controller.signal, AbortSignal.timeout(15000)])
    });
  }

  private unknown(job: LoadJob, message: string) {
    job.status = 'unknown';
    job.message = message;
    this.state.unknown++;
    this.state.locked = true;
    this.pause(`${message} New submissions are locked; confirm server work has finished before a new run.`);
  }

  private async run(job: LoadJob) {
    try {
      const speech = this.speeches[(job.attempt - 1) % this.speeches.length];
      const result = await this.api('/tts', { method: 'POST', body: JSON.stringify(speech) });
      if (!result.ok) {
        if (result.status >= 400 && result.status < 500) {
          job.status = 'rejected';
          job.message = `HTTP ${result.status}`;
          this.state.rejected++;
          this.pause(`Submission rejected (HTTP ${result.status}).`);
        } else this.unknown(job, `Submission returned HTTP ${result.status}; acceptance is uncertain.`);
        return;
      }
      const body = result.body as { job_id?: string } | null;
      if (typeof body?.job_id !== 'string' || !body.job_id) {
        this.unknown(job, 'Submission returned no job ID.'); return;
      }
      job.id = body.job_id;
      job.status = 'queued';
      this.publish();
      const expires = job.started + this.limits.jobTimeoutSeconds * 1000;
      while (!this.disposed && Date.now() < expires) {
        const statusResult = await this.api(`/tts/status/${encodeURIComponent(job.id)}`);
        const status = (statusResult.body as { status?: string } | null)?.status;
        if (!statusResult.ok || !status || !['queued', 'processing', 'completed', 'failed'].includes(status)) {
          this.unknown(job, `Job status unavailable (HTTP ${statusResult.status}).`); return;
        }
        job.status = status as LoadJob['status'];
        if (status === 'completed' || status === 'failed') {
          job.finished = Date.now();
          this.state[status]++;
          if (status === 'failed') this.pause('A speech job failed. Inspect the run before resuming.');
          return;
        }
        this.publish();
        await new Promise<void>((resolve) => {
          const timer = setTimeout(done, Math.min(2000, Math.max(0, expires - Date.now())));
          const signal = this.controller.signal;
          function done() { clearTimeout(timer); signal.removeEventListener('abort', done); resolve(); }
          signal.addEventListener('abort', done, { once: true });
          if (signal.aborted) done();
        });
      }
      if (!this.disposed) this.unknown(job, 'Observation timed out; the server job may still run.');
    } catch {
      if (!this.disposed) this.unknown(job, job.id ? 'Could not track an accepted job.' : 'Submission response was lost; acceptance is uncertain.');
    } finally {
      this.active.delete(job.attempt);
      this.finishIfDrained();
      this.pump();
      this.publish();
    }
  }

  private finishIfDrained() {
    if (this.state.draining && !this.active.size) {
      this.state.ended = true;
      this.state.message = this.state.unknown ? 'Run ended with unknown jobs. Review the report and server before testing again.' : 'Run finished. Download the report or start a new run.';
      clearTimeout(this.deadlineTimer);
      this.publish();
    }
  }

  private snapshot(): LoadSnapshot {
    const durations = this.jobs.filter((job) => job.status === 'completed' && job.finished)
      .map((job) => (job.finished! - job.started) / 1000).sort((a, b) => a - b);
    return {
      ...this.state, outstanding: this.active.size,
      p50Seconds: durations.length ? durations[Math.ceil(durations.length * 0.5) - 1] : null,
      p95Seconds: durations.length ? durations[Math.ceil(durations.length * 0.95) - 1] : null,
      jobs: this.jobs.slice(-30).reverse().map((job) => ({ ...job }))
    };
  }

  private publish() { if (!this.disposed) this.onchange(this.snapshot()); }
}
