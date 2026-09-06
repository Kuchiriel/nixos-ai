<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchLLMInfo, fetchConfig, fetchServices, fetchKeys, setKey, removeKey } from '$lib/api/client';
  let llm: any = $state(null);
  let config: any = $state(null);
  let services: any[] = $state([]);
  let keys: any = $state(null);
  let newProvider = $state('openrouter');
  let newKey = $state('');
  let keyMsg = $state('');

  onMount(async () => {
    llm = await fetchLLMInfo();
    config = await fetchConfig();
    services = await fetchServices();
    try { keys = await fetchKeys(); } catch { keys = null; }
  });

  async function saveKey() {
    if (!newKey.trim()) return;
    try {
      await setKey(newProvider, newKey.trim());
      keyMsg = `✓ ${newProvider} salva`;
      newKey = '';
      keys = await fetchKeys();
    } catch (e) { keyMsg = `✗ ${e}`; }
  }
  async function delKey(provider: string) {
    try {
      await removeKey(provider);
      keyMsg = `✓ ${provider} removida`;
      keys = await fetchKeys();
    } catch (e) { keyMsg = `✗ ${e}`; }
  }
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

{#if keys}
  <section>
    <h2>API Keys</h2>
    <div class="info-grid">
      <div class="row"><span class="label">Cascade</span><span class="value">{keys.cascade?.join(' → ') || 'local'}</span></div>
      {#each Object.entries(keys.providers || {}) as [provider, ok]}
      <div class="row">
        <span class="label">{provider}</span>
        <span class="value">
          <span style="color:{ok ? '#22c55e' : '#ef4444'}">{ok ? '● configurada' : '○ ausente'}</span>
          {#if ok}<button class="mini-btn" onclick={() => delKey(provider)}>remover</button>{/if}
        </span>
      </div>
      {/each}
    </div>
    <div class="key-form">
      <select bind:value={newProvider}>
        <option value="openrouter">openrouter</option>
        <option value="groq">groq</option>
        <option value="cerebras">cerebras</option>
        <option value="together">together</option>
        <option value="gemini">gemini</option>
        <option value="hf">hf</option>
      </select>
      <input type="password" placeholder="sk-..." bind:value={newKey} />
      <button onclick={saveKey}>salvar</button>
      {#if keyMsg}<span class="msg">{keyMsg}</span>{/if}
    </div>
    <p class="hint">Chaves salvas em /etc/litellm.env (fora do repo). Valores nunca exibidos.</p>
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
  .key-form { display: flex; gap: 0.5rem; margin-top: 0.6rem; max-width: 600px; }
  .key-form select, .key-form input { background: #111; border: 1px solid #333; color: #eee; border-radius: 3px; padding: 0.4rem; font-size: 0.8rem; }
  .key-form input { flex: 1; }
  .key-form button, .mini-btn { background: #0a3d62; border: none; color: #fff; border-radius: 3px; padding: 0.4rem 0.8rem; cursor: pointer; font-size: 0.75rem; }
  .mini-btn { margin-left: 0.5rem; padding: 0.15rem 0.5rem; background: #5a1a1a; }
  .msg { font-size: 0.75rem; color: #888; align-self: center; }
  .hint { font-size: 0.7rem; color: #555; max-width: 600px; }
</style>
