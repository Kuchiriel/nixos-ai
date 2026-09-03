<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchStatus } from '$lib/api/client';
  let status: any = $state(null);
  onMount(async () => { status = await fetchStatus(); });
</script>

<svelte:head><title>Jarvis — System</title></svelte:head>
<h1>System</h1>
{#if status}
  <h2>State</h2>
  <pre class="json">{JSON.stringify(status.state, null, 2)}</pre>
  <h2>Event Bus</h2>
  <pre class="json">{JSON.stringify(status.events, null, 2)}</pre>
{:else}
  <p style="color:#666">Loading...</p>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 1rem; }
  h2 { font-size: 0.85rem; color: #00d4ff; margin: 1rem 0 0.4rem; text-transform: uppercase; }
  .json { background: #111; padding: 0.75rem; border-radius: 4px; font-size: 0.75rem; max-height: 400px; overflow-y: auto; white-space: pre-wrap; }
</style>
