<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { fetchEventHistory, connectSSE } from '$lib/api/client';

  let history: any[] = $state([]);
  let realtime: any[] = $state([]);
  let connected = $state(false);
  let filter = $state('');
  let sse: EventSource | null = null;

  onMount(async () => {
    history = await fetchEventHistory(200);
    sse = connectSSE((data) => {
      connected = true;
      if (data.type === 'event' || data.type === 'state_change') {
        realtime = [...realtime, { ...data, ts: Date.now() }].slice(-200);
      }
    }, () => connected = false);
  });

  onDestroy(() => sse?.close());

  function filtered(items: any[]) {
    if (!filter) return items;
    const f = filter.toLowerCase();
    return items.filter(i =>
      (i.topic || i.type || '').toLowerCase().includes(f) ||
      (i.data_summary || i.section || '').toLowerCase().includes(f)
    );
  }

  $effect(() => {
    // Merge history and realtime, newest first
    allEvents = [...realtime, ...history].sort((a, b) => (b.ts || 0) - (a.ts || 0));
  });

  let allEvents: any[] = $state([]);
</script>

<svelte:head><title>Jarvis — Activity</title></svelte:head>

<div class="header">
  <h1>Activity</h1>
  <span class="live">{connected ? '● LIVE' : '○ OFFLINE'}</span>
  <input class="filter" placeholder="Filter events..." bind:value={filter} />
</div>

<div class="timeline">
  {#each filtered(allEvents).slice(0, 100) as evt}
    <div class="evt">
      <span class="evt-time">{new Date((evt.ts || 0) * 1000).toLocaleTimeString()}</span>
      <span class="evt-type">{evt.type || 'event'}</span>
      <span class="evt-topic">{evt.topic || evt.section || ''}</span>
      <span class="evt-detail">{evt.data_summary || evt.key || ''}</span>
    </div>
  {/each}
  {#if allEvents.length === 0}
    <div class="empty">No events recorded yet. Events appear in real-time as components publish to the EventBus.</div>
  {/if}
</div>

<style>
  .header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem; }
  h1 { font-size: 1.2rem; color: #00d4ff; }
  .live { font-size: 0.75rem; color: #22c55e; }
  .filter { background: #111; border: 1px solid #333; color: #e0e0e0; padding: 0.3rem 0.6rem; border-radius: 4px; font-family: inherit; font-size: 0.8rem; width: 200px; }
  .timeline { display: flex; flex-direction: column; gap: 2px; max-height: calc(100vh - 120px); overflow-y: auto; }
  .evt { display: grid; grid-template-columns: 80px 100px 150px 1fr; gap: 0.5rem; padding: 0.35rem 0.5rem; background: #111; border-radius: 3px; font-size: 0.75rem; }
  .evt-time { color: #555; }
  .evt-type { color: #00d4ff; }
  .evt-topic { color: #888; }
  .evt-detail { color: #666; }
  .empty { color: #555; font-style: italic; padding: 2rem; text-align: center; }
</style>
