import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { getRuntime } from '$lib/server/runtime';

export const GET: RequestHandler = async () => {
  try {
    const runtime = await getRuntime();
    return json({
      status: runtime.providerReady ? 'healthy' : 'unhealthy',
      audio_files_count: (await runtime.storage.list()).length,
      active_jobs_size: runtime.queueSize,
      processing_jobs_count: runtime.processingJobsCount,
      worker_slots_in_use: runtime.workerSlotsInUse,
      max_concurrent_requests: runtime.config.maxConcurrent,
      memory_jobs_count: runtime.jobs.size,
      message: runtime.providerReady ? 'System is operational' : 'Service is unavailable'
    });
  } catch {
    return json({
      status: 'unhealthy', audio_files_count: 0, active_jobs_size: 0,
      memory_jobs_count: 0, message: 'Error: Unable to read system statistics'
    });
  }
};
