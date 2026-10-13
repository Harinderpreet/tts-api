<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { PageProps } from './$types';
  import { requestJson, type ApiResult } from '$lib/client/test-api';
  import ApiResponse from '$lib/components/testing/ApiResponse.svelte';
  import HealthCheck from '$lib/components/testing/HealthCheck.svelte';
  import RecentJobs from '$lib/components/testing/RecentJobs.svelte';
  import JobAudio from '$lib/components/testing/JobAudio.svelte';
  import JobStatusPoller from '$lib/components/testing/JobStatusPoller.svelte';
  import '$lib/styles/test-page.css';

  let { data }: PageProps = $props();
  let apiKey = $state('');
  let text = $state('Hello from Speechma. This is a test of speech generation.');
  // Count Unicode code points, matching the API rather than HTML's UTF-16 maxlength.
  const textLength = $derived([...text].length);
  const trimmedTextLength = $derived([...text.trim()].length);
  const textLengthError = $derived(
    textLength > data.maxTextLength
      ? `Text exceeds the maximum of ${data.maxTextLength.toLocaleString()} characters.`
      : trimmedTextLength < data.minTextLength
        ? `Enter at least ${data.minTextLength.toLocaleString()} characters, excluding surrounding whitespace.`
        : ''
  );
  let voice = $state('en-US-AriaNeural');
  let pitch = $state('0');
  let speed = $state('1');
  let volume = $state('100');
  let style = $state('');
  let jobId = $state('');
  let busy = $state('');
  let result = $state<ApiResult | null>(null);
  let error = $state('');
  let audioRevision = $state(0);
  let watchingJobId = $state('');
  let audioReadyFor = $state('');
  const controller = new AbortController();
  onDestroy(() => controller.abort());

  function resetTracking() {
    watchingJobId = '';
    audioReadyFor = '';
  }

  function receiveStatus(response: ApiResult) {
    result = response;
    if (!response.ok || !response.body || typeof response.body !== 'object' || !('status' in response.body)) return;
    if (response.body.status === 'completed') {
      watchingJobId = '';
      audioReadyFor = jobId.trim();
    } else if (response.body.status === 'failed') {
      resetTracking();
      error = 'Audio generation failed';
    } else if (response.body.status === 'queued' || response.body.status === 'processing') {
      watchingJobId = jobId.trim();
    }
  }

  function pollingFailed() {
    watchingJobId = '';
    error = 'Could not check job status. Use Check status to try again.';
  }

  function selectJob(id: string) {
    if (busy) return;
    resetTracking();
    jobId = id;
    result = null;
    error = '';
    if (apiKey) watchingJobId = id;
    document.getElementById('job-id')?.focus();
  }

  async function run(action: 'submit' | 'status' | 'delete') {
    if (!apiKey || busy || (action !== 'submit' && !jobId.trim())) return;
    if (action === 'submit' && textLengthError) {
      error = textLengthError;
      return;
    }
    if (action === 'delete' && !window.confirm(`Delete audio for job ${jobId.trim()}? This cannot be undone.`)) return;
    watchingJobId = '';
    if (action === 'submit') resetTracking();
    busy = action;
    result = null;
    error = '';
    try {
      if (action === 'submit') {
        result = await requestJson('/tts', apiKey, {
          method: 'POST', body: JSON.stringify({ text, voice, pitch, speed, volume, ...(style.trim() ? { style: style.trim() } : {}) }), signal: controller.signal
        });
        if (result.ok && result.body && typeof result.body === 'object' && 'job_id' in result.body && typeof result.body.job_id === 'string') {
          jobId = result.body.job_id;
          watchingJobId = jobId;
        }
      } else {
        const path = `/tts/${action === 'status' ? 'status' : 'audio'}/${encodeURIComponent(jobId.trim())}`;
        result = await requestJson(path, apiKey, { method: action === 'delete' ? 'DELETE' : 'GET', signal: controller.signal });
        if (action === 'status') receiveStatus(result);
        if (action === 'delete' && result.ok) {
          resetTracking();
          audioRevision++;
        }
      }
    } catch {
      if (!controller.signal.aborted) error = 'Could not reach the API. Check your connection and try again.';
    } finally { busy = ''; }
  }
</script>

<svelte:head>
  <title>Speechma · API playground</title>
  <meta name="robots" content="noindex, nofollow" />
  <meta name="description" content="Test Speechma speech generation, jobs, audio, and service health." />
</svelte:head>

