import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { getRuntime } from '$lib/server/runtime';

export const GET: RequestHandler = async () => {
  try {
    return json(await (await getRuntime()).list());
  } catch {
    return json({ detail: { message: 'Error getting jobs' } }, { status: 500 });
  }
};
