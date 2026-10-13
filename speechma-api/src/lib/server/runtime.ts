import { readConfig } from './config';
import { AudioStorage } from './audio-storage';
import { JobManager } from './jobs/manager';
import { speechProvider } from './tts/provider';

const state = globalThis as typeof globalThis & {
  __speechmaRuntime?: Promise<JobManager>;
};

export function getRuntime(): Promise<JobManager> {
  // Keep a single queue and cleanup worker during development module reloads.
  return state.__speechmaRuntime ??= initialize().catch((error) => {
    state.__speechmaRuntime = undefined;
    throw error;
  });
}

async function initialize() {
  const config = readConfig();
  const storage = new AudioStorage(config.audioDir);
  await storage.initialize();
  const manager = new JobManager(config, storage, speechProvider);
  manager.start();
  process.once('sveltekit:shutdown', () => { void manager.stop(); });
  return manager;
}
