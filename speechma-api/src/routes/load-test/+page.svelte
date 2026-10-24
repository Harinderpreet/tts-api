<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import type { PageProps } from './$types';
  import { BrowserLoadTest, emptyLoadSnapshot } from '$lib/client/load-test';
  import type { ServerMetrics } from '$lib/types/load-test';
  import LoadTestMetrics from '$lib/components/testing/LoadTestMetrics.svelte';
  import JobAudio from '$lib/components/testing/JobAudio.svelte';
  import '$lib/styles/test-page.css';

  let { data }: PageProps = $props();
  let apiKey = $state('');
  let connected = $state(false);
  let metrics = $state<ServerMetrics | null>(null);
  let text = $state(`On a quiet morning, a small team gathered around a table to plan a new community garden. The space outside had been empty for years, but everyone could imagine what it might become. There would be paths between the beds, flowers near the entrance, and a comfortable bench beneath the old tree. Before planting anything, they walked around the ground and talked about sunlight, water, and the changing seasons.

One person suggested growing tomatoes and beans. Another wanted herbs that people could use in their kitchens. A teacher offered to bring students every Friday so they could learn how seeds become plants. The group agreed to leave plenty of room for visitors, including people who used wheelchairs or needed a place to rest. Every decision was written down, and each volunteer chose a small task for the following week.

By the afternoon, the first garden bed was ready. Nobody expected the whole project to be finished in a day. They knew that steady progress mattered more than rushing. Over the next few months, they would return to water the plants, repair the paths, and share what they had learned. Some ideas would work well, while others would need to change. What mattered most was that the space would belong to everyone, and that each visit would make it a little more welcoming than before.`);
  let voice = $state('en-US-AriaNeural');
  let pitch = $state('0');
  let speed = $state('1');
  let volume = $state('100');
  let style = $state('');
  const maxConcurrent = 200;
  let maxJobs = $state(5000);
  let durationSeconds = $state(1800);
  let jobTimeoutSeconds = $state(900);
  let count = $state(5);
  let snapshot = $state(emptyLoadSnapshot());
  let error = $state('');
  let now = $state(Date.now());
  let audioJobId = $state('');
  let runner: BrowserLoadTest | null = null;
  const scripts = $derived(text.split(/^\s*---\s*$/m).map((script) => script.trim()).filter(Boolean));
  const textError = $derived(!scripts.length ? 'Enter at least one script.' : scripts.some((script) =>
    [...script].length < data.minTextLength || [...script].length > data.maxTextLength)
    ? `Each script must have ${data.minTextLength}–${data.maxTextLength.toLocaleString()} characters.` : '');
  const limitsError = $derived([maxJobs, durationSeconds, jobTimeoutSeconds].some((value) =>
    !Number.isSafeInteger(value) || value < 1) ? 'Enter positive whole numbers for the run limits.'
    : Math.max(durationSeconds, jobTimeoutSeconds) > 2147483 ? 'Duration exceeds the supported timer range.' : '');
  const countError = $derived(!Number.isSafeInteger(count) || count < 1 ? 'Enter a positive whole number of jobs.' : '');
  const canSubmit = $derived(connected && metrics?.ready && !textError && !limitsError && !countError
    && !snapshot.draining && !snapshot.ended && !snapshot.locked);
  const elapsed = $derived(snapshot.started ? Math.max(0, Math.floor((now - snapshot.started) / 1000)) : 0);

  onMount(() => {
    jobTimeoutSeconds = Math.max(900, Math.ceil(data.processTimeoutSeconds));
    const timer = setInterval(() => { now = Date.now(); }, 1000);
    return () => clearInterval(timer);
  });
  onDestroy(() => runner?.dispose());

  function connect() {
    if (!apiKey.trim()) return;
    error = '';
    connected = true;
  }

  function receiveMetrics(value: ServerMetrics) {
    metrics = value;
    runner?.recordMetrics(value);
    if (!value.ready) runner?.pause('Service is unavailable. New submissions are paused.');
  }

  function metricsFailed() {
    metrics = null;
    runner?.pause('Server monitoring failed. New submissions are paused.');
  }

  function start(action: 'add' | 'target', amount = count) {
    if (!canSubmit) return;
    error = '';
    if (action === 'target' && amount > maxConcurrent) { error = 'Target exceeds the outstanding-job limit.'; return; }
    if (action === 'add' && amount + snapshot.pending + snapshot.attempted > maxJobs) { error = 'Batch exceeds the remaining job budget.'; return; }
    runner ??= new BrowserLoadTest(apiKey, scripts.map((script) => ({
      text: script, voice, pitch, speed, volume, ...(style.trim() ? { style: style.trim() } : {})
    })), { maxConcurrent, maxJobs, durationSeconds, jobTimeoutSeconds }, (value) => { snapshot = value; });
    if (action === 'add') runner.add(amount);
    else runner.setTarget(amount);
  }

  function newRun() {
    if (snapshot.outstanding) return;
    if (snapshot.unknown && !window.confirm('Some jobs have unknown outcomes. Start a new run only after confirming they are no longer running on the server. Continue?')) return;
    runner?.dispose();
    runner = null;
    snapshot = emptyLoadSnapshot();
    audioJobId = '';
    error = '';
  }

  function disconnect() {
    if (snapshot.outstanding || snapshot.target || snapshot.pending) return;
    runner?.dispose();
    runner = null;
    snapshot = emptyLoadSnapshot();
    audioJobId = '';
    connected = false;
    metrics = null;
  }

  function download() {
    if (!runner) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(runner.report(), null, 2)], { type: 'application/json' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `speechma-load-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
</script>

<svelte:head>
  <title>Speechma · Load testing</title>
  <meta name="robots" content="noindex, nofollow" />
</svelte:head>

<main class="test-page">
  <div class="test-shell">
    <header class="page-heading">
      <span class="eyebrow">SPEECHMA / DEVELOPER TOOLS</span>
      <h1>Speech load testing</h1>
      <p>Add parallel jobs, raise the target gradually, and watch server CPU and RAM.</p>
      <a class="button" href="/test-me-here" target="_blank" rel="noopener noreferrer">Open single-request playground</a>
    </header>

    <section class="panel connection" aria-labelledby="connect-title">
      <div><h2 id="connect-title">Connect to this server</h2><p class="muted">Your API key stays in this tab’s memory. Connecting starts monitoring; it does not generate speech.</p></div>
      <div>
        <div class="field"><label for="load-api-key">API key</label><input id="load-api-key" type="password" bind:value={apiKey} disabled={connected} autocomplete="off" spellcheck="false" placeholder="Enter your API_KEY" /></div>
        <div class="actions">
          <button class="primary" type="button" onclick={connect} disabled={!apiKey.trim() || connected}>Connect & monitor</button>
          <button type="button" onclick={disconnect} disabled={!connected || snapshot.outstanding > 0 || snapshot.target > 0 || snapshot.pending > 0}>Disconnect</button>
        </div>
      </div>
    </section>

    <p class="notice">Keep this tab open while testing. Pause stops new submissions; accepted jobs continue running.</p>

    {#if connected}
      <LoadTestMetrics {apiKey} onmetrics={receiveMetrics} onerror={metricsFailed} />
    {/if}

    <div class="workspace-grid">
      <section class="panel" aria-labelledby="script-title">
        <h2 id="script-title">Speech scripts</h2>
        <fieldset disabled={snapshot.started !== null}>
          <div class="field"><label for="load-text">Text</label><textarea id="load-text" bind:value={text} rows="10" aria-describedby="script-hint"></textarea><span id="script-hint" class="muted">The longer default sample is intended to produce over 30 seconds of speech at normal speed. Exact duration depends on voice and speed. Separate scripts with a line containing --- to rotate between them.</span><span class="muted">{scripts.length} script(s) · {[...text].length.toLocaleString()} total characters</span></div>
          <details>
            <summary>Voice settings</summary>
            <div class="advanced-fields">
              <div class="field"><label for="load-voice">Voice identifier</label><input id="load-voice" bind:value={voice} spellcheck="false" /></div>
              <div class="parameter-grid">
                <div class="field"><label for="load-pitch">Pitch</label><input id="load-pitch" bind:value={pitch} /></div>
                <div class="field"><label for="load-speed">Speed</label><input id="load-speed" bind:value={speed} /></div>
                <div class="field"><label for="load-volume">Volume</label><input id="load-volume" bind:value={volume} /></div>
              </div>
              <div class="field"><label for="load-style">Style (optional)</label><input id="load-style" bind:value={style} placeholder="general" /></div>
            </div>
          </details>
        </fieldset>
        {#if textError}<p class="error">{textError}</p>{/if}
        <p class="muted">Use New run to change scripts after testing starts.</p>
      </section>

      <section class="panel" aria-labelledby="controls-title">
        <h2 id="controls-title">Run controls</h2>
        <p class="muted">Choose how many jobs to add, or maintain up to 200 requests.</p>
        <div class="field"><label for="load-count">Number of jobs</label><input id="load-count" type="number" min="1" step="1" bind:value={count} /></div>
        <div class="actions">
          <button class="primary" type="button" onclick={() => start('add')} disabled={!canSubmit}>Add batch</button>
          <button type="button" onclick={() => start('target')} disabled={!canSubmit || count > maxConcurrent}>Maintain this target</button>
        </div>
        <p class="muted">A batch finishes once. A maintained target replaces completed jobs until paused or a limit is reached.</p>
        <div class="actions">
          {#each [10, 50, 100, 150, 200] as amount (amount)}
            <button type="button" onclick={() => start('target', amount)} disabled={!canSubmit || amount > maxConcurrent}>Maintain {amount}</button>
          {/each}
        </div>
        <details class="run-options">
          <summary>Run limits</summary>
          <fieldset class="advanced-fields" disabled={snapshot.started !== null}>
            <div class="field"><label for="load-budget">Maximum total jobs</label><input id="load-budget" type="number" min="1" step="1" bind:value={maxJobs} /></div>
            <div class="field"><label for="load-duration">Run duration (seconds)</label><input id="load-duration" type="number" min="1" step="1" bind:value={durationSeconds} /></div>
            <div class="field"><label for="load-timeout">Job observation timeout (seconds)</label><input id="load-timeout" type="number" min="1" step="1" bind:value={jobTimeoutSeconds} /></div>
          </fieldset>
          <p class="muted">Server worker limit: {metrics?.maxConcurrent ?? data.maxConcurrent}. Requests above that limit wait in the queue. The page does not change server configuration.</p>
        </details>
        {#if limitsError}<p class="error">{limitsError}</p>{/if}
        {#if snapshot.target > (metrics?.maxConcurrent ?? data.maxConcurrent)}
          <p class="muted">Maintaining {snapshot.target} requests. The server processes up to {metrics?.maxConcurrent ?? data.maxConcurrent} at once; the rest wait.</p>
        {/if}
        <div class="actions run-actions">
          <button type="button" onclick={() => runner?.pause()} disabled={!snapshot.target && !snapshot.pending}>Pause new jobs</button>
          <button type="button" onclick={() => runner?.drain()} disabled={!snapshot.started || snapshot.draining || snapshot.ended}>Drain & finish</button>
          <button type="button" onclick={newRun} disabled={!snapshot.started || snapshot.outstanding > 0}>New run</button>
          <button type="button" onclick={download} disabled={!snapshot.started}>Download report</button>
        </div>
        {#if countError || error}<p class="error" role="alert">{countError || error}</p>{/if}
      </section>
    </div>

    <section class="panel" aria-labelledby="results-title">
      <div class="section-heading"><div><h2 id="results-title">This run</h2><p class="muted">{elapsed}s elapsed · maintained target {snapshot.target} · unsent batch jobs {snapshot.pending}</p></div><span class={['badge', { 'error-badge': snapshot.locked }]}>{snapshot.locked ? 'Submissions locked' : snapshot.ended ? 'Finished' : snapshot.draining ? 'Draining' : snapshot.target || snapshot.pending ? 'Running' : 'Paused / ready'}</span></div>
      <p class="run-message" aria-live="polite">{snapshot.message}</p>
      <div class="result-grid">
        <div><span>Running / waiting</span><strong>{snapshot.outstanding}</strong></div>
        <div><span>Submitted</span><strong>{snapshot.attempted} / {maxJobs}</strong></div>
        <div><span>Completed</span><strong>{snapshot.completed}</strong></div>
        <div><span>Errors</span><strong>{snapshot.failed + snapshot.rejected + snapshot.unknown}</strong></div>
      </div>
      <details>
        <summary>Job details & audio</summary>
      <div class="table-scroll">
        <table>
          <thead><tr><th>Attempt</th><th>Job ID</th><th>Status</th><th>Time</th><th>Audio</th></tr></thead>
          <tbody>{#each snapshot.jobs as job (job.attempt)}<tr><td>{job.attempt}</td><td><code>{job.id ?? 'Awaiting response'}</code>{#if job.message}<small>{job.message}</small>{/if}</td><td>{job.status}</td><td>{job.finished ? `${((job.finished - job.started) / 1000).toFixed(1)}s` : '—'}</td><td><button type="button" disabled={job.status !== 'completed' || !job.id || !connected} onclick={() => { audioJobId = job.id ?? ''; }}>Listen / download</button></td></tr>{/each}</tbody>
        </table>
      </div>
      {#if !snapshot.jobs.length}<p class="empty">No speech requests have been sent from this page.</p>{/if}
        <p class="muted">Latest 30 jobs shown. Download the report for all jobs and resource samples.</p>
      </details>
    </section>
    {#if audioJobId && connected}
      <section class="panel" aria-labelledby="load-audio-title">
        <div class="section-heading"><div><h2 id="load-audio-title">Audio preview</h2><code>{audioJobId}</code></div><button type="button" onclick={() => { audioJobId = ''; }}>Close preview</button></div>
        {#key audioJobId}<JobAudio {apiKey} jobId={audioJobId} autoLoad={true} />{/key}
      </section>
    {/if}
  </div>
</main>

<style>
  .advanced-fields { padding-top: 16px; }
  .run-options { margin-top: 20px; }
  .run-actions { margin-top: 20px; padding-top: 18px; border-top: 1px solid #e4e9f1; }
  .run-message { background: #f2f6fc; border-radius: 8px; padding: 12px 16px; }
  .result-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; margin: 20px 0; }
  .result-grid div { display: flex; flex-direction: column; gap: 6px; }
  .result-grid span { color: #5b6b80; font-size: .78rem; }
  .result-grid strong { font-size: 1.3rem; letter-spacing: -.03em; }
  .table-scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: .82rem; text-align: left; }
  th, td { padding: 12px 8px; border-bottom: 1px solid #e4e9f1; }
  th { color: #5b6b80; font-weight: 600; }
  td small { display: block; color: #a32532; margin-top: 5px; }
  @media (max-width: 650px) { .result-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
