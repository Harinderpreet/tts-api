<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { PageProps } from './$types';
  import { requestBrowserSpeechEndpoint, requestBrowserSpeech } from '$lib/client/translator';
  import { createSpeechSsml } from '$lib/tts/ssml';
  import '$lib/styles/test-page.css';

  let { data }: PageProps = $props();
  let text = $state('Hello! [break 1s] This speech request comes directly from your browser.');
  let voice = $state('en-US-GuyNeural');
  let style = $state('cheerful');
  let pitch = $state('0');
  let speed = $state('1');
  let volume = $state('100');
  let busy = $state(false);
  let status = $state('Ready');
  let error = $state('');
  let networkFailure = $state(false);
  let sentSsml = $state('');
  let audioUrl = $state('');
  let result = $state('');
  let controller: AbortController | undefined;
  const textLength = $derived([...text].length);
  const invalidText = $derived(
    textLength > data.maxTextLength || [...text.trim()].length < data.minTextLength || !/[\p{L}\p{N}]/u.test(text)
  );

  onDestroy(() => {
    controller?.abort();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  });

  async function generate(tokenOnly = false) {
    if (busy || (!tokenOnly && (invalidText || !voice.trim()))) return;
    const current = new AbortController();
    controller = current;
    busy = true;
    error = '';
    result = '';
    networkFailure = false;
    sentSsml = '';
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = '';
    const started = performance.now();
    let stage = 'Preparing SSML';
    status = stage;
    try {
      if (!tokenOnly) sentSsml = createSpeechSsml({ text: text.trim(), voice: voice.trim(), style, pitch, speed, volume });
      stage = 'Getting Translator token';
      status = stage;
      const endpoint = await requestBrowserSpeechEndpoint(current.signal, { forceRefresh: tokenOnly });
      if (tokenOnly) {
        status = `Token received · ${endpoint.region}`;
        result = 'Token request succeeded. No speech request was sent.';
        return;
      }
      stage = 'Requesting speech';
      status = `Token ready · ${endpoint.region}. Requesting speech…`;
      const audio = await requestBrowserSpeech(endpoint, sentSsml, current.signal);
      current.signal.throwIfAborted();
      audioUrl = URL.createObjectURL(audio);
      result = `${endpoint.region} · ${(audio.size / 1024).toFixed(1)} KB · ${((performance.now() - started) / 1000).toFixed(2)} seconds`;
      status = 'Audio ready';
    } catch (cause) {
      if (current.signal.aborted) {
        status = 'Cancelled';
      } else {
        error = `${stage}: ${cause instanceof Error ? cause.message : String(cause)}`;
        networkFailure = cause instanceof TypeError;
        status = 'Audio generation failed';
        console.error(`[Speechma browser test] ${stage}`, cause);
      }
    } finally {
      busy = false;
      if (controller === current) controller = undefined;
    }
  }
</script>

<svelte:head>
  <title>Speechma · Direct browser speech test</title>
  <meta name="robots" content="noindex, nofollow" />
</svelte:head>

<main class="test-page">
  <div class="test-shell">
    <header class="page-heading">
      <span class="eyebrow">SPEECHMA / BROWSER EXPERIMENT</span>
      <h1>Direct browser speech</h1>
      <p>Send text to Microsoft from this browser, then play or download the audio.</p>
    </header>
    <p class="notice">Use HTTPS or localhost. No Speechma API key is needed. Generation contacts Microsoft directly and requires its endpoints to allow browser requests.</p>
    <div class="workspace-grid">
      <section class="panel" aria-labelledby="generate-title">
        <h2 id="generate-title">Create speech</h2>
        <form onsubmit={(event) => { event.preventDefault(); void generate(); }}>
          <fieldset disabled={busy}>
            <div class="field">
              <label for="browser-text">Text</label>
              <textarea id="browser-text" bind:value={text} rows="7" required aria-invalid={invalidText} aria-describedby="browser-text-hint"></textarea>
              <span id="browser-text-hint" class="muted">{textLength.toLocaleString()} / {data.maxTextLength.toLocaleString()} characters · minimum {data.minTextLength}. Add pauses with [break 1s] or [break 500ms].</span>
            </div>
            <div class="field"><label for="browser-voice">Voice identifier</label><input id="browser-voice" bind:value={voice} required spellcheck="false" /></div>
            <div class="field">
              <label for="browser-style">Speaking style</label><input id="browser-style" bind:value={style} placeholder="general" spellcheck="false" />
              <span class="muted">Use a style supported by the selected voice. Leave blank for general.</span>
            </div>
            <div class="parameter-grid">
              <div class="field"><label for="browser-pitch">Pitch</label><input id="browser-pitch" bind:value={pitch} required /><span class="muted">Hz adjustment · default 0</span></div>
              <div class="field"><label for="browser-speed">Speed</label><input id="browser-speed" bind:value={speed} required /><span class="muted">Multiplier · default 1</span></div>
              <div class="field"><label for="browser-volume">Volume</label><input id="browser-volume" bind:value={volume} required /><span class="muted">Baseline · default 100</span></div>
            </div>
            <div class="actions">
              <button class="primary" type="submit" disabled={busy || invalidText || !voice.trim()}>{busy ? 'Request in progress…' : 'Generate in browser'}</button>
              <button type="button" disabled={busy} onclick={() => void generate(true)}>Test token only</button>
            </div>
          </fieldset>
        </form>
      </section>
      <section class="panel" aria-labelledby="result-title">
        <h2 id="result-title">Request progress & audio</h2>
        <p role="status">{status}</p>
        {#if busy}<button type="button" onclick={() => controller?.abort()}>Cancel request</button>{/if}
        {#if error}
          <div role="alert">
            <pre class="error">{error}</pre>
            {#if networkFailure}<p class="muted">The browser could not complete the request. This may be CORS, a connection problem, or a browser restriction. Open Developer Tools → Console and Network for the browser’s exact reason; JavaScript cannot read a blocked response.</p>{/if}
          </div>
        {/if}
        {#if result}<p class="muted">{result}</p>{/if}
        {#if audioUrl}
          <audio controls src={audioUrl}>Your browser does not support audio playback.</audio>
          <p><a class="button" href={audioUrl} download="speechma-browser-test.mp3">Download MP3</a></p>
        {/if}
        {#if sentSsml}<details><summary>SSML for this attempt</summary><pre>{sentSsml}</pre></details>{/if}
        <p class="muted">Generation reuses the token in this tab until three minutes before it expires. Reloading clears the cache. “Test token only” requests a fresh token. Tokens are not displayed or saved to browser storage. Requests use your browser’s own User-Agent.</p>
      </section>
    </div>
  </div>
</main>
