export interface ApiResult {
  method: string;
  path: string;
  status: number;
  ok: boolean;
  elapsedMs: number;
  body: unknown;
}

export async function readResponse(response: Response): Promise<unknown> {
  const text = await response.text();
  try { return JSON.parse(text); } catch { return text; }
}

export async function requestJson(path: string, apiKey: string, options: RequestInit = {}): Promise<ApiResult> {
  const start = performance.now();
  const headers = new Headers(options.headers);
  headers.set('api-key', apiKey);
  if (options.body) headers.set('Content-Type', 'application/json');
  const response = await fetch(path, { ...options, headers, cache: 'no-store' });
  const body = await readResponse(response);
  return {
    method: options.method ?? 'GET', path, status: response.status,
    ok: response.ok, elapsedMs: Math.round(performance.now() - start), body
  };
}
