<script lang="ts">
  import { onMount } from 'svelte';
  import { requestJson } from '$lib/client/test-api';
  import type { ServerMetrics } from '$lib/types/load-test';
  import ResourceUsageBar from './ResourceUsageBar.svelte';

  let { apiKey, onmetrics, onerror }: {
    apiKey: string;
    onmetrics: (metrics: ServerMetrics) => void;
    onerror: () => void;
  } = $props();
  let metrics = $state<ServerMetrics | null>(null);
  let error = $state('');
  let busy = $state(false);
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  const mib = (value: number) => `${(value / 1048576).toFixed(0)} MiB`;
  const percent = (value: number | null) => value === null ? 'Sampling…' : `${value.toFixed(1)}%`;

  async function check() {
    if (busy || controller.signal.aborted) return;
    clearTimeout(timer);
    busy = true;
    try {
      const response = await requestJson('/api/load-test/metrics', apiKey, {
        signal: AbortSignal.any([controller.signal, AbortSignal.timeout(15000)])
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      metrics = response.body as ServerMetrics;
      error = '';
      onmetrics(metrics);
    } catch {
      if (!controller.signal.aborted) {
        error = 'Could not read server metrics. Check the API key, connection, and deployment. New submissions are paused.';
        onerror();
      }
    } finally {
      busy = false;
      if (!controller.signal.aborted) timer = setTimeout(check, 5000);
    }
  }

  onMount(() => {
    void check();
    return () => { controller.abort(); clearTimeout(timer); };
  });
</script>

<section class="panel" aria-labelledby="server-metrics-title">
  <div class="section-heading">
    <div><h2 id="server-metrics-title">Overall server usage</h2><p class="muted">Updates every five seconds.</p></div>
    <button type="button" onclick={check} disabled={busy}>{busy ? 'Refreshing…' : 'Refresh now'}</button>
  </div>
  {#if error}<p class="error" role="alert">{error} Previous readings below may be stale.</p>{/if}
  {#if metrics}
    <div class="resource-grid">
      <ResourceUsageBar label="Overall CPU" value={metrics.host.cpuPercent} max={100} currentLabel={percent(metrics.host.cpuPercent)} maxLabel="100%" detail="Across all server CPU cores" />
      <ResourceUsageBar label="Overall RAM" value={metrics.host.memoryBytes} max={metrics.host.totalBytes} currentLabel={mib(metrics.host.memoryBytes)} maxLabel={mib(metrics.host.totalBytes)} detail={`${mib(metrics.host.availableBytes)} available`} />
    </div>
    <p class="muted usage-guide">Usage guide: green below 70% · amber 70% to under 90% · red 90% and above.</p>
  {:else if !error}<p class="empty">Reading server resources…</p>{/if}
</section>

<style>
  .resource-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
  .usage-guide { margin-bottom: 0; }
  @media (max-width: 450px) { .resource-grid { grid-template-columns: 1fr; } }
</style>
