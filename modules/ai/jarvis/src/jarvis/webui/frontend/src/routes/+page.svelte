<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { fetchStatus, fetchServices, fetchLLMInfo, fetchVoiceInfo, connectSSE } from '$lib/api/client';

  let status: any = $state(null);
  let services: any[] = $state([]);
  let llm: any = $state(null);
  let voice: any = $state(null);
  let events: any[] = $state([]);
  let agent: any = $state(null);
  let connected = $state(false);
  let loading = $state(true);

  let sse: EventSource | null = null;

  onMount(async () => {
    try {
      [status, services, llm, voice] = await Promise.all([
        fetchStatus(), fetchServices(), fetchLLMInfo(), fetchVoiceInfo()
      ]);
      agent = status?.state?.agent || {};
    } catch (e) { console.error(e); }
    loading = false;

    sse = connectSSE((data) => {
      connected = true;
      if (data.type === 'event') {
        events = [...events, { ...data, ts: Date.now() }].slice(-50);
      }
      if (data.type === 'state_change' && data.section === 'agent') {
        if (!agent) agent = {};
        agent[data.key] = data.value;
      }
      if (data.type === 'event' && data.topic?.startsWith('harness.')) {
        if (data.data?.event_type === 'task_started') {
          if (!agent) agent = {};
          agent.active_task = data.data.task_id || '';
          agent.status = 'running';
        } else if (data.data?.event_type === 'task_completed') {
          if (!agent) agent = {};
          agent.active_task = '';
          agent.status = 'idle';
          agent.last_commit = data.data.commit || '';
        } else if (data.data?.event_type === 'task_failed') {
          if (!agent) agent = {};
          agent.active_task = '';
          agent.status = 'error';
          agent.last_error = data.data.error || '';
        }
      }
    }, () => connected = false);
  });

  onDestroy(() => sse?.close());

  function healthColor(h: string) {
    return h === 'ok' ? '#22c55e' : h === 'degraded' ? '#eab308' : '#ef4444';
  }

  function agentStatusColor(s: string) {
    switch (s) {
      case 'running': return '#3b82f6';
      case 'idle': return '#22c55e';
      case 'error': return '#ef4444';
      case 'blocked': return '#f97316';
      default: return '#555';
    }
  }

  let healthVal = $derived(status?.state?.health?.overall || 'unknown');
  let gamingVal = $derived(status?.state?.gaming?.profile || 'normal');
  let llmModel = $derived(llm?.model || '?');
  let llmColor = $derived(llm?.healthy ? '#22c55e' : '#ef4444');
  let voiceVal = $derived(voice?.status || 'idle');
  let activeCount = $derived(services.filter(s => s.active).length);
  let agentStatus = $derived(agent?.status || 'idle');
  let agentColor = $derived(agentStatusColor(agentStatus));
  let isWorking = $derived(agent?.active_task || agentStatus === 'running');
</script>

<svelte:head><title>Jarvis — Dashboard</title></svelte:head>

