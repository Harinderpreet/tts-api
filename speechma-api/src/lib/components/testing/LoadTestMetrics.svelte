<script lang="ts">
  import { onMount } from 'svelte';
  import { requestJson } from '$lib/client/test-api';
  import type { ServerMetrics } from '$lib/types/load-test';

  let { apiKey, onmetrics, onerror }: {
    apiKey: string;
    onmetrics: (metrics: ServerMetrics) => void;
    onerror: () => void;
  } = $props();
  let metrics = $state<ServerMetrics | null>(null);
  let error = $state('');
  let busy = $state(false);
  let history = $state<ServerMetrics[]>([]);
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout>;
  const mib = (value: number) => `${(value / 1048576).toFixed(0)} MiB`;
  const percent = (value: number | null) => value === null ? 'Sampling…' : `${value.toFixed(1)}%`;
  const points = $derived(history.map((sample, index) =>
    `${index / Math.max(1, history.length - 1) * 600},${100 - (sample.host.cpuPercent ?? 0)}`).join(' '));

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
      history = [...history.slice(-59), metrics];
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
    <div><h2 id="server-metrics-title">Live server resources</h2><p class="muted">Updates every five seconds. CPU needs two samples. Counts belong to the responding Node process.</p></div>
    <button type="button" onclick={check} disabled={busy}>{busy ? 'Refreshing…' : 'Refresh now'}</button>
  </div>
  {#if error}<p class="error" role="alert">{error} Previous readings below may be stale.</p>{/if}
  {#if metrics}
    <div class="resource-grid">
      <article><span>Host CPU</span><strong>{percent(metrics.host.cpuPercent)}</strong><small>Across all OS-visible CPU cores</small></article>
      <article><span>Host RAM</span><strong>{mib(metrics.host.memoryBytes)}</strong><small>{mib(metrics.host.availableBytes)} available / {mib(metrics.host.totalBytes)} total</small></article>
      <article><span>Speech process CPU</span><strong>{percent(metrics.process.cpuPercent)}</strong><small>100% equals one CPU core</small></article>
      <article><span>Speech process RAM</span><strong>{mib(metrics.process.memoryBytes)}</strong><small>Resident memory · process {metrics.processId}</small></article>
      {#if metrics.group}
        <article><span>Runtime group CPU</span><strong>{percent(metrics.group.cpuPercent)}</strong><small>{metrics.group.cpuLimitCores === null ? 'No direct CPU quota' : `${metrics.group.cpuLimitCores} CPU cores quota`} · 100% = one core</small></article>
        <article><span>Runtime group RAM</span><strong>{mib(metrics.group.memoryBytes)}</strong><small>{metrics.group.memoryLimitBytes === null ? 'No direct memory limit' : `${mib(metrics.group.memoryLimitBytes)} limit`}</small></article>
      {/if}
    </div>
    <p class="muted">Runtime group readings use Linux cgroup v2; in Docker this is normally the container’s resource group. Ancestor limits may be tighter. {metrics.group ? 'Memory includes cache.' : 'Group metrics are unavailable on this runtime.'}</p>
    <div class="server-counts">
      <span>Server queued <b>{metrics.queued}</b></span>
      <span>Processing <b>{metrics.processing}</b></span>
      <span>Worker slots <b>{metrics.workerSlots} / {metrics.maxConcurrent}</b></span>
      <span class={{ error: !metrics.ready }}>{metrics.ready ? 'Provider configured' : 'Service unavailable'}</span>
    </div>
    {#if history.length > 1}
      <svg class="cpu-chart" viewBox="0 0 600 100" role="img" aria-label="Recent host CPU usage, zero to one hundred percent">
        <path d="M0 1H600 M0 50H600 M0 99H600" stroke="#dfe5ee" fill="none" />
        <polyline {points} fill="none" stroke="#285acb" stroke-width="2" vector-effect="non-scaling-stroke" />
      </svg>
      <p class="muted">Host CPU · last {history.length} samples · 0–100%</p>
    {/if}
  {:else if !error}<p class="empty">Reading server resources…</p>{/if}
</section>

<style>
  .resource-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  article { border: 1px solid #e0e7f0; border-radius: 10px; padding: 16px; background: #f8faff; display: flex; flex-direction: column; gap: 5px; }
  article span, small { color: #5b6b80; font-size: .78rem; }
  strong { font-size: 1.65rem; letter-spacing: -.04em; }
  .server-counts { display: flex; flex-wrap: wrap; gap: 12px 24px; padding: 16px 0; font-size: .85rem; }
  .cpu-chart { width: 100%; height: 100px; background: #fcfdff; border-radius: 8px; }
  @media (max-width: 650px) { .resource-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
