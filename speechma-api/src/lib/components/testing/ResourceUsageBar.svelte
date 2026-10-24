<script lang="ts">
  let { label, value, max, currentLabel, maxLabel, detail = '' }: {
    label: string;
    value: number | null;
    max: number;
    currentLabel: string;
    maxLabel: string;
    detail?: string;
  } = $props();

  const usage = $derived(value === null || max <= 0 ? null : Math.min(100, Math.max(0, value / max * 100)));
  const level = $derived(usage === null ? 'pending' : usage >= 90 ? 'high' : usage >= 70 ? 'elevated' : 'normal');
  const status = $derived(usage === null ? 'Waiting for sample' : level === 'high' ? 'High usage' : level === 'elevated' ? 'Elevated usage' : 'Room available');
</script>

<article class={['resource-card', level]}>
  <div class="heading"><h3>{label}</h3><span class="status">{status}</span></div>
  <div class="values">
    <div><strong>{currentLabel}</strong><small>Current usage</small></div>
    <div class="maximum"><strong>{maxLabel}</strong><small>Maximum</small></div>
  </div>
  <div
    class="usage-bar"
    role="progressbar"
    aria-label={label}
    aria-valuemin={0}
    aria-valuemax={100}
    aria-valuenow={usage ?? undefined}
    aria-valuetext={usage === null ? 'Waiting for a server sample' : `${currentLabel} of ${maxLabel}, ${usage.toFixed(1)} percent used`}
  >
    <span class="fill" style:width={`${usage ?? 0}%`}></span>
    <span class="bar-value">{usage === null ? 'Sampling…' : `${usage.toFixed(1)}%`}</span>
  </div>
  {#if detail}<p>{detail}</p>{/if}
</article>

<style>
  .resource-card { border: 1px solid #e0e7f0; border-radius: 10px; padding: 18px; background: #f8faff; }
  .heading, .values { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
  h3 { margin: 0; color: #40536d; font-size: .88rem; font-weight: 650; }
  .status { border-radius: 20px; padding: 4px 9px; font-size: .7rem; background: #e8edf4; color: #526278; }
  .normal .status { background: #e5f4eb; color: #216144; }
  .elevated .status { background: #fff0c9; color: #785300; }
  .high .status { background: #fce5e5; color: #a32532; }
  .values { align-items: flex-start; margin: 18px 0 12px; }
  .values div { display: flex; flex-direction: column; gap: 3px; }
  .maximum { text-align: right; }
  strong { color: #182438; font-size: clamp(1.1rem, 2.5vw, 1.65rem); letter-spacing: -.035em; }
  small, p { color: #5b6b80; font-size: .75rem; }
  p { margin: 10px 0 0; }
  .usage-bar { position: relative; height: 30px; border: 1px solid #d7e0eb; border-radius: 7px; overflow: hidden; background: #e9eef5; }
  .fill { position: absolute; inset: 0 auto 0 0; background: #8ad2a4; transition: width .3s ease; }
  .elevated .fill { background: #f1c667; }
  .high .fill { background: #f49b9b; }
  .bar-value { position: absolute; inset: 0; display: grid; place-items: center; color: #182438; font-size: .8rem; font-weight: 700; }
  @media (prefers-reduced-motion: reduce) { .fill { transition: none; } }
  @media (max-width: 400px) { .heading { align-items: flex-start; flex-wrap: wrap; } }
</style>
