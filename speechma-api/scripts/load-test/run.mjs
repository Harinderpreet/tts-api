import { readFileSync, openSync, writeSync, closeSync } from 'node:fs';
import { parseArgs } from 'node:util';
import { createInterface } from 'node:readline';
import { performance } from 'node:perf_hooks';
import { ResourceMonitor } from './resources.mjs';

const usage = `Run with Node.js 24+ (no packages required):
  node scripts/load-test/run.mjs --base-url BASE_URL --request REQUEST_JSON_FILE \\
    --max-concurrency N --max-jobs N --duration-seconds N [--initial N] \\
    [--container EXACT_CONTAINER_NAME] [--report NEW_JSONL_FILE]

API_KEY must be set in the environment. --container can be repeated.
Optional: --poll-seconds 2 --sample-seconds 5 --http-timeout-seconds 15
          --job-timeout-seconds 900
No jobs start by default. Interactive commands:
  add N       Submit N additional jobs, bounded by --max-concurrency.
  target N    Maintain N outstanding jobs until paused or a budget is reached.
  pause       Clear unsent batch jobs and stop replenishing; keep monitoring.
  drain       Pause, wait for outstanding jobs, save summary, then exit.
  status      Display current counters.
  quit        Exit monitoring immediately; server jobs keep running.
  help        Show this text.
Ctrl+C drains; a second Ctrl+C exits monitoring immediately.`;

function options() {
  const { values } = parseArgs({ options: {
    'base-url': { type: 'string' }, request: { type: 'string' },
    'max-concurrency': { type: 'string' }, 'max-jobs': { type: 'string' },
    'duration-seconds': { type: 'string' }, initial: { type: 'string', default: '0' },
    container: { type: 'string', multiple: true, default: [] }, report: { type: 'string' },
    'poll-seconds': { type: 'string', default: '2' },
    'sample-seconds': { type: 'string', default: '5' },
    'http-timeout-seconds': { type: 'string', default: '15' },
    'job-timeout-seconds': { type: 'string', default: '900' },
    help: { type: 'boolean', default: false }
  } });
  if (values.help) { console.log(usage); return null; }
  for (const key of ['base-url', 'request', 'max-concurrency', 'max-jobs', 'duration-seconds']) {
    if (!values[key]) throw new Error(`Missing --${key}. Use --help for usage.`);
  }
  for (const key of ['max-concurrency', 'max-jobs', 'duration-seconds', 'initial',
    'poll-seconds', 'sample-seconds', 'http-timeout-seconds', 'job-timeout-seconds']) {
    const number = Number(values[key]);
    if (!Number.isSafeInteger(number) || number < (key === 'initial' ? 0 : 1)) {
      throw new Error(`--${key} must be a ${key === 'initial' ? 'nonnegative' : 'positive'} integer.`);
    }
    values[key] = number;
  }
  if (values.initial > values['max-concurrency']) throw new Error('--initial exceeds --max-concurrency.');
  for (const key of ['duration-seconds', 'poll-seconds', 'sample-seconds',
    'http-timeout-seconds', 'job-timeout-seconds']) {
    if (values[key] > 2_147_483) throw new Error(`--${key} exceeds the Node timer limit.`);
  }
  const url = new URL(values['base-url']);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) {
    throw new Error('Base URL must be HTTP(S), without credentials, query, or fragment.');
  }
  if (!process.env.API_KEY?.trim()) throw new Error('Set API_KEY in the environment first.');
  let payload;
  try { payload = JSON.parse(readFileSync(values.request, 'utf8')); }
  catch { throw new Error('Cannot read request file as JSON.'); }
  if (!payload || Array.isArray(payload) || typeof payload.text !== 'string' || !payload.text.trim()) {
    throw new Error('Request file must be an object with nonempty text.');
  }
  values.base = url.href.replace(/\/$/, '');
  values.body = JSON.stringify(payload);
  return values;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const seconds = (ms) => Math.round(ms / 100) / 10;
const percentile = (sorted, p) => sorted.length ? sorted[Math.ceil(sorted.length * p) - 1] : null;

