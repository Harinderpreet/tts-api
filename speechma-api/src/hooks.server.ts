import { building } from '$app/environment';
import { json, type Handle, type ServerInit } from '@sveltejs/kit';
import { hasValidApiKey } from '$lib/server/auth';
import { getRuntime } from '$lib/server/runtime';

export const init: ServerInit = async () => {
  if (!building) await getRuntime();
};

export const handle: Handle = async ({ event, resolve }) => {
  const path = event.url.pathname;
  const apiRoute = path === '/health' || path === '/tts' || path.startsWith('/tts/')
    || path.startsWith('/api/load-test/');
  if (!apiRoute) return resolve(event);

  // Preserve the source's permissive CORS policy and unauthenticated preflight.
  const cors = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': '*'
  };
  if (event.request.method === 'OPTIONS') return new Response(null, { status: 200, headers: cors });

  const runtime = await getRuntime();
  if (!hasValidApiKey(event.request.headers, runtime.config.apiKey)) {
    return json({ detail: event.request.headers.has('api-key') ? 'Invalid API key' : 'Not authenticated' },
      { status: 403, headers: cors });
  }
  const response = await resolve(event);
  for (const [key, value] of Object.entries(cors)) response.headers.set(key, value);
  return response;
};
