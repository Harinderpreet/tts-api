# Interactive speech capacity tester

An independent terminal client for the SvelteKit speech API. Uses Node.js 24+ built-ins;
no package installation, application restart, or new listening service is needed to run
the client. It submits through `/tts` and follows `/tts/status/{job_id}` until completion.
It does not bypass the production queue, provider, storage, retention, or webhooks.

## Run on the server

Copy this entire `load-test` directory to the Linux server, outside the application
container. Run it on the host to measure host CPU and RAM. Running it on a laptop measures
the laptop; running it inside a container does not provide a reliable host view of resource
limits. Docker monitoring requires the existing Docker CLI and access to its daemon.
If Node.js 24+ is unavailable on the host, arrange that runtime before running this tool.

From this directory, copy `request.example.json` to `request.json` and edit the text,
voice, and other supported settings to match actual production work. The example parameters
come from this repository's API defaults. Repeat separate runs for short, typical, and long
scripts; capacity depends on the workload. No text or API key is written to the report.

Enter the API key without putting its literal value in shell history (bash/zsh):

```sh
printf 'API key: '
read -r -s API_KEY
export API_KEY
printf '\n'
```

Set `TTS_BASE_URL` to your actual service base URL, including any deployed path prefix,
without `/tts` at the end. No production hostname is assumed. This example deliberately
starts with zero generated jobs. The limits are example operator choices, not measured
server capacity:

```sh
node run.mjs \
  --base-url "$TTS_BASE_URL" \
  --request request.json \
  --max-concurrency 20 \
  --max-jobs 200 \
  --duration-seconds 600 \
  --report run-01.jsonl
```

For container metrics, add `--container` with the exact running container name or ID.
Repeat the flag for additional containers. On Docker Swarm use the running task container
name/ID, not the service name. Discover current names with `docker ps`; none are guessed.
Docker CPU percentages use a per-core scale, while this tool's host CPU percentage covers
all host CPUs. They have different denominators and should not be compared directly.
Docker memory usage and its limit are displayed together.

## Controls during the run

| Command | Behavior |
| --- | --- |
| `add 10` | Submit ten more jobs, respecting the outstanding-job cap. No automatic replacement after the batch finishes. |
| `target 10` | Maintain ten outstanding test jobs, replacing finished jobs until paused or a budget is reached. |
| `target 5` | Reduce the maintained target; existing jobs finish normally. |
| `target 0` | Stop maintaining concurrency; previously added unsent batch jobs still submit. |
| `pause` | Stop replenishment and clear unsent batch work; continue monitoring accepted jobs. |
| `status` | Display the latest metrics and current test counters. |
| `drain` | Pause and exit after tracked jobs finish or their observation timeout expires. |
| `quit` | Exit monitoring immediately; accepted server jobs continue. |

With `target 10` active, `add 5` adds five one-off submissions into available slots up to
`--max-concurrency`; the maintained target stays ten. These commands always share the same
run limits. Ctrl+C drains; a second Ctrl+C exits immediately. Closing standard input drains.
For an unattended run, keep stdin open and use `--initial N` to set an initial maintained
target explicitly.

`--max-jobs` bounds all submission attempts, including failures. `--duration-seconds` bounds
the submission window starting at tool startup, including baseline monitoring. Expiry drains
instead of cancelling server work. These limits do not change `MAX_CONCURRENT_REQUESTS` on
the service. More submitted work than the server allows will queue and does not prove higher
generation concurrency. In particular, testing beyond the configured server limit requires
a deliberate configuration change and deployment outside this tool.

## Reading the output

- **Outstanding**: this run's submitted/queued/processing jobs that have not reached a known
  terminal state, including submissions still waiting for acknowledgment.
- **Test states**: last observed per-job states. Polling can miss brief processing intervals;
  they are sampled observations, not exact instantaneous upstream connection counts.
- **Server queued**: the existing `/health` `active_jobs_size` field actually means waiting jobs.
- **Server processing**: new `processing_jobs_count`, jobs currently synthesizing or saving audio.
- **Worker slots**: new `worker_slots_in_use`, which also includes completion/failure webhook
  handling before the worker slot is released. The denominator is `max_concurrent_requests`.
- **Local host**: sampled total host CPU busy percentage, RAM used/total/available in MiB.
  The first CPU sample is unavailable because calculating utilization needs two observations.
