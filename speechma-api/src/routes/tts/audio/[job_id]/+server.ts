import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { getRuntime } from '$lib/server/runtime';

export const GET: RequestHandler = async ({ params: { job_id } }) => {
  try {
    const runtime = await getRuntime();
    const audio = await runtime.storage.download(job_id);
    if (!audio) return json({ detail: { message: `Audio for job ${job_id} not found or not ready yet`, job_id } }, { status: 404 });
    if (!audio.stream) return json({ detail: { message: `Audio file appears to be incomplete for job ${job_id}`, job_id } }, { status: 422 });
    return new Response(audio.stream, { headers: {
      'Content-Type': 'audio/mpeg',
      'Content-Length': String(audio.size),
      'Cache-Control': 'public, max-age=86400',
      ETag: `"${job_id}"`
    } });
  } catch {
    return json({ detail: { message: 'Error reading audio file', job_id } }, { status: 500 });
  }
};

export const DELETE: RequestHandler = async ({ params: { job_id } }) => {
  try {
    const runtime = await getRuntime();
    if (!await runtime.storage.remove(job_id)) {
      return json({ detail: { message: `Audio for job ${job_id} not found`, job_id } }, { status: 404 });
    }
    runtime.forget(job_id);
    return json({ message: `Audio for job ${job_id} deleted successfully` });
  } catch {
    return json({ detail: { message: 'Error deleting audio file', job_id } }, { status: 500 });
  }
};
