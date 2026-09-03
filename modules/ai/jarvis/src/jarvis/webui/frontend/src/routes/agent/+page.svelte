<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchAgentInfo } from '$lib/api/client';
  let agent: any = $state(null);
  onMount(async () => { agent = await fetchAgentInfo(); });
</script>

<svelte:head><title>Jarvis — Agent</title></svelte:head>
<h1>Agent</h1>
{#if agent}
  <div class="info-grid">
    <div class="row"><span class="label">Active Task</span><span class="value">{agent.active_task || '—'}</span></div>
    <div class="row"><span class="label">Persona</span><span class="value">{agent.active_persona || '—'}</span></div>
    <div class="row"><span class="label">Project</span><span class="value">{agent.active_project || '—'}</span></div>
  </div>
{:else}
  <p style="color:#666">Loading...</p>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 1rem; }
  .info-grid { display: flex; flex-direction: column; gap: 2px; max-width: 500px; }
  .row { display: grid; grid-template-columns: 120px 1fr; padding: 0.5rem; background: #111; border-radius: 3px; font-size: 0.8rem; }
  .label { color: #666; text-transform: uppercase; font-size: 0.7rem; }
</style>
