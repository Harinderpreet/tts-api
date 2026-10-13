import type { Job } from '$lib/types/tts';
import type { AudioStorage } from '../audio-storage';
import type { Config } from '../config';
import type { SpeechProvider } from '../tts/provider';
import type { RetentionWorker } from './retention';
import { localTimestamp } from '../timestamps';
import { sendWebhook } from '../webhooks';

export async function processJob(
  job: Job, provider: SpeechProvider, storage: AudioStorage,
  retention: RetentionWorker, config: Config, shutdown: AbortSignal
) {
  job.status = 'processing';
  job.start_time = Date.now();
  const controller = new AbortController();
  const signal = AbortSignal.any([shutdown, controller.signal]);
  const timer = setTimeout(() => controller.abort(new Error(
    `TTS processing timed out for job ${job.job_id} (${config.processTimeoutMs / 1000}s timeout exceeded)`
  )), config.processTimeoutMs);
  let onAbort: () => void = () => {};

  try {
    signal.throwIfAborted();
    const cancelled = new Promise<never>((_, reject) => {
      onAbort = () => reject(signal.reason);
      signal.addEventListener('abort', onAbort, { once: true });
    });
    const synthesis = (async () => {
      const audio = await provider.synthesize(job.request, signal);
      await storage.save(job.job_id, audio, signal);
    })();
    await Promise.race([synthesis, cancelled]);
    clearTimeout(timer);
    signal.removeEventListener('abort', onAbort);
    job.status = 'completed';
    retention.schedule(job.job_id);
    await sendWebhook(config.webhookUrl, {
      job_id: job.job_id, status: 'completed', timestamp: localTimestamp(),
      message: 'Audio file is ready',
      processing_time_seconds: (Date.now() - job.start_time) / 1000
    }, AbortSignal.any([shutdown, AbortSignal.timeout(5000)]));
  } catch (error) {
    console.error(`[Speechma] Audio generation failed for job ${job.job_id}`, error);
    job.status = 'failed';
    job.error_message = 'Audio generation failed';
    await sendWebhook(config.webhookUrl, {
      job_id: job.job_id, status: 'failed', timestamp: localTimestamp(),
      message: job.error_message
    }, AbortSignal.any([shutdown, AbortSignal.timeout(5000)]));
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', onAbort);
    job.end_time = Date.now();
  }
}
