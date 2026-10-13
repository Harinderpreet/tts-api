import { env } from '$env/dynamic/private';
import { resolve } from 'node:path';

export function readConfig() {
  if (!env.API_KEY) throw new Error('API_KEY must be configured');

  function number(name: string, fallback: number, minimum: number, integer = false) {
    const value = Number(env[name] ?? fallback);
    if (!Number.isFinite(value) || value < minimum || (integer && !Number.isInteger(value))) {
      throw new Error(`Invalid ${name} configuration`);
    }
    return value;
  }

  const config = {
    apiKey: env.API_KEY,
    webhookUrl: (env.WEBHOOK_URL ?? '').trim(),
    audioDir: resolve(env.AUDIO_DIR?.trim() || 'audio_files'),
    maxConcurrent: number('MAX_CONCURRENT_REQUESTS', 50, 1, true),
    autoDeleteDelayMs: number('AUTO_DELETE_DELAY', 300, 0) * 1000,
    maxTextLength: number('MAX_TEXT_LENGTH', 50000, 1, true),
    minTextLength: number('MIN_TEXT_LENGTH', 2, 1, true),
    processTimeoutMs: number('PROCESS_TIMEOUT', 600, 0.001) * 1000
  };
  if (config.minTextLength > config.maxTextLength) {
    throw new Error('MIN_TEXT_LENGTH cannot exceed MAX_TEXT_LENGTH');
  }
  // Node timers overflow beyond this limit rather than waiting the requested duration.
  if (config.autoDeleteDelayMs > 2_147_483_647 || config.processTimeoutMs > 2_147_483_647) {
    throw new Error('Configured timeout exceeds the Node timer limit');
  }
  return config;
}

export type Config = ReturnType<typeof readConfig>;
