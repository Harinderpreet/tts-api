// Same public protocol constants as the documented server experiment, not API_KEY.
const endpointUrl = 'https://dev.microsofttranslator.com/apps/endpoint?api-version=1.0';
const signingKey = 'oik6PdDdMnOXemTbwvMn9de/h9lFnfBaCWbGMMZqqoSaQaqUOqjVGm5NqsmjcBI1x+sS9ugjB55HEJWRiFXYFw==';

export interface BrowserSpeechEndpoint {
  region: string;
  token: string;
}

// Memory only: shared within this tab, cleared on reload, never persisted to storage.
let cachedEndpoint: (BrowserSpeechEndpoint & { expires: number }) | undefined;

async function responseError(response: Response, stage: string, token?: string) {
  let detail = await response.text();
  if (token) detail = detail.replaceAll(token, '[redacted token]');
  detail = detail.replaceAll(signingKey, '[redacted signing key]')
    .replace(/"(?:t|token|access_token|authorization)"\s*:\s*"[^"]*"/gi, '"credential":"[redacted]"')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[redacted token]');
  return new Error(`${stage}: HTTP ${response.status} ${response.statusText}. ${detail.slice(0, 4000)}`);
}

/** Reuse tokens until three minutes before their expiry, matching the server cache. */
export async function requestBrowserSpeechEndpoint(
  signal: AbortSignal, { forceRefresh = false }: { forceRefresh?: boolean } = {}
): Promise<BrowserSpeechEndpoint> {
  signal.throwIfAborted();
  if (!forceRefresh && cachedEndpoint && Date.now() / 1000 < cachedEndpoint.expires - 180) {
    return cachedEndpoint;
  }
  cachedEndpoint = undefined;
  if (!globalThis.isSecureContext || !globalThis.crypto?.subtle) {
    throw new Error('Browser signing requires HTTPS or localhost with Web Crypto support.');
  }
  signal.throwIfAborted();
  const requestId = crypto.randomUUID().replaceAll('-', '');
  const date = new Date().toUTCString().toLowerCase();
  const encodedUrl = encodeURIComponent(endpointUrl.split('://')[1]);
  const payload = `MSTranslatorAndroidApp${encodedUrl}${date}${requestId}`.toLowerCase();
  const key = await crypto.subtle.importKey(
    'raw', Uint8Array.from(atob(signingKey), (character) => character.charCodeAt(0)),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']
  );
  const digest = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(payload));
  const signature = btoa(String.fromCharCode(...new Uint8Array(digest)));
  signal.throwIfAborted();
  const response = await fetch(endpointUrl, {
    method: 'POST', mode: 'cors', credentials: 'omit', redirect: 'error', signal,
    // The token endpoint returns 401001 when the browser sends a Referer.
    // Preserve CORS and Origin; omit only the referring page URL.
    referrerPolicy: 'no-referrer',
    headers: {
      'Accept-Language': 'zh-Hans',
      'X-ClientVersion': '4.0.530a 5fe1dc6c',
      'X-UserId': '0f04d16a175c411e',
      'X-HomeGeographicRegion': 'zh-Hans-CN',
      'X-ClientTraceId': crypto.randomUUID().replaceAll('-', ''),
      'X-MT-Signature': `MSTranslatorAndroidApp::${signature}::${date}::${requestId}`,
      'Content-Type': 'application/json; charset=utf-8'
      // User-Agent is supplied by the browser, not spoofed by this experiment.
    }
  });
  if (!response.ok) throw await responseError(response, 'Translator token request');
  const data = await response.json();
  if (typeof data?.r !== 'string' || !/^[a-z0-9-]+$/.test(data.r) || typeof data?.t !== 'string' || !data.t) {
    throw new Error('Translator returned an invalid region or missing token.');
  }
  // Read expiry for caching only; this is not JWT signature verification.
  let expires: unknown;
  try {
    const payload = data.t.split('.')[1].replaceAll('-', '+').replaceAll('_', '/');
    const bytes = Uint8Array.from(atob(payload.padEnd(Math.ceil(payload.length / 4) * 4, '=')),
      (character) => character.charCodeAt(0));
    expires = JSON.parse(new TextDecoder().decode(bytes)).exp;
  } catch {
    throw new Error('Translator token could not be decoded to read its expiry.');
  }
  if (typeof expires !== 'number' || !Number.isFinite(expires) || expires <= Date.now() / 1000) {
    throw new Error('Translator token has an invalid or elapsed expiry.');
  }
  signal.throwIfAborted();
  cachedEndpoint = { region: data.r, token: data.t, expires };
  return cachedEndpoint;
}

/** Browser -> Microsoft Speech. No Speechma API, proxy, or fallback. */
export async function requestBrowserSpeech(
  endpoint: BrowserSpeechEndpoint, ssml: string, signal: AbortSignal
): Promise<Blob> {
  const response = await fetch(`https://${endpoint.region}.tts.speech.microsoft.com/cognitiveservices/v1`, {
    method: 'POST', mode: 'cors', credentials: 'omit', redirect: 'error', signal,
    headers: {
      Authorization: endpoint.token,
      'Content-Type': 'application/ssml+xml',
      'X-Microsoft-OutputFormat': 'audio-24khz-48kbitrate-mono-mp3'
    },
    body: ssml
  });
  if (!response.ok) {
    if ((response.status === 401 || response.status === 403) && cachedEndpoint?.token === endpoint.token) {
      cachedEndpoint = undefined;
    }
    throw await responseError(response, 'Microsoft Speech request', endpoint.token);
  }
  const contentType = response.headers.get('content-type');
  if (!contentType?.toLowerCase().startsWith('audio/')) {
    await response.body?.cancel();
    throw new Error(`Microsoft Speech returned a non-audio content type (${contentType ?? 'missing'}).`);
  }
  const audio = await response.blob();
  if (audio.size < 100) throw new Error(`Microsoft Speech returned incomplete audio (${audio.size} bytes).`);
  signal.throwIfAborted();
  return audio;
}
