<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchLLMInfo, fetchConfig, fetchServices } from '$lib/api/client';
  let llm: any = $state(null);
  let config: any = $state(null);
  let services: any[] = $state([]);

  onMount(async () => {
    llm = await fetchLLMInfo();
    config = await fetchConfig();
    services = await fetchServices();
  });
</script>

<svelte-head><title>Jarvis — Config</title></svelte-head>
<h1>Config</h1>

{#if llm}
  <section>
    <h2>LLM</h2>
    <div class="info-grid">
      <div class="row"><span class="label">Model</span><span class="value">{llm.model}</span></div>
      <div class="row"><span class="label">Backend</span><span class="value">{llm.backend}</span></div>
      <div class="row"><span class="label">Status</span><span class="value" style="color:{llm.healthy ? '#22c55e' : '#ef4444'}">{llm.status}</span></div>
      <div class="row"><span class="label">Base URL</span><span class="value">{llm.base_url}</span></div>
    </div>
  </section>
{/if}

{#if config}
  <section>
    <h2>Services</h2>
    <div class="info-grid">
      {#each Object.entries(config.services) as [name, cfg]}
      <div class="row"><span class="label">{name}</span><span class="value">{cfg.url || '—'}</span></div>
      {/each}
    </div>
  </section>
{/if}

{#if services.length > 0}
  <section>
    <h2>System Services</h2>
    <table>
      <thead><tr><th>Service</th><th>Active</th><th>Enabled</th></tr></thead>
      <tbody>
        {#each services as s}
        <tr>
          <td>{s.name}</td>
          <td style="color:{s.active ? '#22c55e' : '#ef4444'}">{s.active ? 'yes' : 'no'}</td>
          <td style="color:{s.enabled ? '#22c55e' : '#ef4444'}">{s.enabled ? 'yes' : 'no'}</td>
        </tr>
        {/each}
      </tbody>
    </table>
  </section>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 1rem; }
  h2 { font-size: 1rem; color: #888; margin: 1rem 0 0.5rem; }
  .info-grid { display: flex; flex-direction: column; gap: 2px; max-width: 600px; }
  .row { display: grid; grid-template-columns: 120px 1fr; padding: 0.4rem 0.6rem; background: #111; border-radius: 3px; font-size: 0.8rem; }
  .label { color: #666; text-transform: uppercase; font-size: 0.7rem; }
  table { width: 100%; max-width: 600px; border-collapse: collapse; font-size: 0.8rem; }
  th, td { padding: 0.4rem 0.6rem; text-align: left; border-bottom: 1px solid #222; }
  th { color: #666; }
</style>