async function main(config) {
  const report = config.report ?? `tts-load-${new Date().toISOString().replace(/[:.]/g, '-')}.jsonl`;
  // Never overwrite a previous run; reports contain job IDs but no key or speech text.
  const file = openSync(report, 'wx', 0o600);
  const started = performance.now();
  const deadline = started + config['duration-seconds'] * 1000;
  const monitor = new ResourceMonitor();
  const active = new Map();
  const durations = [];
  const totals = { attempted: 0, accepted: 0, completed: 0, failed: 0, rejected: 0, unknown: 0 };
  let target = 0, pending = 0, draining = false, force = false, locked = false, finishing = false;
  let server = null, serverError = null, resources = null, lastCompleted = 0, lastSample = started;
  let throughput = 0;
  let peakOutstanding = 0, peakObservedProcessing = 0, sequence = 0;
  let resourcePeaks = { host_cpu_percent: null, host_memory_used_mib: null, containers: {} };
  let deadlineTimer, sampleTimer;

  function record(type, data) {
    writeSync(file, JSON.stringify({ time: new Date().toISOString(), elapsed_seconds: seconds(performance.now() - started), type, ...data }) + '\n');
  }
  function pause(reason) {
    target = 0;
    pending = 0;
    record('pause', { reason });
    console.log(`Paused: ${reason}`);
  }
  function uncertainty(reason, job) {
    totals.unknown++;
    locked = true;
    pause(reason);
    record('unknown', { job_id: job.id, attempt: job.attempt, reason });
    console.log('New submissions are locked for this run because server work may still be outstanding.');
  }
  async function api(path, method = 'GET', body) {
    const response = await fetch(`${config.base}${path}`, {
      method, redirect: 'error',
      headers: { 'api-key': process.env.API_KEY, ...(body ? { 'Content-Type': 'application/json' } : {}) },
      body, signal: AbortSignal.timeout(config['http-timeout-seconds'] * 1000)
    });
    let data;
    try { data = await response.json(); } catch { /* Status still identifies definite rejections. */ }
    return { status: response.status, ok: response.ok, data };
  }
  async function runJob(job) {
    try {
      let submission;
      try { submission = await api('/tts', 'POST', config.body); }
      catch { uncertainty('Submission transport error; acceptance is unknown. No automatic retry.', job); return; }
      if (!submission.ok) {
        if (submission.status >= 400 && submission.status < 500) {
          totals.rejected++;
          pause(`Submission rejected with HTTP ${submission.status}.`);
          record('rejected', { attempt: job.attempt, http_status: submission.status });
        } else uncertainty(`Submission returned HTTP ${submission.status}; acceptance is unknown.`, job);
        return;
      }
      if (typeof submission.data?.job_id !== 'string' || !submission.data.job_id) {
        uncertainty('Submission returned no usable job ID.', job); return;
      }
      job.id = submission.data.job_id;
      job.state = 'accepted';
      totals.accepted++;
      record('accepted', { attempt: job.attempt, job_id: job.id });
      const expires = job.started + config['job-timeout-seconds'] * 1000;
      while (!force && performance.now() < expires) {
        let result;
        try { result = await api(`/tts/status/${encodeURIComponent(job.id)}`); }
        catch { uncertainty('Status transport error; the accepted job may still run.', job); return; }
        const status = result.data?.status;
        if (!result.ok || !['queued', 'processing', 'completed', 'failed'].includes(status)) {
          uncertainty(`Status unavailable (HTTP ${result.status}); the accepted job may still run.`, job); return;
        }
        if (job.state !== status) {
          record('job_status', { attempt: job.attempt, job_id: job.id, status });
          job.state = status;
        }
        if (status === 'completed' || status === 'failed') {
          totals[status]++;
          const elapsed = seconds(performance.now() - job.started);
          if (status === 'completed') durations.push(elapsed);
          record('job_finished', { job_id: job.id, status, end_to_end_seconds: elapsed });
          if (status === 'failed') pause('A speech job failed. Inspect the run before explicitly resuming.');
          return;
        }
        await sleep(Math.min(config['poll-seconds'] * 1000, Math.max(0, expires - performance.now())));
      }
      uncertainty(force ? 'Monitoring exited before job completion.' : 'Job observation timed out; server job is not cancelled.', job);
    } finally {
      active.delete(job.attempt);
      pump();
    }
  }
  function pump() {
    if (force || draining || locked || performance.now() >= deadline) return;
    while (active.size < config['max-concurrency'] && (pending > 0 || active.size < target)) {
      if (totals.attempted >= config['max-jobs']) { drain('Maximum job budget reached.'); break; }
      if (pending > 0) pending--;
      const job = { attempt: ++sequence, id: null, state: 'submitting', started: performance.now() };
      totals.attempted++;
      active.set(job.attempt, job);
      peakOutstanding = Math.max(peakOutstanding, active.size);
      void runJob(job).catch(() => {
        locked = true;
        pause('Unexpected client error; review the report before another run.');
      });
    }
  }
  function drain(reason) {
    if (draining) return;
    draining = true;
    pause(reason);
    console.log('Draining outstanding test jobs. This does not cancel server work.');
  }
  function display() {
    const states = {};
    for (const job of active.values()) states[job.state] = (states[job.state] ?? 0) + 1;
    peakObservedProcessing = Math.max(peakObservedProcessing, states.processing ?? 0);
    console.log(`\n${seconds(performance.now() - started)}s | target ${target} | unsent ${pending} | outstanding ${active.size}/${config['max-concurrency']} | ${JSON.stringify(states)}`);
    console.log(`Test totals: ${JSON.stringify(totals)}`);
    const sorted = durations.toSorted((a, b) => a - b);
    console.log(`Completed/s since last sample: ${throughput.toFixed(2)} | successful end-to-end p50 ${percentile(sorted, 0.5) ?? 'n/a'}s | p95 ${percentile(sorted, 0.95) ?? 'n/a'}s (whole run)`);
    if (server) console.log(`Server process: queued ${server.queued ?? 'n/a'} | processing ${server.processing ?? 'n/a'} | worker slots ${server.slots ?? 'n/a'}/${server.limit ?? 'n/a'}`);
    if (serverError) console.log(`Server metrics: ${serverError}`);
    if (resources) {
      console.log(`Local host: ${JSON.stringify(resources.host)}`);
      for (const container of resources.containers) console.log(`Container: ${JSON.stringify(container)}`);
    }
  }
  function peak(previous, current) {
    return typeof current === 'number' && Number.isFinite(current) ? Math.max(previous ?? current, current) : previous;
  }
  async function sample() {
    const [health, usage] = await Promise.all([
      api('/health').catch(() => null), monitor.sample(config.container)
    ]);
    resources = usage;
    server = null;
    serverError = null;
    if (health?.ok && health.data?.status === 'healthy') {
      const data = health.data;
      server = { queued: data.active_jobs_size, processing: data.processing_jobs_count,
        slots: data.worker_slots_in_use, limit: data.max_concurrent_requests };
    } else {
      serverError = health ? `Unavailable/unhealthy (HTTP ${health.status})` : 'Transport error';
      if (active.size || target || pending) pause('Health monitoring failed.');
    }
    resourcePeaks.host_cpu_percent = peak(resourcePeaks.host_cpu_percent, usage.host.cpu_percent);
    resourcePeaks.host_memory_used_mib = peak(resourcePeaks.host_memory_used_mib, usage.host.memory_used_mib);
    for (const container of usage.containers) {
      const current = resourcePeaks.containers[container.name] ?? { cpu_percent: null, memory_percent: null };
      current.cpu_percent = peak(current.cpu_percent, container.cpu_percent);
      current.memory_percent = peak(current.memory_percent, container.memory_percent);
      resourcePeaks.containers[container.name] = current;
    }
    const now = performance.now();
    throughput = (totals.completed - lastCompleted) / ((now - lastSample) / 1000);
    record('sample', { totals: { ...totals }, target, pending, outstanding: active.size,
      observed_processing: [...active.values()].filter((job) => job.state === 'processing').length,
      completed_per_second: throughput,
      server, server_error: serverError, resources });
    lastCompleted = totals.completed;
    lastSample = now;
    display();
  }

  const input = createInterface({ input: process.stdin, output: process.stdout, terminal: process.stdin.isTTY });
  input.on('line', (line) => {
    const [command, value, extra] = line.trim().split(/\s+/);
    if (command === 'help') { console.log(usage); return; }
    if (command === 'status') { display(); return; }
    if (command === 'pause') { pause('Operator paused.'); return; }
    if (command === 'drain') { drain('Operator requested drain.'); return; }
    if (command === 'quit') { force = true; drain('Operator exited monitoring.'); return; }
    if (!['add', 'target'].includes(command)) { console.log('Use add N, target N, pause, drain, status, quit, or help.'); return; }
    const number = Number(value);
    if (extra || !/^\d+$/.test(value ?? '') || !Number.isSafeInteger(number)) { console.log('Enter a nonnegative integer.'); return; }
    if (draining || locked || performance.now() >= deadline) { console.log('New submissions are disabled for this run.'); return; }
    if (serverError) { console.log('Wait for healthy server metrics before submitting.'); return; }
    if (command === 'target' && number > config['max-concurrency']) { console.log('Target exceeds --max-concurrency.'); return; }
    if (command === 'add' && number > config['max-jobs'] - totals.attempted - pending) { console.log('Batch exceeds the remaining job budget.'); return; }
    if (command === 'target') target = number;
    else pending += number;
    record('command', { command, number });
    pump();
  });
  input.on('close', () => { if (!finishing) drain('Input closed.'); });
  function interrupt() {
    if (draining) force = true;
    else drain('Ctrl+C received.');
  }
  input.on('SIGINT', interrupt);
  process.on('SIGINT', interrupt);

  try {
    console.log(`Report: ${report}\n${usage}\nHost metrics describe THIS machine. No jobs start unless --initial or an interactive command requests them.`);
    record('start', { limits: { concurrency: config['max-concurrency'], jobs: config['max-jobs'],
      submission_seconds: config['duration-seconds'], poll_seconds: config['poll-seconds'],
      job_timeout_seconds: config['job-timeout-seconds'] } });
    // Initial health/resource sampling finishes before accepting any load commands.
    serverError = 'Initial health check in progress';
    await sample();
    if (serverError) throw new Error('Initial health check failed. No speech jobs were sent.');
    target = config.initial;
    deadlineTimer = setTimeout(() => drain('Submission duration reached.'), Math.max(0, deadline - performance.now()));
    pump();
    async function tick() {
      try { await sample(); }
      catch { locked = true; pause('Monitoring/reporting failed.'); }
      if (!force) sampleTimer = setTimeout(tick, config['sample-seconds'] * 1000);
    }
    sampleTimer = setTimeout(tick, config['sample-seconds'] * 1000);
    while (!force && !(draining && active.size === 0)) await sleep(200);
    const unresolved = [...active.values()].map((job) => ({ job_id: job.id, attempt: job.attempt, status: job.state }));
    const sorted = durations.toSorted((a, b) => a - b);
    const summary = { totals, elapsed_seconds: seconds(performance.now() - started),
      peak_outstanding: peakOutstanding, peak_sampled_test_processing: peakObservedProcessing,
      successful_end_to_end_seconds: { p50: percentile(sorted, 0.5), p95: percentile(sorted, 0.95), max: sorted.at(-1) ?? null },
      sampled_resource_peaks: resourcePeaks, still_observed_jobs: unresolved,
      note: 'Completion means API-reported completion; MP3 validity and content completeness were not checked.' };
    record('summary', summary);
    console.log(`\nSummary:\n${JSON.stringify(summary, null, 2)}\nReport: ${report}`);
    if (totals.unknown || unresolved.length || totals.failed || totals.rejected) process.exitCode = 1;
  } catch {
    console.error('Load tester stopped. Check server health, report file access, and configuration.');
    console.error('Accepted server jobs may continue; see accepted job IDs in the report.');
    process.exitCode = 1;
  } finally {
    finishing = true;
    force = true;
    clearTimeout(deadlineTimer);
    clearTimeout(sampleTimer);
    input.close();
    process.removeListener('SIGINT', interrupt);
    closeSync(file);
    // Outstanding fetches must not keep a forced exit alive or mutate a closed report.
    process.exit(process.exitCode ?? 0);
  }
}

try {
  const config = options();
  if (config) await main(config);
} catch (error) {
  // Do not print response bodies, headers, payloads, or network exception details.
  console.error(error instanceof Error && !error.message.includes(process.env.API_KEY || '\0')
    ? error.message : 'Load tester failed. Check configuration and the report.');
  process.exitCode = 1;
}
