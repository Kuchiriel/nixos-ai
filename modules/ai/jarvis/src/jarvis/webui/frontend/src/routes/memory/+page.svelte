<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchMemoryInfo, fetchMemories, fetchVaultNotes } from '$lib/api/client';
  let mem: any = $state(null);
  let episodic: any = $state(null);
  let vault: any = $state(null);
  onMount(async () => {
    mem = await fetchMemoryInfo();
    try { episodic = await fetchMemories('', 10); } catch { episodic = null; }
    try { vault = await fetchVaultNotes(); } catch { vault = null; }
  });
</script>

<svelte:head><title>Jarvis — Memory</title></svelte:head>
<h1>Memory / RAG</h1>
{#if mem}
  <h2>RAG (Qdrant)</h2>
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

{#if episodic}
  <h2>Memória Episódica ({episodic.total ?? episodic.memories?.length ?? 0})</h2>
  <div class="list">
    {#each (episodic.memories || []).slice(0, 10) as m}
    <div class="card">
      <div class="card-head"><span class="kind">{m.kind}</span><span class="ts">{m.timestamp}</span></div>
      <div class="card-body">{m.content}</div>
      {#if m.task}<div class="card-task">task: {m.task}</div>{/if}
    </div>
    {/each}
  </div>
{/if}

{#if vault}
  <h2>Vault ({vault.total ?? vault.notes?.length ?? 0})</h2>
  <div class="info-grid">
    {#each (vault.notes || []) as n}
    <div class="row"><span class="label">{n.title}</span><span class="value preview">{n.preview?.slice(0, 120) || '—'}</span></div>
    {/each}
  </div>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 1rem; }
  .info-grid { display: flex; flex-direction: column; gap: 2px; max-width: 600px; }
  .row { display: grid; grid-template-columns: 140px 1fr; padding: 0.5rem; background: #111; border-radius: 3px; font-size: 0.8rem; }
  .label { color: #666; text-transform: uppercase; font-size: 0.7rem; }
  .mono { font-family: monospace; font-size: 0.75rem; color: #888; }
  h2 { font-size: 1rem; color: #888; margin: 1rem 0 0.5rem; }
  .list { display: flex; flex-direction: column; gap: 0.4rem; max-width: 700px; }
  .card { background: #111; border-radius: 4px; padding: 0.5rem 0.7rem; font-size: 0.8rem; }
  .card-head { display: flex; justify-content: space-between; margin-bottom: 0.25rem; }
  .kind { color: #00d4ff; text-transform: uppercase; font-size: 0.7rem; }
  .ts { color: #555; font-size: 0.7rem; }
  .card-body { color: #ddd; }
  .card-task { color: #666; font-size: 0.7rem; margin-top: 0.25rem; }
  .preview { color: #888; font-size: 0.75rem; }
</style>
