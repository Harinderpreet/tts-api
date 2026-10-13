import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import type { TtsRequest } from '$lib/types/tts';
import { getRuntime } from '$lib/server/runtime';

export const POST: RequestHandler = async ({ request }) => {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return json({ detail: [{ loc: ['body'], msg: 'Invalid JSON', type: 'json_invalid' }] }, { status: 422 });
  }
  if (body === null || typeof body !== 'object' || Array.isArray(body)) {
    return json({ detail: [{ loc: ['body'], msg: 'Input should be an object', type: 'model_type' }] }, { status: 422 });
  }

  const input = body as Record<string, unknown>;
  const defaults = { voice: 'en-US-AriaNeural', pitch: '0', speed: '1', volume: '100', style: 'general' };
  const fields = ['text', 'voice', 'pitch', 'speed', 'volume', 'style'] as const;
  const issues: Array<{ loc: string[]; msg: string; type: string }> = [];
  for (const field of fields) {
    if (!(field in input)) {
      if (field === 'text') issues.push({ loc: ['body', field], msg: 'Field required', type: 'missing' });
    } else if (typeof input[field] !== 'string') {
      issues.push({ loc: ['body', field], msg: 'Input should be a valid string', type: 'string_type' });
    }
  }
  if (issues.length) return json({ detail: issues }, { status: 422 });

  const runtime = await getRuntime();
  const { minTextLength, maxTextLength } = runtime.config;
  const text = input.text as string;
  // Count Unicode code points, matching Python len() rather than UTF-16 code units.
  if ([...text].length > maxTextLength || !text.trim()) {
    const msg = text.trim() ? `Text exceeds maximum length of ${maxTextLength} characters` : 'Text cannot be empty';
    return json({ detail: [{ loc: ['body', 'text'], msg, type: 'value_error' }] }, { status: 422 });
  }
  if (!/[\p{L}\p{N}]/u.test(text)) {
    return json({ detail: { message: "Text must contain alphanumeric characters (not just punctuation like '...' or '!!!')" } }, { status: 400 });
  }
  if ([...text.trim()].length < minTextLength) {
    return json({ detail: { message: `Text too short (minimum ${minTextLength} characters)` } }, { status: 400 });
  }
  if (!runtime.providerReady) {
    return json({ detail: { message: 'Audio generation failed' } }, { status: 503 });
  }
  if (runtime.queueSize > runtime.config.maxConcurrent * 2) {
    return json({ detail: { message: 'Server is currently at capacity. Please try again later.', queue_size: runtime.queueSize } }, { status: 503 });
  }
  const speech: TtsRequest = {
    text: text.trim(),
    voice: (input.voice as string | undefined) ?? defaults.voice,
    pitch: (input.pitch as string | undefined) ?? defaults.pitch,
    speed: (input.speed as string | undefined) ?? defaults.speed,
    volume: (input.volume as string | undefined) ?? defaults.volume,
    style: (input.style as string | undefined)?.trim() || defaults.style
  };
  try {
    return json({ job_id: runtime.add(speech) });
  } catch {
    return json({ detail: { message: 'Unable to submit speech job' } }, { status: 500 });
  }
};
