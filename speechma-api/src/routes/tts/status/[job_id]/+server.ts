import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { getRuntime } from '$lib/server/runtime';

export const GET: RequestHandler = async ({ params: { job_id } }) => {
  try {
    const runtime = await getRuntime();
    const status = await runtime.storage.info(job_id) ? 'completed' : runtime.jobs.get(job_id)?.status;
    if (!status) return json({ detail: { message: `Job ${job_id} not found`, job_id } }, { status: 404 });
    const messages = {
      queued: 'Audio is queued',
      processing: 'Audio is being processed',
      completed: 'Audio is ready',
      failed: 'Audio generation failed'
    };
    return json({ job_id, status, message: messages[status] });
  } catch {
    return json({ detail: { message: 'Error checking job status', job_id } }, { status: 500 });
  }
};
