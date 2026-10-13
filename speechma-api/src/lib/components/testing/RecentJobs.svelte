<script lang="ts">
  import { onDestroy } from 'svelte';
  import type { ListedJob } from '$lib/types/tts';
  import { requestJson, type ApiResult } from '$lib/client/test-api';
  import ApiResponse from './ApiResponse.svelte';
  let { apiKey, onselect }: { apiKey: string; onselect: (id: string) => void } = $props();
  let result = $state<ApiResult | null>(null);
  let jobs = $state<ListedJob[]>([]);
  let busy = $state(false);
  let error = $state('');
  const controller = new AbortController();
  onDestroy(() => controller.abort());

  async function refresh() {
    busy = true;
    error = '';
    jobs = [];
    result = null;
    try {
      result = await requestJson('/tts/jobs', apiKey, { signal: controller.signal });
      if (result.ok && Array.isArray(result.body)) jobs = result.body as ListedJob[];
    } catch {
      if (!controller.signal.aborted) error = 'Could not load jobs. Check your connection and try again.';
    } finally { busy = false; }
  }
</script>

<section class="panel" aria-labelledby="jobs-title">
  <div class="section-heading">
    <div><h2 id="jobs-title">Recent jobs</h2><p class="muted">Up to 50 jobs. Select one to inspect its status and audio.</p></div>
    <button type="button" onclick={refresh} disabled={!apiKey || busy}>{busy ? 'Loading…' : 'Refresh jobs'}</button>
  </div>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if jobs.length}
    <ul class="job-list">
      {#each jobs as job (job.job_id)}
        <li>
          <div class="job-details">
            <code>{job.job_id}</code>
            <span class="muted">{job.status} · {job.created_at}</span>
            {#if job.audio_exists}<span class="muted">{job.file_size.toLocaleString()} bytes</span>
            {:else}<p>{job.text}</p>{/if}
          </div>
          <button type="button" onclick={() => onselect(job.job_id)} aria-label={`Inspect job ${job.job_id}`}>Inspect</button>
        </li>
      {/each}
    </ul>
  {:else if result?.ok}<p class="empty">No jobs found.</p>
  {:else if !result && !error}<p class="empty">Refresh to load jobs from this service.</p>{/if}
  {#if result}<details><summary>Raw jobs response</summary><ApiResponse {result} /></details>{/if}
</section>
