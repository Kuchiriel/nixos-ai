<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchMcpTools, callMcpTool, type McpToolInfo } from '$lib/api/client';

  let tools: McpToolInfo[] = $state([]);
  let loading = $state(true);
  let selectedTool: McpToolInfo | null = $state(null);
  let argsJson = $state('{}');
  let approveMutation = $state(false);
  let executing = $state(false);
  let callResult: any = $state(null);
  let errorMessage: string | null = $state(null);
  let filterText = $state('');

  onMount(async () => {
    try {
      tools = await fetchMcpTools();
      if (tools.length > 0) {
        selectedTool = tools[0];
        approveMutation = selectedTool.write;
      }
    } catch (e: any) {
      errorMessage = e.message;
    } finally {
      loading = false;
    }
  });

  function selectTool(t: McpToolInfo) {
    selectedTool = t;
    approveMutation = t.write;
    callResult = null;
    errorMessage = null;
    argsJson = '{}';
  }

  async function executeSelected() {
    if (!selectedTool) return;
    executing = true;
    callResult = null;
    errorMessage = null;

    let parsedArgs = {};
    try {
      parsedArgs = JSON.parse(argsJson);
    } catch (e: any) {
      errorMessage = `Invalid JSON arguments: ${e.message}`;
      executing = false;
      return;
    }

    try {
      callResult = await callMcpTool(selectedTool.name, parsedArgs, approveMutation);
    } catch (e: any) {
      errorMessage = e.message;
    } finally {
      executing = false;
    }
  }

  let filteredTools = $derived(
    tools.filter(t => 
      t.name.toLowerCase().includes(filterText.toLowerCase()) || 
      t.description.toLowerCase().includes(filterText.toLowerCase())
    )
  );
</script>

<svelte:head><title>Jarvis — MCP Tools Bridge</title></svelte:head>

<h1>⚙️ MCP Tools Bridge</h1>
<p class="subtitle">{tools.length} Registered MCP Tools (HTTP Bridge & SSE Audited)</p>

