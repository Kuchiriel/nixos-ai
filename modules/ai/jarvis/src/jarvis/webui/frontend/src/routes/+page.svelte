<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { fetchStatus, fetchServices, fetchLLMInfo, fetchVoiceInfo, connectSSE } from '$lib/api/client';

  let status: any = $state(null);
  let services: any[] = $state([]);
  let llm: any = $state(null);
  let voice: any = $state(null);
  let events: any[] = $state([]);
  let connected = $state(false);
  let loading = $state(true);

  let sse: EventSource | null = null;

  onMount(async () => {
    try {
      [status, services, llm, voice] = await Promise.all([
        fetchStatus(), fetchServices(), fetchLLMInfo(), fetchVoiceInfo()
      ]);
    } catch (e) { console.error(e); }
    loading = false;

    sse = connectSSE((data) => {
      connected = true;
      if (data.type === 'event') {
        events = [...events, { ...data, ts: Date.now() }].slice(-50);
      }
    }, () => connected = false);
  });

  onDestroy(() => sse?.close());

  function healthColor(h: string) {
    return h === 'ok' ? '#22c55e' : h === 'degraded' ? '#eab308' : '#ef4444';
  }
</script>

<svelte:head><title>Jarvis — Dashboard</title></svelte:head>

{#if loading}
  <div style="text-align:center;padding:3rem;color:#666">Loading...</div>
{:else}
  <!-- Status Bar -->
  <div class="status-bar">
    <div class="status-item">
      <span class="dot" style="background:{healthColor(status?.state?.health?.overall || 'unknown')}"></span>
      <span>Health: {status?.state?.health?.overall || 'unknown'}</span>
    </div>
    <div class="status-item">
      <span class="dot" style="background:{llm?.healthy ? '#22c55e' : '#ef4444'}"></span>
      <span>LLM: {llm?.status || 'unknown'}</span>
    </div>
    <div class="status-item">
      <span class="dot" style="background:#00d4ff"></span>
      <span>Voice: {voice?.status || 'idle'}</span>
    </div>
    <div class="status-item">
      <span>{connected ? '● LIVE' : '○ OFFLINE'}</span>
    </div>
  </div>

  <!-- Quick Stats -->
  <div class="grid-6">
    <div class="card">
      <div class="card-label">Health</div>
      <div class="card-value" style="color:{healthColor(status?.state?.health?.overall || 'unknown')}">
        {status?.state?.health?.overall || 'unknown'}
      </div>
    </div>
    <div class="card">
      <div class="card-label">Gaming</div>
      <div class="card-value">{status?.state?.gaming?.profile || 'normal'}</div>
    </div>
    <div class="card">
      <div class="card-label">LLM</div>
      <div class="card-value" style="font-size:0.75rem">{llm?.model || '?'}</div>
    </div>
    <div class="card">
      <div class="card-label">Voice</div>
      <div class="card-value">{voice?.status || 'idle'}</div>
    </div>
    <div class="card">
      <div class="card-label">Services</div>
      <div class="card-value">{services.filter(s => s.active).length}/{services.length}</div>
    </div>
    <div class="card">
      <div class="card-label">Events</div>
      <div class="card-value">{events.length}</div>
    </div>
  </div>

  <!-- Services -->
  <h2>Services</h2>
  <div class="service-grid">
    {#each services as svc}
      <div class="svc" class:active={svc.active}>
        <span class="svc-dot" style="background:{svc.active ? '#22c55e' : '#ef4444'}"></span>
        <span class="svc-name">{svc.name}</span>
        <span class="svc-desc">{svc.description || ''}</span>
      </div>
    {/each}
  </div>

  <!-- Recent Events -->
  <h2>Recent Events</h2>
  <div class="event-list">
    {#each events.slice().reverse().slice(0, 15) as evt}
      <div class="evt">
        <span class="evt-topic">{evt.topic || evt.type}</span>
        <span class="evt-data">{evt.data_summary || evt.section || ''}</span>
        <span class="evt-time">{new Date((evt.ts || Date.now()/1000) * 1000).toLocaleTimeString()}</span>
      </div>
    {/each}
    {#if events.length === 0}
      <div class="empty">Waiting for events...</div>
    {/if}
  </div>
{/if}

<style>
  h2 { font-size: 0.9rem; color: #00d4ff; margin: 1.5rem 0 0.5rem; text-transform: uppercase; letter-spacing: 0.05em; }
  .status-bar { display: flex; gap: 1.5rem; padding: 0.5rem 0; margin-bottom: 1rem; font-size: 0.8rem; color: #888; }
  .status-item { display: flex; align-items: center; gap: 0.4rem; }
  .dot { width: 8px; height: 8px; border-radius: 50%; }

  .grid-6 { display: grid; grid-template-columns: repeat(6, 1fr); gap: 0.5rem; margin-bottom: 1rem; }
  .card { background: #111; border: 1px solid #222; border-radius: 6px; padding: 0.75rem; text-align: center; }
  .card-label { font-size: 0.65rem; color: #666; text-transform: uppercase; }
  .card-value { font-size: 1.2rem; font-weight: bold; margin-top: 0.2rem; text-transform: capitalize; }

  .service-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.4rem; }
  .svc { display: flex; align-items: center; gap: 0.5rem; background: #111; padding: 0.4rem 0.6rem; border-radius: 4px; font-size: 0.75rem; }
  .svc.active { border-left: 2px solid #22c55e; }
  .svc-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
  .svc-name { font-weight: bold; min-width: 140px; }
  .svc-desc { color: #666; }

  .event-list { max-height: 300px; overflow-y: auto; }
  .evt { display: flex; gap: 0.75rem; padding: 0.3rem 0.5rem; background: #111; border-radius: 3px; margin-bottom: 2px; font-size: 0.75rem; }
  .evt-topic { color: #00d4ff; min-width: 120px; }
  .evt-data { color: #888; flex: 1; }
  .evt-time { color: #555; }
  .empty { color: #555; font-style: italic; padding: 1rem; text-align: center; }
</style>
