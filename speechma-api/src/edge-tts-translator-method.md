# Microsoft Translator token method for speech generation

Documented on October 13, 2026.

Source: [pyVideoTrans — Bypassing Edge-TTS Errors by Deploying to Cloudflare](https://en.pyvideotrans.com/edgettscf).

## Overview

The article's method obtains a temporary token and region from Microsoft Translator, then uses them to request synthesized audio from Microsoft Speech over HTTPS. Cloudflare is a hosting option for the code; it is not required for the token flow.

Our implementation runs on the SvelteKit server and uses Node's built-in cryptography and HTTP fetch APIs. It does not use the Speech SDK, an Azure subscription key, an external proxy, or a Cloudflare Worker.

```text
Browser
  -> SvelteKit API
     -> Microsoft Translator: request token and region, unless cached
     -> Microsoft Speech: submit speech request using token
  <- MP3 audio
```

## 1. Obtain a token and region

Send an empty-body POST to:

```text
https://dev.microsofttranslator.com/apps/endpoint?api-version=1.0
```

The request carries the article's client identity headers and an `X-MT-Signature`.

Signature construction:

1. Generate a UUID and remove its hyphens.
2. Format the current UTC date with `toUTCString()` and lowercase it.
3. Remove `https://` from the endpoint URL and apply `encodeURIComponent()` to the remainder.
4. Concatenate `MSTranslatorAndroidApp`, the encoded URL, the date, and the UUID; lowercase the whole string.
5. Sign it with HMAC-SHA256 using the article's Base64-decoded signing constant, then Base64-encode the digest.
6. Construct the header value:

```text
MSTranslatorAndroidApp::<signature>::<date>::<uuid>
```

The response fields used are `r` (region) and `t` (authorization token).

## 2. Request speech

Send a POST to:

```text
https://<r>.tts.speech.microsoft.com/cognitiveservices/v1
```

Supply `t` as the `Authorization` header, the speech document as the body, `Content-Type: application/ssml+xml`, and `X-Microsoft-OutputFormat: audio-24khz-48kbitrate-mono-mp3`. The successful response contains audio bytes.

## How the current implementation handles this

The exact client headers, signing constant, and User-Agent used in the working experiment are maintained in [the server helper](../src/lib/server/edge-tts-cf.ts). These values were taken from the article, rather than guessed or obtained from the user's Azure account.

`getEndpoint()` validates the returned region and token. It reads the token's JWT `exp` field to determine the cache expiry; this decoding is for caching, not signature verification. It refreshes the token three minutes before expiry and does not fall back to an expired token. The cache lives in server-process memory, so separate instances have separate caches.

`synthesizeSsml()` sends one complete speech request. It rejects HTTP failures, empty audio, and non-audio responses. A speech response of 401 or 403 clears the cached token for the next attempt; the failed request is not automatically retried. Tokens are kept server-side and are not returned to the browser.

The selected output is a 24 kHz, 48 kbps, mono MP3. The browser receives the MP3, elapsed server time, and region for playback and download. This response path does not return word-level timing metadata.

## Project locations

| Purpose | File or route |
| --- | --- |
| Test page | [src/routes/edge-tts-cf/+page.svelte](../src/routes/edge-tts-cf/+page.svelte) — `/edge-tts-cf` |
| API validation and response | [src/routes/api/edge-tts-cf/+server.ts](../src/routes/api/edge-tts-cf/+server.ts) — `POST /api/edge-tts-cf` |
| Token acquisition and synthesis | [src/lib/server/edge-tts-cf.ts](../src/lib/server/edge-tts-cf.ts) |

The page supports plain text and complete speech documents. Both use the same token acquisition and synthesis flow. The API checks that requests originate from the same origin as the test page; it currently has no account authentication or per-user quota enforcement.

## Network and observed behavior

Microsoft receives connections from the machine running this code. Locally, that is the computer's outbound public IP; after deployment, it is the hosting server's outbound IP. A VPN or outbound network proxy can change that address. Merely placing the website behind Cloudflare does not reroute the server's outgoing requests.

The user reported successful generation with standard neural, multilingual, Dragon HD, and Dragon HD Omni voice examples through this method. This confirms those tested examples, not universal access to every Microsoft voice. The experiment requires no user-provided paid Speech credentials; it does not establish unlimited usage or guaranteed future availability.

The original 2,000-character application cap and automatic request timers have been removed. The current implementation sends the complete input in one synthesis request without splitting it into chunks. Runtime, hosting, network, and provider limits still apply, and the actual maximum input size has not been established. Successful MP3 delivery alone does not confirm that the entire input was spoken.

SSML feature syntax and examples are intentionally outside this document's scope.
