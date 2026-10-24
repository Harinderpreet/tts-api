import { getRuntime } from '$lib/server/runtime';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ setHeaders }) => {
  setHeaders({ 'cache-control': 'no-store' });
  const { minTextLength, maxTextLength, maxConcurrent, processTimeoutMs } = (await getRuntime()).config;
  return { minTextLength, maxTextLength, maxConcurrent, processTimeoutSeconds: processTimeoutMs / 1000 };
};
