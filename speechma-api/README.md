# Speechma API — SvelteKit

TTS-only SvelteKit implementation based on [`../API_AND_ARCHITECTURE.md`](../API_AND_ARCHITECTURE.md).
The existing Python applications are unchanged. The user confirmed that public routes stay
at `/tts` and `/health`, with no `/api` prefix. LavaSR is outside this app's scope.

## Setup

Use Node.js 24 or newer. From this directory, install the declared dependencies yourself:

```sh
npm install
cp .env.example .env
```

Set `API_KEY` in `.env`. Keep `WEBHOOK_URL` empty until notifications should be delivered.
The dependency versions use the SvelteKit 2 / Svelte 5 / Vite 8 combination already declared
in the local Ai-Video project. The generated `package-lock.json` locks resolved versions.

No service has been started. `npm run dev` is available for the IDE's development setup.
When authorized, `npm run check` checks types and `npm run build` produces the Node server.
`npm start` runs that build and loads `.env`; none of these commands were run during scaffolding.

## Docker production deployment

The Dockerfile builds the SvelteKit app with Node 24 and runs `node build` as the unprivileged
`node` user. It carries only the built app, production dependencies, package metadata, and
healthcheck script into the runtime image. It does not use `npm start`, so it does not require
an `.env` file inside the container. Secrets and existing audio are excluded from the build.

Configure your deployment platform as follows:

| Setting | Value |
| --- | --- |
| Build context / application directory | `speechma-api` within this repository |
| Dockerfile | `Dockerfile` relative to that context (`speechma-api/Dockerfile` from repo root) |
| Container port | `3000` |
| Start command | Use the image default (`node build`) |
| Runtime environment | Set `API_KEY`; set `ORIGIN` to your actual public origin, including `https://` |
| Optional runtime environment | `WEBHOOK_URL` and the existing limits in the configuration table/reference |
| Persistent volume destination | `/app/audio_files` |
| Replicas | One; the queue and job metadata remain process-local |
| Stop grace period | At least 45 seconds to allow the adapter's default 30-second HTTP shutdown window |

The image uses `HOST=0.0.0.0`, `PORT=3000`, `AUDIO_DIR=/app/audio_files`, and
`BODY_SIZE_LIMIT=1M`. The transport body limit allows JSON escaping overhead around the
50,000-character application limit; it does not increase the text limit. Adjust it explicitly
if you later raise `MAX_TEXT_LENGTH`. Keep `AUDIO_DIR` aligned with the mounted volume.

Supply secrets as runtime environment variables in the hosting platform, not build arguments.
No public domain, TLS certificate, proxy configuration, or registry destination is assumed.
Terminate HTTPS at your hosting platform/reverse proxy and forward traffic to container port
3000. Existing paths remain `/tts`, `/health`, and `/test-me-here`.

The built-in Docker healthcheck sends the required `api-key` header to `/health` and checks
both HTTP success and the JSON `status`, because that route returns HTTP 200 even when unhealthy.
If your platform replaces this with its own HTTP probe, supply the same header and check the
JSON status there too. This is a local health check, not a live Microsoft synthesis request.

Build command, from the repository root:

```sh
docker build -t speechma-api:latest ./speechma-api
```

For a standalone Docker deployment, place production runtime variables in
`speechma-api/.env.production` (including `API_KEY` and your actual `ORIGIN`), then run:

```sh
docker run -d \
  --name speechma-api \
  --restart unless-stopped \
  --stop-timeout 45 \
  --env-file speechma-api/.env.production \
  -p 3000:3000 \
  --mount type=volume,source=speechma-audio,target=/app/audio_files \
  speechma-api:latest
```

The named volume retains generated audio across container replacement; normal audio retention
still deletes expired files. Host bind mounts must be writable by the image's `node` user
(UID/GID 1000). Queued/running jobs are not persisted, so container replacement can interrupt
generation. The production test page never prefills the shared API key.

