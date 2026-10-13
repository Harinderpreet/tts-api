<script lang="ts">
  import type { ApiResult } from '$lib/client/test-api';
  let { result }: { result: ApiResult | null } = $props();
</script>

{#if result}
  <div class="api-response">
    <div class="response-heading" aria-live="polite">
      <span class="badge" class:error-badge={!result.ok}>HTTP {result.status}</span>
      <code>{result.method} {result.path}</code>
      <span class="muted">{result.elapsedMs} ms</span>
    </div>
    <pre aria-label="API response">{typeof result.body === 'string' ? result.body : JSON.stringify(result.body, null, 2)}</pre>
  </div>
{/if}
