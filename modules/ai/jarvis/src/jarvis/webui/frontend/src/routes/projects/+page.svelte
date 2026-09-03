<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchProjects } from '$lib/api/client';
  let projects: any[] = $state([]);
  onMount(async () => { projects = await fetchProjects(); });
</script>

<svelte:head><title>Jarvis — Projects</title></svelte:head>
<h1>Projects</h1>
<p class="subtitle">{projects.length} discovered</p>

<div class="list">
  {#each projects as p}
    <div class="proj">
      <span class="proj-name">{p.name}</span>
      <span class="proj-type">{p.type}</span>
      <span class="proj-path">{p.path}</span>
    </div>
  {/each}
  {#if projects.length === 0}
    <div class="empty">No projects discovered</div>
  {/if}
</div>

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; }
  .subtitle { font-size: 0.75rem; color: #666; margin-bottom: 1rem; }
  .list { display: flex; flex-direction: column; gap: 2px; }
  .proj { display: grid; grid-template-columns: 150px 80px 1fr; padding: 0.5rem; background: #111; border-radius: 3px; font-size: 0.8rem; }
  .proj-name { font-weight: bold; }
  .proj-type { color: #00d4ff; font-size: 0.7rem; }
  .proj-path { color: #555; font-family: monospace; font-size: 0.7rem; }
  .empty { color: #555; font-style: italic; padding: 1rem; text-align: center; }
</style>
