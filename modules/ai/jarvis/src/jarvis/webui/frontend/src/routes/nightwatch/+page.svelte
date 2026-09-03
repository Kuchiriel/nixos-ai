<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchNightwatchInfo } from '$lib/api/client';
  let nw: any = $state(null);
  onMount(async () => { nw = await fetchNightwatchInfo(); });
</script>

<svelte:head><title>Jarvis — Nightwatch</title></svelte:head>
<h1>Nightwatch</h1>
{#if nw}
  <div class="info-grid">
    <div class="row"><span class="label">Active</span><span class="value" style="color:{nw.active ? '#22c55e' : '#555'}">{nw.active ? 'yes' : 'no'}</span></div>
    <div class="row"><span class="label">Last Run</span><span class="value">{nw.last_run ? JSON.stringify(nw.last_run).slice(0, 200) : '—'}</span></div>
  </div>
{:else}
  <p style="color:#666">Loading...</p>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 1rem; }
  .info-grid { display: flex; flex-direction: column; gap: 2px; max-width: 600px; }
  .row { display: grid; grid-template-columns: 100px 1fr; padding: 0.5rem; background: #111; border-radius: 3px; font-size: 0.8rem; }
  .label { color: #666; text-transform: uppercase; font-size: 0.7rem; }
  .value { word-break: break-all; }
</style>