These files prepare the image build. No Docker image has been built, pushed, or started by the
agent, and the container healthcheck has not been executed. Build/install/run commands above
are provided for you or your deployment platform to execute.

## Current implementation

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/tts` | Validate and submit a speech job |
| GET | `/tts/status/[job_id]` | Read disk-first job status |
| GET | `/tts/audio/[job_id]` | Stream MP3 audio |
| DELETE | `/tts/audio/[job_id]` | Delete audio and its memory record |
| GET | `/tts/jobs` | List the latest 50 disk/memory records |
| GET | `/health` | Read local queue/storage statistics |

All application routes require the `api-key` header. API-key authentication is centralized
in `hooks.server.ts`; missing `API_KEY` fails runtime initialization. Building does not
initialize the queue or require that secret. FastAPI documentation routes are not added.

The light-theme testing page is at `/test-me-here`. In development, the API key field is
prefilled from the server's `API_KEY`. Production leaves it blank; the shared key is never
included in production page data. The page response uses `Cache-Control: no-store`.
You can also enter the service API key manually to submit speech,
check job status, load/play/download audio, delete audio with confirmation, list jobs, or inspect
health. It calls this app's existing endpoints and shows HTTP status, timing, and response bodies.
The key is kept only in page memory, never persisted to browser storage. After submission or
selection from recent jobs, status is checked automatically with 1.5 seconds between completed
requests. Polling stops on completion, failure, request errors, changing the key/job, a new
submission, deletion, or leaving the page. Completed jobs load audio automatically without
autoplay. The manual status button can resume checking an existing job. Health and job-list
requests remain manual; no requests run automatically on page load. Audio is fetched with the key
and played through a temporary object URL, which is revoked when replaced or the component closes.
The page is publicly loadable, while its API operations still require the service key.

The API and testing page use `MAX_TEXT_LENGTH` (default 50,000 raw characters) and
`MIN_TEXT_LENGTH` (default 2 characters after trimming). The page receives the active limits
from the server, shows a character counter, and disables submission outside those bounds.
Both count Unicode code points. Overlong pasted input is shown with an error, not truncated.
These limits apply to the submitted text, before XML escaping and the SSML wrapper; the
Microsoft speech request sends the generated SSML as `application/ssml+xml`.

### Pauses and speaking style

`POST /tts` now also accepts an optional string `style`. Missing or blank values use the
existing `general` style. Non-string values (including null) return HTTP 422, like the other
string fields. The selected style is XML-escaped and applied to the entire text inside one
`mstts:express-as` element. Existing `styledegree="2.0"` and `role="default"` behavior is retained.
Styles depend on the selected voice; there is no guessed style allowlist.

Inline markers such as `[break 1s]`, `[break 1.5s]`, and `[break 500ms]` become SSML `break`
elements in place. Multiple markers are supported, with case-insensitive `break` and units.
Durations must be nonnegative numeric values in seconds or milliseconds. Unrecognized markers
remain literal text. Ordinary input and raw XML remain escaped; only recognized markers add
SSML elements. The raw character limit includes the marker characters.

Example request body:

```json
{
  "text": "Hello there. [break 1s] Welcome to Speechma.",
  "voice": "en-US-AriaNeural",
  "style": "cheerful"
}
```

Neither supplied local reference defined inline pause syntax. Microsoft's documentation
describes [break duration](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup-structure#add-a-break)
and [voice-specific styles](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-synthesis-markup-voice).
Microsoft documents a maximum of 20 seconds per break, with longer values capped by the
provider. This app forwards the marker duration without adding its own cap or splitting pauses.

Valid submissions return a job ID, then the worker uses the Microsoft Translator token
method to generate an MP3. Generation failures report only **Audio generation failed** in
status responses and failure webhooks. Microsoft error bodies, token details, and network
exceptions are never forwarded to clients.

## Source map

| Location | Responsibility |
| --- | --- |
| `src/routes/` | HTTP validation, response status/shapes, service orchestration |
| `src/routes/test-me-here/+page.svelte` | Testing page, speech submission and job actions |
| `src/lib/components/testing/` | Health, recent jobs, audio playback, response display |
| `src/lib/client/test-api.ts` | Browser-side authenticated JSON requests |
| `src/hooks.server.ts` | Startup, authentication, CORS |
| `src/lib/types/tts.ts` | Request, job, listing, webhook types |
| `src/lib/server/config.ts` | Private environment configuration and reference defaults |
| `src/lib/server/auth.ts` | Shared constant-time API-key comparison |
| `src/lib/server/runtime.ts` | One process-local manager and retention worker |
| `src/lib/server/jobs/manager.ts` | UUIDs, queue, concurrency, memory records, listing |
| `src/lib/server/jobs/processor.ts` | Timeout, state transitions, storage, completion/failure notifications |
| `src/lib/server/jobs/retention.ts` | Per-job deletion timers and periodic cleanup |
| `src/lib/server/audio-storage.ts` | Safe paths, temporary writes, rename, streaming, listing, deletion |
| `src/lib/server/webhooks.ts` | Payload serialization and best-effort delivery |
| `src/lib/server/tts/provider.ts` | Connected synthesis adapter boundary |
| `src/lib/server/tts/ssml.ts` | Escaped speech document and public parameter conversion |
| `src/lib/server/tts/translator.ts` | Translator token cache and Microsoft Speech request |

## Synthesis integration

The provider follows [`src/edge-tts-translator-method.md`](src/edge-tts-translator-method.md).
Exact headers and signing constants were taken from the referenced existing experiment.
It obtains a Translator token and region, caches the token until three minutes before its
expiry, and sends one complete SSML document to Microsoft Speech. There is no expired-token
fallback, automatic retry, text chunking, Python process, or external proxy. An authorization
failure clears the matching cached token for the next job. Concurrent cold-cache requests
may each acquire a token. Output is 24 kHz, 48 kbps, mono MP3, streamed into temporary storage.

The adapter honors cancellation and releases the response stream when finished or aborted.
Storage owns temporary files and publication. Restart the development
process after changing the provider: the runtime singleton deliberately survives hot reloads.

The reference defaults (`voice`, `pitch`, `speed`, `volume`) remain the public request contract.
Speed converts to a percentage with `trunc((speed - 1) * 100)`; volume converts with
`trunc(volume) - 100`; pitch becomes signed Hz. Text and attributes are XML-escaped.
Invalid numeric speed/volume values fail in the worker rather than exposing conversion errors.
No new request-time numeric ranges, voice allowlist, or provider pacing were added.
The queue's concurrency and whole-job processing timeout still apply. The old Edge WebSocket
retry/rate-limit settings are not used by this HTTPS method. No new packages are required.

## Compatibility and deliberate differences

- Request fields/defaults, text length checks, HTTP 200 job acceptance, disk-first status,
  top-level job list, download minimum of 100 bytes, and deletion response are carried over.
  Extra request fields are ignored. Text lengths/previews count Unicode code points.
- Status messages now distinguish queued, processing, completed, and failed jobs.
  Failed jobs always say `"Audio generation failed"`, including in outgoing failure webhooks.
- API errors retain the reference's `detail` envelope. Framework validation messages are
  representative rather than byte-for-byte Pydantic output. Python and JavaScript whitespace
  classifications can differ at rare Unicode boundaries. Stack traces and request text are
  not exposed in unexpected-error responses or logged as failed-request files.
- File identifiers cannot escape the configured audio directory. All file operations share
  one absolute directory, defaulting to this app's `audio_files` when launched here.
  No existing Python files are imported or migrated automatically. `AUDIO_DIR` can explicitly
  select a different directory; its retention policy will apply to MP3/temp files there.
- The queue uses FIFO for equal-priority submissions, avoiding the original infinite
  reprioritization loop for old jobs. The capacity check remains waiting jobs `> concurrency * 2`.
- Active processing files/jobs are excluded from periodic cleanup. Completed files and stale
  temp files otherwise expire at `AUTO_DELETE_DELAY`; completed/failed memory metadata expires
  after one hour, other non-processing jobs after two hours. Sweeps run every 60 seconds after
  the previous sweep ends. Manual deletion still sends no webhook and does not cancel synthesis.
- Webhooks preserve their payload keys, HTTP-200-only acknowledgment, three attempts,
  10-second attempt timeout, and 1/2.1/4.2-second backoff. Completion/failure delivery has the
  five-second outer deadline; deletion delivery does not. Shutdown aborts outstanding requests.
  Delivery is unsigned and best effort, with no persistent retry queue.
- Timestamps remain local ISO strings without an offset; JavaScript records milliseconds,
  whereas Python can include microseconds. The ETag uses the job ID, not Python's process hash.
- CORS permits all origins for API-key requests, but does not enable cookie credentials.
  Preflight requests do not require the key. There is no cookie authentication contract.
- Health keeps the original response fields and HTTP 200 behavior and omits tracebacks.
  A healthy local state does not prove provider connectivity or webhook delivery.

## Browser capacity testing

Deploy the app and open `/load-test` (production: `https://speechma.crikk.com/load-test`).
The API playground links to this light-theme page. No extra service, package, host terminal,
or Docker socket access is needed.

