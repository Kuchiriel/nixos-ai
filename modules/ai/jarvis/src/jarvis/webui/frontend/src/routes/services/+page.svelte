<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchServices, executeCommand } from '$lib/api/client';

  let services: any[] = $state([]);
  let loading = $state(true);

  onMount(async () => {
    services = await fetchServices();
    loading = false;
  });

  async function toggle(name: string, action: 'start' | 'stop' | 'restart') {
    const cmd = `service.${action}`;
    await executeCommand(cmd, { name });
    services = await fetchServices(); // refresh
  }
</script>

<svelte:head><title>Jarvis — Services</title></svelte:head>

<h1>Services</h1>
<p class="subtitle">{services.filter(s => s.active).length} active / {services.length} total</p>

{#if loading}
  <p style="color:#666">Loading...</p>
{:else}
  <div class="table">
    <div class="row header">
      <span class="col-status">Status</span>
      <span class="col-name">Service</span>
      <span class="col-desc">Description</span>
      <span class="col-scope">Scope</span>
      <span class="col-actions">Actions</span>
    </div>
    {#each services as svc}
      <div class="row" class:active={svc.active}>
        <span class="col-status">
          <span class="dot" style="background:{svc.active ? '#22c55e' : svc.enabled ? '#eab308' : '#555'}"></span>
        </span>
        <span class="col-name">{svc.name}</span>
        <span class="col-desc">{svc.description || '—'}</span>
        <span class="col-scope">{svc.scope}</span>
        <span class="col-actions">
          {#if svc.active}
            <button class="btn-stop" onclick={() => toggle(svc.name, 'stop')}>Stop</button>
            <button class="btn-restart" onclick={() => toggle(svc.name, 'restart')}>Restart</button>
          {:else}
            <button class="btn-start" onclick={() => toggle(svc.name, 'start')}>Start</button>
          {/if}
        </span>
      </div>
    {/each}
  </div>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 0.25rem; }
  .subtitle { font-size: 0.75rem; color: #666; margin-bottom: 1rem; }
  .table { display: flex; flex-direction: column; gap: 1px; }
  .row { display: grid; grid-template-columns: 30px 200px 1fr 60px 140px; align-items: center; padding: 0.5rem; background: #111; font-size: 0.8rem; }
  .row.header { background: #1a1a1a; color: #666; font-size: 0.7rem; text-transform: uppercase; }
  .row.active { border-left: 2px solid #22c55e; }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .col-name { font-weight: bold; }
  .col-desc { color: #888; }
  .col-scope { color: #555; }
  .col-actions { display: flex; gap: 0.25rem; }
  button { padding: 0.2rem 0.5rem; border: none; border-radius: 3px; font-size: 0.7rem; font-family: inherit; }
  .btn-start { background: #1a3a1a; color: #22c55e; }
  .btn-stop { background: #3a1a1a; color: #ef4444; }
  .btn-restart { background: #1a1a3a; color: #60a5fa; }
  button:hover { filter: brightness(1.2); }
</style>