{#if loading}
  <div style="text-align:center;padding:3rem;color:#666">Loading...</div>
{:else}
  <!-- Status Bar -->
  <div class="status-bar">
    <div class="status-item">
      <span class="dot" style="background:{healthColor(healthVal)}"></span>
      <span>Health: {healthVal}</span>
    </div>
    <div class="status-item">
      <span class="dot" style="background:{llmColor}"></span>
      <span>LLM: {llm?.status || 'unknown'}</span>
    </div>
    <div class="status-item">
      <span class="dot" style="background:#00d4ff"></span>
      <span>Voice: {voiceVal}</span>
    </div>
    <div class="status-item">
      <span class="dot" style="background:{agentColor}"></span>
      <span>Agent: {agentStatus}</span>
    </div>
    <div class="status-item">
      <span>{connected ? '● LIVE' : '○ OFFLINE'}</span>
    </div>
  </div>

  <!-- Quick Stats -->
  <div class="grid-7">
    <div class="card">
      <div class="card-label">Health</div>
      <div class="card-value" style="color:{healthColor(healthVal)}">{healthVal}</div>
    </div>
    <div class="card">
      <div class="card-label">Gaming</div>
      <div class="card-value">{gamingVal}</div>
    </div>
    <div class="card">
      <div class="card-label">LLM</div>
      <div class="card-value" style="font-size:0.75rem">{llmModel}</div>
    </div>
    <div class="card">
      <div class="card-label">Voice</div>
      <div class="card-value">{voiceVal}</div>
    </div>
    <div class="card">
      <div class="card-label">Services</div>
      <div class="card-value">{activeCount}/{services.length}</div>
    </div>
    <div class="card">
      <div class="card-label">Agent</div>
      <div class="card-value" style="color:{agentColor}">{agentStatus}</div>
    </div>
    <div class="card">
      <div class="card-label">Events</div>
      <div class="card-value">{events.length}</div>
    </div>
  </div>

  <!-- Agent Status Panel -->
  {#if isWorking}
    <div class="agent-panel">
      <div class="agent-header">
        <span class="agent-dot" style="background:{agentColor}"></span>
        <span class="agent-title">Agent Working</span>
      </div>
      <div class="agent-grid">
        <div class="agent-row"><span class="agent-label">Task</span><span class="agent-value">{agent?.active_task || '—'}</span></div>
        <div class="agent-row"><span class="agent-label">Persona</span><span class="agent-value">{agent?.active_persona || '—'}</span></div>
        <div class="agent-row"><span class="agent-label">Project</span><span class="agent-value">{agent?.active_project || '—'}</span></div>
        <div class="agent-row"><span class="agent-label">Status</span><span class="agent-value" style="color:{agentColor}">{agentStatus}</span></div>
      </div>
    </div>
  {/if}

  <!-- Agent Last Activity -->
  {#if agent?.last_commit || agent?.last_error}
    <div class="agent-activity">
      {#if agent?.last_commit}
        <div class="activity-item success">✅ Last commit: {agent.last_commit.slice(0, 8)}</div>
      {/if}
      {#if agent?.last_error}
        <div class="activity-item error">❌ Last error: {agent.last_error.slice(0, 120)}</div>
      {/if}
    </div>
  {/if}

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
        <span class="evt-time">{new Date((evt.ts || Date.now() / 1000) * 1000).toLocaleTimeString()}</span>
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

  .grid-7 { display: grid; grid-template-columns: repeat(7, 1fr); gap: 0.5rem; margin-bottom: 1rem; }
  .card { background: #111; border: 1px solid #222; border-radius: 6px; padding: 0.75rem; text-align: center; }
  .card-label { font-size: 0.65rem; color: #666; text-transform: uppercase; }
  .card-value { font-size: 1.1rem; font-weight: bold; margin-top: 0.2rem; text-transform: capitalize; }

  .agent-panel { background: #0a1520; border: 1px solid #1a3050; border-radius: 6px; padding: 0.8rem; margin-bottom: 1rem; }
  .agent-header { display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem; }
  .agent-dot { width: 10px; height: 10px; border-radius: 50%; animation: pulse 2s infinite; }
  .agent-title { font-size: 0.85rem; color: #00d4ff; font-weight: bold; }
  .agent-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.5rem; }
  .agent-row { display: flex; flex-direction: column; }
  .agent-label { font-size: 0.6rem; color: #555; text-transform: uppercase; }
  .agent-value { font-size: 0.8rem; color: #ccc; font-family: monospace; }
  @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }

  .agent-activity { display: flex; gap: 1rem; margin-bottom: 1rem; }
  .activity-item { font-size: 0.75rem; padding: 0.3rem 0.6rem; border-radius: 4px; background: #111; }
  .activity-item.success { color: #22c55e; }
  .activity-item.error { color: #ef4444; }

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