1. Enter the existing service API key and click **Connect & monitor**. The key starts blank,
   stays in tab memory, and is never included in page data or reports. Connecting sends no
   speech requests.
2. Use the longer default speech sample, or enter representative text. The default is intended
   to exceed 30 seconds at normal speed; actual duration depends on voice and speed and has not
   been measured. Separate texts with a line containing `---` to rotate through multiple scripts.
   Voice settings and run limits are collapsed by default.
3. Use **Add batch** for a finite number of jobs, or **Maintain this target** / the preset buttons
   to replace completed jobs continuously. Maintained targets support 1–200 outstanding requests,
   with presets for 10, 50, 100, 150, and 200. Watch overall CPU/RAM and the submitted/completed/error
   counts. The client cap is 200 independently of the server worker limit. To process 200 jobs
   simultaneously, production `MAX_CONCURRENT_REQUESTS` must also allow 200; otherwise extras queue.
   The page does not change that server setting.
4. **Pause new jobs** clears unsent batch work and replenishment. **Drain & finish** waits for
   tracked jobs to finish or their observation timeout. Neither cancels accepted server work.
5. Expand **Job details & audio** for per-job status and **Listen / download**. **Download
   report** exports all job records and resource samples without speech text or credentials.
   **New run** resets the local counters when no jobs remain tracked; scripts and limits can
   then be changed.