<main class="test-page">
  <div class="test-shell">
    <header class="page-heading">
      <span class="eyebrow">SPEECHMA / DEVELOPER TOOLS</span>
      <h1>API playground</h1>
      <p>Send a speech request, inspect a job, and listen to the result.</p>
    </header>

    <section class="panel connection" aria-labelledby="connection-title">
      <div><h2 id="connection-title">Connect to this API</h2><p class="muted">Requests use the same server as this page. Your key stays in this tab’s memory.</p></div>
      <div class="field"><label for="api-key">API key</label><input id="api-key" type="password" bind:value={apiKey} oninput={resetTracking} disabled={!!busy} autocomplete="off" spellcheck="false" placeholder="Enter your API_KEY" /></div>
    </section>

    <p class="notice">Generate speech and the page will check its progress automatically. When it’s ready, the audio loads for playback and download.</p>

    <div class="workspace-grid">
      <section class="panel" aria-labelledby="generate-title">
        <div class="section-heading"><div><span class="eyebrow">01 / GENERATE</span><h2 id="generate-title">Create speech</h2></div><code>POST /tts</code></div>
        <form onsubmit={(event) => { event.preventDefault(); void run('submit'); }}>
          <fieldset disabled={!!busy}>
            <div class="field">
              <label for="speech-text">Text</label>
              <textarea id="speech-text" bind:value={text} rows="7" required aria-invalid={!!textLengthError} aria-describedby="text-length-hint text-length-error"></textarea>
              <span id="text-length-hint" class="muted">{textLength.toLocaleString()} / {data.maxTextLength.toLocaleString()} characters · minimum {data.minTextLength.toLocaleString()} after trimming</span>
              <span class="muted">Add a pause with [break 1s] or [break 500ms].</span>
              <span id="text-length-error" class="error" aria-live="polite">{textLengthError}</span>
            </div>
            <div class="field"><label for="voice">Voice identifier</label><input id="voice" bind:value={voice} spellcheck="false" /></div>
            <div class="field">
              <label for="style">Speaking style (optional)</label>
              <input id="style" bind:value={style} spellcheck="false" placeholder="general" aria-describedby="style-hint" />
              <span id="style-hint" class="muted">Applies to the whole text. Use a style supported by the selected voice; leave blank for general.</span>
            </div>
            <div class="parameter-grid">
              <div class="field"><label for="pitch">Pitch</label><input id="pitch" bind:value={pitch} /><span class="muted">Hz adjustment · default 0</span></div>
              <div class="field"><label for="speed">Speed</label><input id="speed" bind:value={speed} /><span class="muted">Multiplier · default 1</span></div>
              <div class="field"><label for="volume">Volume</label><input id="volume" bind:value={volume} /><span class="muted">Baseline · default 100</span></div>
            </div>
            <button class="primary" type="submit" disabled={!apiKey || !!textLengthError || !!busy}>{busy === 'submit' ? 'Submitting…' : 'Generate speech'}</button>
          </fieldset>
        </form>
      </section>

      <section class="panel" aria-labelledby="inspect-title">
        <span class="eyebrow">02 / INSPECT</span><h2 id="inspect-title">Job & audio</h2>
        <p class="muted">A successful submission fills the job ID below. You can also paste an existing ID.</p>
        <div class="field"><label for="job-id">Job ID</label><input id="job-id" bind:value={jobId} oninput={resetTracking} disabled={!!busy} spellcheck="false" placeholder="Paste a job ID" /></div>
        <div class="actions">
          <button type="button" onclick={() => run('status')} disabled={!apiKey || !jobId.trim() || !!busy}>{busy === 'status' ? 'Checking…' : 'Check status'}</button>
          <button class="danger" type="button" onclick={() => run('delete')} disabled={!apiKey || !jobId.trim() || !!busy}>{busy === 'delete' ? 'Deleting…' : 'Delete audio'}</button>
        </div>
        {#if watchingJobId && watchingJobId === jobId.trim()}
          {#key JSON.stringify([apiKey, watchingJobId])}
            <JobStatusPoller {apiKey} jobId={watchingJobId} onresult={receiveStatus} onerror={pollingFailed} />
          {/key}
        {/if}
        {#key JSON.stringify([apiKey, jobId, audioRevision, audioReadyFor])}
          <JobAudio {apiKey} {jobId} autoLoad={!!audioReadyFor && audioReadyFor === jobId.trim()} />
        {/key}
      </section>
    </div>

    <section class="panel" aria-labelledby="response-title">
      <h2 id="response-title">Last request</h2>
      {#if error}<p class="error" role="alert">{error}</p>{/if}
      <ApiResponse {result} />
      {#if !result && !error}<p class="empty" aria-live="polite">{busy ? 'Waiting for the API…' : 'Submit a request or check a job to see the response here.'}</p>{/if}
    </section>

    {#key apiKey}
      <HealthCheck {apiKey} />
      <RecentJobs {apiKey} onselect={selectJob} />
    {/key}
  </div>
</main>
