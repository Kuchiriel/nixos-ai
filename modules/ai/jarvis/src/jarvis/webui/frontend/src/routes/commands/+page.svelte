<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchCommands, executeCommand } from '$lib/api/client';

  let commands: any[] = $state([]);
  let loading = $state(true);
  let result: any = $state(null);
  let executing = $state('');

  onMount(async () => {
    commands = await fetchCommands();
    loading = false;
  });

  async function run(name: string, risk: string) {
    if ((risk === 'medium' || risk === 'high') && !confirm(`Execute ${name} (risk: ${risk})?`)) return;
    executing = name;
    result = await executeCommand(name);
    executing = '';
  }

  function grouped(cmds: any[]) {
    const cats: Record<string, any[]> = {};
    for (const c of cmds) {
      if (!cats[c.category]) cats[c.category] = [];
      cats[c.category].push(c);
    }
    return cats;
  }
</script>

<svelte:head><title>Jarvis — Commands</title></svelte:head>

<h1>Commands</h1>
<p class="subtitle">{commands.length} registered</p>

{#if loading}
  <p style="color:#666">Loading...</p>
{:else}
  {#each Object.entries(grouped(commands)) as [cat, cmds]}
    <h2>{cat}</h2>
    <div class="cmd-list">
      {#each cmds as cmd}
        <div class="cmd">
          <span class="cmd-risk risk-{cmd.risk}">{cmd.risk.toUpperCase()}</span>
          <span class="cmd-name">{cmd.name}</span>
          <span class="cmd-desc">{cmd.description}</span>
          <button
            class="btn-run"
            disabled={executing === cmd.name}
            onclick={() => run(cmd.name, cmd.risk)}
          >
            {executing === cmd.name ? '...' : 'Run'}
          </button>
        </div>
      {/each}
    </div>
  {/each}

  {#if result}
    <h2>Last Result</h2>
    <pre class="result" class:success={result.success} class:error={!result.success}>{JSON.stringify(result, null, 2)}</pre>
  {/if}
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; }
  .subtitle { font-size: 0.75rem; color: #666; margin-bottom: 1rem; }
  h2 { font-size: 0.85rem; color: #00d4ff; margin: 1rem 0 0.4rem; text-transform: uppercase; }
  .cmd-list { display: flex; flex-direction: column; gap: 2px; }
  .cmd { display: flex; align-items: center; gap: 0.5rem; padding: 0.4rem 0.6rem; background: #111; border-radius: 3px; font-size: 0.8rem; }
  .cmd-risk { padding: 0.1rem 0.3rem; border-radius: 3px; font-size: 0.6rem; font-weight: bold; min-width: 45px; text-align: center; }
  .risk-safe { background: #1a3a1a; color: #22c55e; }
  .risk-low { background: #3a3a1a; color: #eab308; }
  .risk-medium { background: #3a2a1a; color: #f97316; }
  .risk-high { background: #3a1a1a; color: #ef4444; }
  .cmd-name { font-family: monospace; min-width: 180px; }
  .cmd-desc { color: #666; flex: 1; }
  .btn-run { padding: 0.15rem 0.5rem; border: none; border-radius: 3px; background: #1a2a3a; color: #60a5fa; font-size: 0.7rem; font-family: inherit; }
  .btn-run:hover { background: #2a3a4a; }
  .btn-run:disabled { opacity: 0.5; }
  .result { padding: 0.75rem; border-radius: 4px; font-size: 0.75rem; max-height: 300px; overflow-y: auto; }
  .result.success { background: #0a1a0a; border: 1px solid #22c55e33; }
  .result.error { background: #1a0a0a; border: 1px solid #ef444433; }
</style>