- **Container**: Docker CPU percentage and memory usage/limit for each specified container.
- **Throughput**: successful jobs completed per second between samples, displayed and saved to the report.
- **p50/p95**: successful end-to-end time from submission through observed completion, including
  queue and polling delays. Failed/unknown jobs are counted separately, not hidden in percentiles.

The additional health fields require deploying the accompanying application source changes.
Before deployment, the client still works and displays `n/a` for those fields. All health counts
belong to the responding Node process; they include normal traffic in that process. They do
not aggregate replicas. With multiple replicas and process-local jobs, status polling may hit
a process that does not own the job; this tester locks submissions on that uncertainty.

Each JSONL report contains timestamped samples, control changes, job IDs, status changes,
per-job end-to-end times, and a final summary. The summary includes successful p50/p95/max
time, sampled resource peaks, and unfinished jobs still being monitored at a forced exit.
Unknown jobs that were no longer observable are recorded in individual `unknown` events.
Reports are created with owner-only permissions and never overwrite existing files.
The request body, API key, raw provider errors, and response bodies are not recorded.

HTTP timeouts, unreadable accepted-job status, or job observation timeouts stop and lock new
submissions for the run. They cannot prove that server work has ended, so the tester never
automatically retries or replaces that uncertain work. Confirm it has finished before starting
another run. Definite request rejections, speech failures, and unhealthy health monitoring
pause replenishment; an explicit later command can resume after investigation and health
recovery. Reports and exit status distinguish failures, rejections, and unknown results.
The client never deletes audio or cancels accepted work. Existing production retention and
webhooks still apply to test jobs.

The tool reports API completion. It does not download/decode MP3s or check spoken text
completeness. Reported processing jobs are not a count of Microsoft-side connections.

## Find a sustainable concurrency level

1. Record baseline host/container usage before adding jobs. Use the same request corpus
   and container CPU/RAM limits that production uses.
2. Start with a small maintained target and increase in steps. The values `5`, `10`, `20`
   are illustrative starting steps, not a capacity recommendation. Hold each step long
   enough to cover representative long jobs and provider throttling behavior.
3. Compare successful throughput and p95 completion time with failures, queue growth,
   CPU, and available RAM. Low CPU alone does not establish spare capacity: upstream
   throttling, networking, and queue limits can dominate.
4. Pause or drain if customer latency or failures increase. The client pauses on individual
   failures/health loss, but does not invent CPU/RAM or latency thresholds for your server.
5. Keep a production margin below the highest stable step, then repeat with mixed script
   lengths and sustained traffic. A short successful burst is not a sustained capacity result.

Normal customer traffic shares the queue, resources, output retention, and webhook delivery.
Use a low-traffic period or a comparable isolated instance for finding the limit; a live
production test contributes real work and can affect other requests. For larger tests,
run the generator on another machine and monitor resources on the server separately so the
generator does not become the bottleneck or distort server CPU measurements.

Defaults: status polling 2 seconds, resource sampling 5 seconds after the previous sample
finishes, HTTP timeout 15 seconds, job observation timeout 900 seconds. Override with
`--poll-seconds`, `--sample-seconds`, `--http-timeout-seconds`, and `--job-timeout-seconds`.
Match the observation timeout to your server processing timeout plus possible queue delay.
Polling adds approximately one HTTP request per outstanding job per polling interval.
Health currently scans audio storage; allow for its monitoring overhead when choosing intervals.

References: [Docker stats](https://docs.docker.com/reference/cli/docker/container/stats/),
[API load testing and latency/error criteria](https://grafana.com/docs/k6/latest/testing-guides/api-load-testing/).

## Validation status

Approved local validation passed on 2026-10-15:

- Node syntax checks for both terminal tool modules.
- Project type/component checks: zero errors and zero warnings.
- In-process mock API scenarios: maintained concurrency, finite batches starting at zero,
  ambiguous submission acceptance, failed speech generation, and unavailable job status.
  These checked the concurrency cap, submission budget, outcome counts, exit statuses,
  and absence of the API key from the reports.

The mock intercepted requests without starting a listening service or contacting production.
No build, deployment, real synthesis load test, or production Linux/Docker resource validation
has been performed. Production concurrency capacity remains unmeasured. Request approval
before additional tests.
