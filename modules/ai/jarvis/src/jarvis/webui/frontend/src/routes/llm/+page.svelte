<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchLLMInfo } from '$lib/api/client';

  let llm: any = $state(null);
  let loading = $state(true);

  onMount(async () => {
    llm = await fetchLLMInfo();
    loading = false;
  });
</script>

<svelte:head><title>Jarvis — LLM</title></svelte:head>

<h1>LLM Backend</h1>

{#if loading}
  <p style="color:#666">Loading...</p>
{:else if llm}
  <div class="info-grid">
    <div class="info-row">
      <span class="label">Status</span>
      <span class="value" style="color:{llm.healthy ? '#22c55e' : '#ef4444'}">{llm.status}</span>
    </div>
    <div class="info-row">
      <span class="label">Backend</span>
      <span class="value">{llm.backend}</span>
    </div>
    <div class="info-row">
      <span class="label">Model</span>
      <span class="value">{llm.model}</span>
    </div>
    <div class="info-row">
      <span class="label">Endpoint</span>
      <span class="value mono">{llm.base_url}</span>
    </div>
    <div class="info-row">
      <span class="label">Timeout</span>
      <span class="value">{llm.timeout}s</span>
    </div>
    <div class="info-row">
      <span class="label">Tool Calling</span>
      <span class="value" style="color:{llm.tool_calling ? '#22c55e' : '#ef4444'}">{llm.tool_calling ? 'enabled' : 'disabled'}</span>
    </div>
    <div class="info-row">
      <span class="label">Thinking</span>
      <span class="value" style="color:{llm.disable_thinking ? '#eab308' : '#22c55e'}">{llm.disable_thinking ? 'disabled' : 'enabled'}</span>
    </div>
  </div>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 1rem; }
  .info-grid { display: flex; flex-direction: column; gap: 2px; max-width: 600px; }
  .info-row { display: grid; grid-template-columns: 120px 1fr; padding: 0.5rem; background: #111; border-radius: 3px; font-size: 0.8rem; }
  .label { color: #666; text-transform: uppercase; font-size: 0.7rem; }
  .value { color: #e0e0e0; }
  .mono { font-family: monospace; font-size: 0.75rem; color: #888; }
</style>
