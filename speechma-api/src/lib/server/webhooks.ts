import { setTimeout as delay } from 'node:timers/promises';
import type { WebhookPayload } from '$lib/types/tts';

export async function sendWebhook(url: string, event: WebhookPayload, signal: AbortSignal) {
  if (!url.trim()) return;
  const payload: WebhookPayload = {
    job_id: event.job_id, status: event.status, timestamp: event.timestamp
  };
  if (event.message) payload.message = event.message;
  if (event.processing_time_seconds) payload.processing_time_seconds = event.processing_time_seconds;

  for (let attempt = 0; attempt < 3; attempt++) {
    if (signal.aborted) return;
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
        redirect: 'manual',
        signal: AbortSignal.any([signal, AbortSignal.timeout(10_000)])
      });
      await response.body?.cancel();
      if (response.status === 200) return;
    } catch {
      if (signal.aborted) return;
    }
    try {
      await delay((2 ** attempt + 0.1 * attempt) * 1000, undefined, { signal });
    } catch {
      return;
    }
  }
  console.warn(`Webhook delivery failed for job ${event.job_id} (${event.status})`);
}
