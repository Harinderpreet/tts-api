import { getRuntime } from '$lib/server/runtime';
import type { PageServerLoad } from './$types';

// Only public input limits are loaded here. All Microsoft calls run in the browser.
export const prerender = false;
export const load: PageServerLoad = async ({ setHeaders }) => {
  setHeaders({ 'cache-control': 'no-store' });
  const { minTextLength, maxTextLength } = (await getRuntime()).config;
  return { minTextLength, maxTextLength };
};