{#if loading}
  <p style="color:#666">Loading MCP tools...</p>
{:else}
  <div class="mcp-layout">
    <!-- Tools Sidebar List -->
    <div class="tools-sidebar">
      <input 
        type="text" 
        placeholder="Filter tools..." 
        bind:value={filterText} 
        class="search-box" 
      />
      <div class="tools-list">
        {#each filteredTools as tool}
          <button 
            class="tool-item" 
            class:active={selectedTool?.name === tool.name}
            onclick={() => selectTool(tool)}
          >
            <div class="tool-name-row">
              <span class="tool-name">{tool.name}</span>
              {#if tool.write}
                <span class="badge-write">WRITE</span>
              {:else}
                <span class="badge-read">READ</span>
              {/if}
            </div>
            <span class="tool-desc-short">{tool.description}</span>
          </button>
        {/each}
      </div>
    </div>

    <!-- Active Tool Execution Detail Panel -->
    <div class="tool-detail">
      {#if selectedTool}
        <div class="detail-header">
          <h2>{selectedTool.name}</h2>
          {#if selectedTool.write}
            <span class="badge-write">GATED (Requires Approval)</span>
          {:else}
            <span class="badge-read">READ ONLY</span>
          {/if}
        </div>
        <p class="detail-desc">{selectedTool.description}</p>

        <div class="editor-box">
          <label for="args-editor" class="input-label">Arguments (JSON):</label>
          <textarea 
            id="args-editor"
            bind:value={argsJson} 
            rows="5" 
            class="json-textarea"
            placeholder={'Enter JSON arguments (e.g. {"query": "search text"})'}
          ></textarea>

          {#if selectedTool.write}
            <div class="approval-toggle">
              <label class="checkbox-label">
                <input type="checkbox" bind:checked={approveMutation} />
                <span>Approve State Mutation (approve=true)</span>
              </label>
              <span class="gate-hint">Without approval, mutating tools return HTTP 403.</span>
            </div>
          {/if}

          <button 
            class="btn-execute" 
            disabled={executing} 
            onclick={executeSelected}
          >
            {executing ? 'Executing via MCP Bridge...' : '▶ Execute Tool'}
          </button>
        </div>

        {#if errorMessage}
          <div class="error-banner">
            ❌ <strong>Error:</strong> {errorMessage}
          </div>
        {/if}

        {#if callResult}
          <div class="result-box">
            <h3>Execution Output:</h3>
            <pre class="output-pre">{typeof callResult.result === 'string' ? callResult.result : JSON.stringify(callResult, null, 2)}</pre>
          </div>
        {/if}
      {:else}
        <p style="color:#666">Select a tool from the list to view and execute.</p>
      {/if}
    </div>
  </div>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 0.25rem; }
  .subtitle { font-size: 0.75rem; color: #666; margin-bottom: 1rem; }

  .mcp-layout { display: grid; grid-template-columns: 320px 1fr; gap: 1rem; height: calc(100vh - 120px); }
  
  .tools-sidebar { display: flex; flex-direction: column; gap: 0.5rem; border-right: 1px solid #222; padding-right: 1rem; }
  .search-box { background: #111; border: 1px solid #333; border-radius: 4px; padding: 0.5rem; color: #fff; font-family: inherit; font-size: 0.8rem; }
  .tools-list { display: flex; flex-direction: column; gap: 4px; overflow-y: auto; flex: 1; }

  .tool-item { background: #111; border: 1px solid #222; border-radius: 4px; padding: 0.6rem; text-align: left; transition: all 0.15s ease; cursor: pointer; }
  .tool-item:hover { background: #1a1a1a; border-color: #00d4ff; }
  .tool-item.active { background: #112233; border-color: #00d4ff; }

  .tool-name-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem; }
  .tool-name { font-weight: bold; font-size: 0.8rem; color: #e0e0e0; }
  .tool-desc-short { font-size: 0.7rem; color: #888; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }

  .badge-write { background: #3a1a1a; color: #ef4444; font-size: 0.6rem; padding: 2px 6px; border-radius: 3px; font-weight: bold; border: 1px solid #ef4444; }
  .badge-read { background: #1a3a1a; color: #22c55e; font-size: 0.6rem; padding: 2px 6px; border-radius: 3px; font-weight: bold; border: 1px solid #22c55e; }

  .tool-detail { display: flex; flex-direction: column; gap: 1rem; overflow-y: auto; padding-left: 0.5rem; }
  .detail-header { display: flex; align-items: center; gap: 1rem; }
  .detail-header h2 { font-size: 1.1rem; color: #00d4ff; }
  .detail-desc { font-size: 0.85rem; color: #aaa; line-height: 1.4; background: #111; padding: 0.75rem; border-radius: 4px; border: 1px solid #222; }

  .editor-box { display: flex; flex-direction: column; gap: 0.75rem; background: #111; padding: 1rem; border-radius: 4px; border: 1px solid #222; }
  .input-label { font-size: 0.75rem; color: #888; text-transform: uppercase; font-weight: bold; }
  .json-textarea { background: #0a0a0a; border: 1px solid #333; border-radius: 4px; padding: 0.6rem; color: #00d4ff; font-family: inherit; font-size: 0.8rem; resize: vertical; }

  .approval-toggle { display: flex; flex-direction: column; gap: 0.25rem; background: #1a1510; border: 1px solid #eab308; padding: 0.6rem; border-radius: 4px; }
  .checkbox-label { display: flex; align-items: center; gap: 0.5rem; color: #eab308; font-weight: bold; font-size: 0.8rem; cursor: pointer; }
  .gate-hint { font-size: 0.7rem; color: #a1a1aa; }

  .btn-execute { background: #00d4ff; color: #000; font-weight: bold; border: none; padding: 0.6rem 1rem; border-radius: 4px; font-size: 0.85rem; font-family: inherit; align-self: flex-start; }
  .btn-execute:hover { filter: brightness(1.1); }
  .btn-execute:disabled { opacity: 0.5; cursor: not-allowed; }

  .error-banner { background: #3a1a1a; border: 1px solid #ef4444; color: #ef4444; padding: 0.75rem; border-radius: 4px; font-size: 0.8rem; }
  .result-box { background: #0a0a0a; border: 1px solid #222; border-radius: 4px; padding: 1rem; display: flex; flex-direction: column; gap: 0.5rem; }
  .result-box h3 { font-size: 0.85rem; color: #22c55e; }
  .output-pre { background: #111; padding: 0.75rem; border-radius: 4px; color: #e0e0e0; font-size: 0.75rem; overflow-x: auto; max-height: 400px; white-space: pre-wrap; word-break: break-all; }
</style>
