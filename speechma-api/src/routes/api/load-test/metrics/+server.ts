import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { getRuntime } from '$lib/server/runtime';
import { readSystemMetrics } from '$lib/server/system-metrics';
import type { ServerMetrics } from '$lib/types/load-test';

export const GET: RequestHandler = async () => {
  const [runtime, resources] = await Promise.all([getRuntime(), readSystemMetrics()]);
  return json({
    timestamp: Date.now(), ready: runtime.providerReady, maxConcurrent: runtime.config.maxConcurrent,
    ...resources
  } satisfies ServerMetrics, { headers: { 'cache-control': 'no-store' } });
};
