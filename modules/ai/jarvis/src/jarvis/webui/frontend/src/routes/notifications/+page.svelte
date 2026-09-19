<script lang="ts">
  import { onMount } from 'svelte';
  import { notificationStatus, notificationHistory, loadNotificationStatus, loadNotificationHistory } from '$lib/stores/jarvis';
  import { sendNotification } from '$lib/api/client';

  let status = $state<any>(null);
  let history: any[] = $state([]);
  let title = $state('');
  let body = $state('');
  let severity = $state('info');
  let sending = $state(false);
  let loading = $state(true);

  onMount(async () => {
    await loadNotificationStatus();
    await loadNotificationHistory();
    status = $notificationStatus;
    history = $notificationHistory.history;
    loading = false;
  });

  async function handleSend() {
    if (!title.trim()) return;
    sending = true;
    try {
      await sendNotification(title, body, severity);
      title = '';
      body = '';
      await loadNotificationStatus();
      await loadNotificationHistory();
      history = $notificationHistory.history;
      status = $notificationStatus;
    } catch { /* ignore */ }
    finally { sending = false; }
  }

  function severityColor(s: string) {
    return s === 'critical' ? '#ef4444' : s === 'error' ? '#f97316' : s === 'warning' ? '#eab308' : s === 'success' ? '#22c55e' : '#60a5fa';
  }
</script>

<svelte:head><title>Jarvis — Notifications</title></svelte:head>

<h1>Notifications</h1>

{#if loading}
  <p style="color:#666">Loading...</p>
{:else}
  <div class="notif-panel">
    <div class="notif-status-card">
      <h2>Status Atual</h2>
      <div class="status-row">
        <span class="label">Foco:</span>
        <span class="value" class:focus-active={status?.focused}>{status?.focused ? '🔒 ATIVO' : '🔓 INATIVO'}</span>
      </div>
      {#if status?.last}
        <div class="status-row">
          <span class="label">Última:</span>
          <span class="value">{status.last.text}</span>
        </div>
        <div class="status-row">
          <span class="label">Prioridade:</span>
          <span class="value" style="color:{severityColor(status.last.priority)}">{status.last.priority.toUpperCase()}</span>
        </div>
      {/if}
    </div>

    <div class="notif-send">
      <h2>Enviar Notificação</h2>
      <input type="text" bind:value={title} placeholder="Título" class="input" />
      <textarea bind:value={body} placeholder="Corpo" class="input" />
      <select bind:value={severity} class="input">
        <option value="info">Info</option>
        <option value="success">Success</option>
        <option value="warning">Warning</option>
        <option value="error">Error</option>
        <option value="critical">Critical</option>
      </select>
      <button onclick={handleSend} disabled={sending || !title.trim()} class="btn-send">{sending ? 'Enviando...' : 'Enviar'}</button>
    </div>

    <div class="notif-history">
      <h2>Histórico ({history.length})</h2>
      {#if history.length === 0}
        <p class="empty">Nenhuma notificação ainda</p>
      {:else}
        <div class="history-list">
          {#each history as entry}
            <div class="history-entry">
              <span class="history-event">{entry.event}</span>
              <span class="history-channels">{entry.channels?.join(', ') ?? ''}</span>
              <span class="history-ts">{new Date(entry.ts).toLocaleTimeString()}</span>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; }
  h2 { font-size: 0.85rem; color: #00d4ff; margin: 1rem 0 0.4rem; text-transform: uppercase; }
  .notif-panel { display: flex; flex-direction: column; gap: 1rem; max-width: 600px; }
  .notif-status-card, .notif-send, .notif-history { background: #111; border: 1px solid #333; border-radius: 8px; padding: 1rem; }
  .status-row { display: flex; gap: 0.5rem; padding: 0.25rem 0; }
  .label { color: #666; min-width: 80px; }
  .value { color: #e0e0e0; }
  .focus-active { color: #22c55e; }
  .input { width: 100%; padding: 0.5rem; background: #1a1a1a; border: 1px solid #333; border-radius: 4px; color: #e0e0e0; font-family: inherit; font-size: 0.8rem; margin-bottom: 0.5rem; }
  select.input { cursor: pointer; }
  .btn-send { padding: 0.5rem 1rem; background: #1a2a3a; color: #60a5fa; border: none; border-radius: 4px; font-family: inherit; font-size: 0.8rem; cursor: pointer; }
  .btn-send:hover { background: #2a3a4a; }
  .btn-send:disabled { opacity: 0.5; cursor: not-allowed; }
  .empty { color: #555; font-size: 0.8rem; }
  .history-list { display: flex; flex-direction: column; gap: 2px; }
  .history-entry { display: flex; justify-content: space-between; padding: 0.3rem 0.5rem; background: #1a1a1a; border-radius: 3px; font-size: 0.75rem; }
  .history-event { color: #00d4ff; }
  .history-channels { color: #666; }
  .history-ts { color: #555; }
</style>
