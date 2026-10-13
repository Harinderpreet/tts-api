import { createHmac, randomUUID } from 'node:crypto';

// Protocol constants from the existing edge-tts-cf.ts experiment documented in
// src/edge-tts-translator-method.md and https://en.pyvideotrans.com/edgettscf.
const endpointUrl = 'https://dev.microsofttranslator.com/apps/endpoint?api-version=1.0';
const signingKey = 'oik6PdDdMnOXemTbwvMn9de/h9lFnfBaCWbGMMZqqoSaQaqUOqjVGm5NqsmjcBI1x+sS9ugjB55HEJWRiFXYFw==';
const userAgent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36 Edg/127.0.0.0';
type Endpoint = { region: string; token: string; expires: number };
let cachedEndpoint: Endpoint | undefined;

async function providerError(response: Response, stage: string, token?: string) {
  let detail = await response.text().catch(() => '(response body could not be read)');
  // Preserve provider diagnostics for server logs without exposing authorization values.
  if (token) detail = detail.replaceAll(token, '[redacted token]');
  detail = detail.replaceAll(signingKey, '[redacted signing key]')
    .replace(/"(?:t|token|access_token|authorization)"\s*:\s*"[^"]*"/gi, '"credential":"[redacted]"')
    .replace(/\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, '[redacted token]');
  return new Error(`${stage}: HTTP ${response.status} ${response.statusText}. ${detail.slice(0, 4000)}`);
}

async function getEndpoint(signal: AbortSignal): Promise<Endpoint> {
  signal.throwIfAborted();
  if (cachedEndpoint && Date.now() / 1000 < cachedEndpoint.expires - 180) return cachedEndpoint;

  const requestId = randomUUID().replaceAll('-', '');
  const date = new Date().toUTCString().toLowerCase();
  const encodedUrl = encodeURIComponent(endpointUrl.split('://')[1]);
  const payload = `MSTranslatorAndroidApp${encodedUrl}${date}${requestId}`.toLowerCase();
  const signature = createHmac('sha256', Buffer.from(signingKey, 'base64')).update(payload).digest('base64');
  const response = await fetch(endpointUrl, {
    method: 'POST', signal, redirect: 'error',
    headers: {
      'Accept-Language': 'zh-Hans',
      'X-ClientVersion': '4.0.530a 5fe1dc6c',
      'X-UserId': '0f04d16a175c411e',
      'X-HomeGeographicRegion': 'zh-Hans-CN',
      'X-ClientTraceId': randomUUID().replaceAll('-', ''),
      'X-MT-Signature': `MSTranslatorAndroidApp::${signature}::${date}::${requestId}`,
      'User-Agent': userAgent,
      'Content-Type': 'application/json; charset=utf-8'
    }
  });
  if (!response.ok) {
    throw await providerError(response, 'Translator token request');
  }
  const data = await response.json().catch(() => {
    throw new Error('Translator token endpoint returned invalid JSON');
  });
  if (typeof data?.r !== 'string' || !/^[a-z0-9-]+$/.test(data.r) || typeof data?.t !== 'string') {
    throw new Error('Translator token endpoint returned an invalid region or missing token');
  }
  // Decode expiry only for caching; this does not verify the JWT signature.
  let expires: unknown;
  try {
    expires = JSON.parse(Buffer.from(data.t.split('.')[1], 'base64url').toString()).exp;
  } catch {
    throw new Error('Translator token could not be decoded to read its expiry');
  }
  if (typeof expires !== 'number' || !Number.isFinite(expires) || expires <= Date.now() / 1000) {
    throw new Error('Translator token has an invalid or elapsed expiry');
  }
  signal.throwIfAborted();
  cachedEndpoint = { region: data.r, token: data.t, expires };
  return cachedEndpoint;
}

/** One complete SSML request, without chunking or automatic provider retries. */
export async function* synthesizeSsml(ssml: string, signal: AbortSignal): AsyncGenerator<Uint8Array> {
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  let stage = 'Translator token request';
  try {
    const endpoint = await getEndpoint(signal);
    stage = 'Microsoft Speech request';
    const response = await fetch(`https://${endpoint.region}.tts.speech.microsoft.com/cognitiveservices/v1`, {
      method: 'POST', signal, redirect: 'error',
      headers: {
        Authorization: endpoint.token,
        'Content-Type': 'application/ssml+xml',
        'User-Agent': userAgent,
        'X-Microsoft-OutputFormat': 'audio-24khz-48kbitrate-mono-mp3'
      },
      body: ssml
    });
    if (!response.ok) {
      if ((response.status === 401 || response.status === 403) && cachedEndpoint === endpoint) {
        cachedEndpoint = undefined;
      }
      throw await providerError(response, stage, endpoint.token);
    }
    const contentType = response.headers.get('content-type');
    if (!contentType?.toLowerCase().startsWith('audio/') || !response.body) {
      await response.body?.cancel();
      throw new Error(`Microsoft Speech returned no audio stream or a non-audio content type (${contentType ?? 'missing'})`);
    }
    stage = 'Microsoft Speech audio stream';
    reader = response.body.getReader();
    let size = 0;
    while (true) {
      signal.throwIfAborted();
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      yield value;
    }
    // Match the download boundary: never publish an empty or unusably short file.
    if (size < 100) throw new Error(`Microsoft Speech returned incomplete audio (${size} bytes)`);
  } catch (error) {
    // Preserve the underlying failure for server logs; the job processor sanitizes public output.
    throw new Error(`${stage} failed`, { cause: error });
  } finally {
    if (reader) {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
}
