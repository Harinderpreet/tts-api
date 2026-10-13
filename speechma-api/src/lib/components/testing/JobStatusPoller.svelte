<script lang="ts">
  import { onMount } from 'svelte';
  import { requestJson, type ApiResult } from '$lib/client/test-api';

  let { apiKey, jobId, onresult, onerror }: {
    apiKey: string;
    jobId: string;
    onresult: (result: ApiResult) => void;
    onerror: () => void;
  } = $props();

  onMount(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function poll() {
      try {
        const result = await requestJson(`/tts/status/${encodeURIComponent(jobId.trim())}`, apiKey, {
          signal: controller.signal
        });
        if (controller.signal.aborted) return;
        onresult(result);
        if (!result.ok) { onerror(); return; }
        const status = result.body && typeof result.body === 'object' && 'status' in result.body
          ? result.body.status : undefined;
        if (status === 'queued' || status === 'processing') {
          // Schedule only after the previous request finishes, so requests never overlap.
          timer = setTimeout(() => { void poll(); }, 1500);
        } else if (status !== 'completed' && status !== 'failed') onerror();
      } catch {
        if (!controller.signal.aborted) onerror();
      }
    }

    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  });
</script>

<p class="muted" role="status">Checking job status automatically…</p>
