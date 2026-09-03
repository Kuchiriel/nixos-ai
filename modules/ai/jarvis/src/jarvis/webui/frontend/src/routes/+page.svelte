<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import {
    status, commands, services, state, events, loading, error, connected,
    health, gamingProfile, llmModel, voiceStatus,
    activeServices, totalServices,
    commandsByCategory,
    loadAll, connectRealtime, disconnectRealtime
  } from '$lib/stores/jarvis';
  import { executeCommand } from '$lib/api/client';

  onMount(() => {
    loadAll();
    connectRealtime();
  });

  onDestroy(() => {
    disconnectRealtime();
  });

  async function runCommand(name: string) {
    try {
      await executeCommand(name);
      await loadAll(); // Refresh
    } catch (e: any) {
      alert(`Command failed: ${e.message}`);
    }
  }

  function healthColor(h: string): string {
    return h === 'ok' ? '#22c55e' : h === 'degraded' ? '#eab308' : '#ef4444';
  }

  function formatTime(ts: number): string {
    return new Date(ts * 1000).toLocaleTimeString();
  }
</script>

<svelte:head>
  <title>Jarvis Control Plane</title>
  <meta name="description" content="Jarvis AI System Control Plane" />
</svelte:head>

<main>
  <header>
    <h1>🤖 Jarvis Control Plane</h1>
    <div class="status-bar">
      <span class="indicator" style="background: {healthColor($health)}" title="Health: {$health}"></span>
      <span class="label">{$health}</span>
      {#if $connected}
        <span class="connected">● LIVE</span>
      {:else}
        <span class="disconnected">○ OFFLINE</span>
      {/if}
    </div>
  </header>

  {#if $loading}
    <div class="loading">Loading...</div>
  {:else if $error}
    <div class="error">Error: {$error}</div>
  {:else}
    <!-- Quick Stats -->
    <section class="stats">
      <div class="stat-card">
        <div class="stat-label">Health</div>
        <div class="stat-value" style="color: {healthColor($health)}">{$health}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Gaming</div>
        <div class="stat-value">{$gamingProfile}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">LLM</div>
        <div class="stat-value">{$llmModel}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Voice</div>
        <div class="stat-value">{$voiceStatus}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Services</div>
        <div class="stat-value">{$activeServices}/{$totalServices}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Commands</div>
        <div class="stat-value">{$commands.length}</div>
      </div>
    </section>

    <!-- Services -->
    <section>
      <h2>Services</h2>
      <div class="service-grid">
        {#each $services as svc}
          <div class="service-card" class:active={svc.active} class:failed={!svc.active && svc.enabled}>
            <div class="service-header">
              <span class="service-status">{svc.active ? '✅' : '❌'}</span>
              <span class="service-name">{svc.name}</span>
            </div>
            <div class="service-detail">{svc.description}</div>
            <div class="service-actions">
              {#if svc.active}
                <button class="btn-small" onclick={() => runCommand('service.stop')}>Stop</button>
              {:else}
                <button class="btn-small btn-primary" onclick={() => runCommand('service.start')}>Start</button>
              {/if}
            </div>
          </div>
        {/each}
      </div>
    </section>

    <!-- Commands -->
    <section>
      <h2>Commands</h2>
      {#each Object.entries($commandsByCategory) as [category, cmds]}
        <div class="command-category">
          <h3>{category}</h3>
          <div class="command-list">
            {#each cmds as cmd}
              <div class="command-item">
                <span class="cmd-risk" class:risk-low={cmd.risk === 'low'} class:risk-safe={cmd.risk === 'safe'} class:risk-medium={cmd.risk === 'medium'} class:risk-high={cmd.risk === 'high'}>
                  {cmd.risk.toUpperCase()}
                </span>
                <span class="cmd-name">{cmd.name}</span>
                <span class="cmd-desc">{cmd.description}</span>
                <button class="btn-tiny" onclick={() => runCommand(cmd.name)}>Run</button>
              </div>
            {/each}
          </div>
        </div>
      {/each}
    </section>

    <!-- Activity -->
    <section>
      <h2>Activity ({$events.length} events)</h2>
      <div class="event-list">
        {#each $events.slice().reverse().slice(0, 20) as evt}
          <div class="event-item">
            <span class="event-type">{evt.type}</span>
            {#if evt.section}
              <span class="event-section">{evt.section}.{evt.key}</span>
            {/if}
            <span class="event-time">{new Date(evt.ts).toLocaleTimeString()}</span>
          </div>
        {/each}
        {#if $events.length === 0}
          <div class="empty">No events yet. Waiting for real-time updates...</div>
        {/if}
      </div>
    </section>
  {/if}
</main>

<style>
  :root {
    --bg: #0a0a0a;
    --surface: #1a1a1a;
    --border: #2a2a2a;
    --text: #e0e0e0;
    --text-muted: #888;
    --accent: #00d4ff;
    --success: #22c55e;
    --warning: #eab308;
    --error: #ef4444;
  }

  :global(*) { box-sizing: border-box; margin: 0; padding: 0; }

  :global(body) { background: var(--bg); color: var(--text); font-family: 'JetBrains Mono', monospace; }

  main { max-width: 1200px; margin: 0 auto; padding: 1rem; }

  header {
    display: flex; justify-content: space-between; align-items: center;
    padding: 1rem; border-bottom: 1px solid var(--border); margin-bottom: 1rem;
  }

  h1 { font-size: 1.5rem; color: var(--accent); }

  .status-bar { display: flex; align-items: center; gap: 0.5rem; }
  .indicator { width: 10px; height: 10px; border-radius: 50%; }
  .connected { color: var(--success); font-size: 0.8rem; }
  .disconnected { color: var(--text-muted); font-size: 0.8rem; }

  .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0.5rem; margin-bottom: 1.5rem; }
  .stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; text-align: center; }
  .stat-label { font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; }
  .stat-value { font-size: 1.5rem; font-weight: bold; margin-top: 0.25rem; text-transform: capitalize; }

  section { margin-bottom: 1.5rem; }
  h2 { font-size: 1.1rem; color: var(--accent); margin-bottom: 0.75rem; border-bottom: 1px solid var(--border); padding-bottom: 0.25rem; }
  h3 { font-size: 0.9rem; color: var(--text-muted); margin: 0.75rem 0 0.5rem; text-transform: uppercase; }

  .service-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 0.5rem; }
  .service-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 0.75rem; }
  .service-card.active { border-left: 3px solid var(--success); }
  .service-card.failed { border-left: 3px solid var(--error); }
  .service-header { display: flex; align-items: center; gap: 0.5rem; }
  .service-name { font-weight: bold; font-size: 0.85rem; }
  .service-detail { font-size: 0.75rem; color: var(--text-muted); margin: 0.25rem 0; }
  .service-actions { margin-top: 0.5rem; }

  .command-list { display: flex; flex-direction: column; gap: 0.25rem; }
  .command-item { display: flex; align-items: center; gap: 0.5rem; background: var(--surface); padding: 0.5rem; border-radius: 4px; font-size: 0.8rem; }
  .cmd-risk { padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.65rem; font-weight: bold; min-width: 40px; text-align: center; }
  .risk-safe { background: #1a3a1a; color: var(--success); }
  .risk-low { background: #3a3a1a; color: var(--warning); }
  .risk-medium { background: #3a2a1a; color: #f97316; }
  .risk-high { background: #3a1a1a; color: var(--error); }
  .cmd-name { min-width: 180px; font-family: monospace; }
  .cmd-desc { color: var(--text-muted); flex: 1; }

  .event-list { display: flex; flex-direction: column; gap: 0.25rem; max-height: 400px; overflow-y: auto; }
  .event-item { display: flex; gap: 0.75rem; padding: 0.4rem; background: var(--surface); border-radius: 4px; font-size: 0.75rem; }
  .event-type { color: var(--accent); min-width: 100px; }
  .event-section { color: var(--text-muted); }
  .event-time { color: var(--text-muted); margin-left: auto; }
  .empty { color: var(--text-muted); font-style: italic; padding: 1rem; text-align: center; }

  .btn-small, .btn-tiny { background: var(--border); color: var(--text); border: none; padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer; font-size: 0.7rem; }
  .btn-small:hover, .btn-tiny:hover { background: #3a3a3a; }
  .btn-primary { background: var(--accent); color: #000; }
  .btn-primary:hover { background: #00b8d9; }

  .loading, .error { text-align: center; padding: 2rem; }
  .error { color: var(--error); }
</style>
