<script lang="ts">
  import { onDestroy } from 'svelte';
  import { requestJson, type ApiResult } from '$lib/client/test-api';
  import ApiResponse from './ApiResponse.svelte';
  let { apiKey }: { apiKey: string } = $props();
  let result = $state<ApiResult | null>(null);
  let busy = $state(false);
  let error = $state('');
  const controller = new AbortController();
  onDestroy(() => controller.abort());

  async function check() {
    busy = true;
    error = '';
    result = null;
    try {
      result = await requestJson('/health', apiKey, { signal: controller.signal });
    } catch {
      if (!controller.signal.aborted) error = 'Could not reach the API. Check your connection and try again.';
    } finally { busy = false; }
  }
</script>

<section class="panel" aria-labelledby="health-title">
  <div class="section-heading">
    <div><h2 id="health-title">Service health</h2><p class="muted">Queue, storage, and provider readiness.</p></div>
    <button type="button" onclick={check} disabled={!apiKey || busy}>{busy ? 'Checking…' : 'Check health'}</button>
  </div>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  <ApiResponse {result} />
  {#if !result && !error}<p class="empty">Run a check to see the current service state.</p>{/if}
</section>
