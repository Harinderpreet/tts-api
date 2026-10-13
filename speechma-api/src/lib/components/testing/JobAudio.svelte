<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { readResponse, type ApiResult } from '$lib/client/test-api';
  import ApiResponse from './ApiResponse.svelte';
  let { apiKey, jobId, autoLoad = false }: { apiKey: string; jobId: string; autoLoad?: boolean } = $props();
  let audioUrl = $state('');
  let result = $state<ApiResult | null>(null);
  let busy = $state(false);
  let error = $state('');
  const controller = new AbortController();
  onMount(() => {
    if (autoLoad) void loadAudio();
  });
  onDestroy(() => {
    controller.abort();
    if (audioUrl) URL.revokeObjectURL(audioUrl);
  });

  async function loadAudio() {
    if (busy || !apiKey || !jobId.trim()) return;
    busy = true;
    error = '';
    result = null;
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = '';
    const path = `/tts/audio/${encodeURIComponent(jobId.trim())}`;
    const start = performance.now();
    try {
      const response = await fetch(path, {
        headers: { 'api-key': apiKey }, cache: 'no-store', signal: controller.signal
      });
      let body: unknown;
      if (response.ok) {
        const blob = await response.blob();
        if (controller.signal.aborted) return;
        audioUrl = URL.createObjectURL(blob);
        body = { content_type: blob.type, bytes: blob.size };
      } else body = await readResponse(response);
      result = { method: 'GET', path, status: response.status, ok: response.ok,
        elapsedMs: Math.round(performance.now() - start), body };
    } catch {
      if (!controller.signal.aborted) error = 'Could not load audio. Check your connection and try again.';
    } finally { busy = false; }
  }
</script>

<div class="audio-section">
  <div class="actions">
    <button type="button" onclick={loadAudio} disabled={!apiKey || !jobId.trim() || busy}>{busy ? 'Loading audio…' : 'Load audio'}</button>
    {#if audioUrl}<a class="button" href={audioUrl} download={`${jobId.trim()}.mp3`}>Download MP3</a>{/if}
  </div>
  {#if audioUrl}<audio controls src={audioUrl} aria-label="Generated speech" onerror={() => error = 'The browser could not play this audio file. You can still download it.'}></audio>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <ApiResponse {result} />
</div>