Live metrics are read from the authenticated, uncached `GET /api/load-test/metrics` endpoint.
It uses the existing API-key authentication hook and exposes no environment or credential values.
The page samples every five seconds, and the server shares/caches resource measurements across
tabs for one second. There is no resource-monitor background worker or disk scan.

The resource panel shows only overall server CPU and RAM. CPU uses the whole machine scale,
across all OS-visible CPU cores. RAM shows used, available, and total memory. The first CPU
reading needs a second sample. Each resource has a usage bar with its current value on the left,
maximum on the right, and percentage inside the bar. Colors are visual guides: green below 70%,
amber from 70% to under 90%, and red at 90% and above. They are not measured capacity limits.
Node-process and cgroup resource collection and response fields
have been removed from the browser metrics endpoint. No Docker CLI or daemon access is required.

The server worker limit belongs to the responding Node process. Resource readings describe
that server and do not aggregate multiple hosts. The browser drives this test: keep the tab
open and active. Background-tab timer throttling can affect the load. Closing, refreshing, or
disconnecting loses local tracking; accepted jobs, retention, and outgoing webhooks continue
normally. No speech requests run just from opening the page. Failed speech/rejected requests
pause replenishment; uncertain submission or job-status outcomes lock new submissions rather
than retrying work that may still run. Monitoring loss also pauses new submissions.

