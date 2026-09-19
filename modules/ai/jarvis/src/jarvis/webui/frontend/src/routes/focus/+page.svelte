<script lang="ts">
  import { onMount } from 'svelte';
  import { focus, doFocusEnable, doFocusDisable, doFocusToggle, loadFocus, loadNotificationStatus } from '$lib/stores/jarvis';
  import { fetchNotificationStatus } from '$lib/api/client';

  let focused = $state(false);
  let loading = $state(true);

  onMount(async () => {
    await loadFocus();
    await loadNotificationStatus();
    focused = $focus.focused;
    loading = false;
  });

  async function toggle() {
    await doFocusToggle();
    focused = $focus.focused;
  }

  async function enable() {
    await doFocusEnable();
    focused = $focus.focused;
  }

  async function disable() {
    await doFocusDisable();
    focused = $focus.focused;
  }
</script>

<svelte:head><title>Jarvis — Focus Mode</title></svelte:head>

<h1>Focus Mode</h1>

{#if loading}
  <p style="color:#666">Loading...</p>
{:else}
  <div class="focus-card">
    <div class="focus-indicator" class:active={focused}>
      <span class="focus-icon">{focused ? '🔒' : '🔓'}</span>
      <span class="focus-text">{focused ? 'Foco Ativo' : 'Modo Normal'}</span>
    </div>
    <p class="focus-desc">
      {focused
        ? 'Notificações críticas e de erro apenas. Notificações informativas silenciadas.'
        : 'Todas as notificações ativas.'}
    </p>
    <div class="focus-actions">
      <button class="btn" class:btn-active={focused} onclick={enable}>Ativar</button>
      <button class="btn" class:btn-active={!focused} onclick={disable}>Desativar</button>
      <button class="btn btn-toggle" onclick={toggle}>Toggle</button>
    </div>
    <div class="focus-status">
      <span class="badge" class:badge-active={focused}>{focused ? 'ATIVO' : 'INATIVO'}</span>
    </div>
  </div>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; }
  .focus-card { background: #111; border: 1px solid #333; border-radius: 8px; padding: 1.5rem; max-width: 400px; }
  .focus-indicator { display: flex; align-items: center; gap: 0.75rem; padding: 1rem; border-radius: 6px; background: #1a1a1a; border: 1px solid #333; transition: all 0.3s; }
  .focus-indicator.active { border-color: #f59e0b; background: #1a1510; }
  .focus-icon { font-size: 1.5rem; }
  .focus-text { font-size: 1rem; font-weight: bold; }
  .focus-desc { color: #888; margin: 1rem 0; font-size: 0.85rem; }
  .focus-actions { display: flex; gap: 0.5rem; flex-wrap: wrap; }
  .btn { padding: 0.5rem 1rem; border: 1px solid #333; border-radius: 4px; background: #1a1a1a; color: #e0e0e0; font-family: inherit; font-size: 0.8rem; cursor: pointer; transition: all 0.2s; }
  .btn:hover { background: #2a2a2a; }
  .btn-active { border-color: #00d4ff; color: #00d4ff; }
  .btn-toggle { border-color: #f59e0b; color: #f59e0b; }
  .badge { display: inline-block; padding: 0.2rem 0.6rem; border-radius: 3px; font-size: 0.7rem; font-weight: bold; margin-top: 1rem; }
  .badge-active { background: #1a3a1a; color: #22c55e; }
</style>
