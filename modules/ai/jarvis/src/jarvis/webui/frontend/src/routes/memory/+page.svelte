<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchMemoryInfo } from '$lib/api/client';
  let mem: any = $state(null);
  onMount(async () => { mem = await fetchMemoryInfo(); });
</script>

<svelte:head><title>Jarvis — Memory</title></svelte:head>
<h1>Memory / RAG</h1>
{#if mem}
  <div class="info-grid">
    <div class="row"><span class="label">Qdrant</span><span class="value" style="color:{mem.healthy ? '#22c55e' : '#ef4444'}">{mem.healthy ? 'online' : 'offline'}</span></div>
    <div class="row"><span class="label">URL</span><span class="value mono">{mem.qdrant_url}</span></div>
    <div class="row"><span class="label">Code Collection</span><span class="value">{mem.collections?.code}</span></div>
    <div class="row"><span class="label">Memory Collection</span><span class="value">{mem.collections?.memories}</span></div>
    <div class="row"><span class="label">Books Collection</span><span class="value">{mem.collections?.books}</span></div>
    <div class="row"><span class="label">Existing</span><span class="value">{mem.existing_collections?.join(', ') || 'none'}</span></div>
  </div>
{:else}
  <p style="color:#666">Loading...</p>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 1rem; }
  .info-grid { display: flex; flex-direction: column; gap: 2px; max-width: 600px; }
  .row { display: grid; grid-template-columns: 140px 1fr; padding: 0.5rem; background: #111; border-radius: 3px; font-size: 0.8rem; }
  .label { color: #666; text-transform: uppercase; font-size: 0.7rem; }
  .mono { font-family: monospace; font-size: 0.75rem; color: #888; }
</style>