Detailed completion times remain in the downloaded report. API completion does not check MP3
validity or spoken-text completeness; the audio preview supports manual inspection. Resource
readings and client counters are sampled and are not exact Microsoft-side connection counts.

Browser feature source map:

| Location | Responsibility |
| --- | --- |
| `src/routes/load-test/` | Page controls, input validation, run/report orchestration, public limits |
| `src/lib/client/load-test.ts` | Browser job dispatch, concurrency, status tracking, pause/drain and reports |
| `src/lib/components/testing/LoadTestMetrics.svelte` | Live overall CPU/RAM polling and usage display |
| `src/lib/components/testing/ResourceUsageBar.svelte` | Reusable current/maximum usage bar and color guide |
| `src/lib/server/system-metrics.ts` | Shared overall CPU/RAM sampling |
| `src/routes/api/load-test/metrics/+server.ts` | Authenticated overall resources and server worker limit |

Approved local validation on 2026-10-22: project check passed with zero errors/warnings;
changed Svelte components passed the source analyzer. In-process mocks covered finite batches,
script rotation, target increases/decreases, replenishment, pause/drain, job/time budgets,
generation failures, rejected/uncertain requests, observation timeouts, disposal, report privacy,
the resource cache, and metrics endpoint authentication/queue counts. No service was started,
no production request was sent, and no deployment, browser playback, build, or live Linux
cgroup validation was performed for this addition.

Simplification checks on 2026-10-24 passed: project check with zero errors/warnings, Svelte
source analysis, and local mocked controller/endpoint/resource checks. The mock maintained 200
outstanding requests, replaced completed jobs, and stopped new submissions when paused. Metrics
checks confirmed only overall resources are returned, with authentication and no-store preserved.
No real speech requests, production load tests, service starts, or deployment were performed.

The subsequent usage-bar UI update is source-only; the user chose to perform its checks and
testing themselves. No source analyzer, type check, build, browser test, or service start was
run for that update.

## Runtime limits

For interactive production capacity measurement, see
[`scripts/load-test/README.md`](scripts/load-test/README.md). The standalone Node terminal
client supports finite batches, adjustable maintained concurrency, Linux host/Docker metrics,
and JSONL reports without installing packages or starting a web service. `/health` now also
exposes `processing_jobs_count`, `worker_slots_in_use`, and `max_concurrent_requests`; the
existing `active_jobs_size` remains the waiting queue count. Worker slots include webhook
completion time. These new health fields require deploying the source changes, and all counts
remain per Node process.

This app needs a long-running Node process (`adapter-node`), not a short-lived serverless
request runtime. The queue, job metadata, concurrency limit, and timers belong to one process.
Restarting loses queued/running metadata; surviving MP3s remain discoverable from disk.
There is no database, durable queue, shared worker coordination, or automatic scaling support.
The adapter-node shutdown event stops dispatch and cleanup and signals active jobs to abort.
Providers must implement cooperative cancellation; a timeout alone cannot terminate arbitrary
non-cooperative work. Hostname, TLS termination, reverse proxy, and deployment are not configured.

## Validation status

The approved type check passed with zero errors and zero warnings; the updated testing page
also passed the Svelte source analyzer. One approved live test of the actual provider and audio
storage produced a 33,696-byte MP3 in approximately 1.6 seconds. Media inspection confirmed
5.616 seconds of 24 kHz mono MP3 audio. The test used temporary storage and did not exercise
HTTP routes, browser playback, queue concurrency, or webhook delivery.
No packages were installed by the agent and no service,
build, or outgoing webhook request was started. Ask before additional validation, as required
by the project instructions.
