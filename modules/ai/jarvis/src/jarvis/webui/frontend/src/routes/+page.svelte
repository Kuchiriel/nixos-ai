<script lang="ts">
  import { onMount } from 'svelte';
  import { loadAll, loadFocus, loadNotificationStatus, focus, notificationStatus } from '$lib/stores/jarvis';
  import { fetchFocusStatus, fetchNotificationStatus, fetchServices, fetchCommands } from '$lib/api/client';

  let systemStatus: any = $state(null);
  let focusState: any = $state({ focused: false });
  let notifState: any = $state({ focused: false });
  let services: any[] = $state([]);
  let commands: any[] = $state([]);
  let loading = $state(true);
  let error: string | null = $state(null);

  onMount(async () => {
    try {
      const [status, focus, notif, svc, cmds] = await Promise.all([
        fetchStatus(), fetchFocusStatus(), fetchNotificationStatus(), fetchServices(), fetchCommands(),
      ]);
      systemStatus = status;
      focusState = focus;
      notifState = notif;
      services = svc;
      commands = cmds;
    } catch (e: any) { error = e.message; }
    finally { loading = false; }
  });

  async function toggleFocus() {
    try {
      const res = await fetch('/api/focus/toggle', { method: 'POST' });
      focusState = await res.json();
    } catch { /* ignore */ }
  }

  async function sendTestNotif() {
    try {
      await fetch('/api/notify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: 'Teste WebUI', body: 'Notificação do painel de controle', severity: 'info' }),
      });
    } catch { /* ignore */ }
  }
</script>

<svelte:head><title>Jarvis — Dashboard</title></svelte:head>

<h1>JARVIS Dashboard</h1>

{#if loading}
  <p style="color:#666">Carregando...</p>
{:else if error}
  <p style="color:#ef4444">Erro: {error}</p>
{:else}
  <div class="dashboard">
    <div class="card">
      <h2>🤖 Sistema</h2>
      <div class="stat">
        <span class="stat-label">Saúde</span>
        <span class="stat-value">{systemStatus?.state?.health?.overall ?? '—'}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Modelo LLM</span>
        <span class="stat-value">{systemStatus?.state?.llm?.model ?? '—'}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Serviços</span>
        <span class="stat-value">{services.filter(s => s.active).length}/{services.length}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Comandos</span>
        <span class="stat-value">{commands.length}</span>
      </div>
    </div>

    <div class="card">
      <h2>🔒 Focus Mode</h2>
      <div class="focus-card" class:focus-active={focusState?.focused}>
        <span class="focus-icon">{focusState?.focused ? '🔒' : '🔓'}</span>
        <span class="focus-label">{focusState?.focused ? 'Ativo' : 'Inativo'}</span>
      </div>
      <p class="focus-desc">
        {focusState?.focused
          ? 'Notificações críticas e de erro apenas.'
          : 'Todas as notificações ativas.'}
      </p>
      <button class="btn" onclick={toggleFocus}>
        {focusState?.focused ? 'Desativar' : 'Ativar'} Focus
      </button>
    </div>

    <div class="card">
      <h2>🔔 Notificações</h2>
      <div class="notif-card">
        <div class="notif-info">
          <span class="notif-label">Última:</span>
          <span class="notif-value">{notifState?.last?.text ?? 'Nenhuma'}</span>
        </div>
        <div class="notif-info">
          <span class="notif-label">Prioridade:</span>
          <span class="notif-value">{notifState?.last?.priority ?? '—'}</span>
        </div>
      </div>
      <button class="btn btn-send" onclick={sendTestNotif}>Enviar Teste</button>
    </div>

    <div class="card">
      <h2>📡 EventBus</h2>
      <div class="stat">
        <span class="stat-label">Events Publicados</span>
        <span class="stat-value">{systemStatus?.events?.events_published ?? '—'}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Events Entregues</span>
        <span class="stat-value">{systemStatus?.events?.events_delivered ?? '—'}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Subscritores</span>
        <span class="stat-value">{systemStatus?.events?.subscribers ?? '—'}</span>
      </div>
    </div>
  </div>
{/if}

<style>
  h1 { font-size: 1.4rem; color: #00d4ff; margin-bottom: 1rem; }
  .dashboard { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem; }
  .card {
    background: #111; border: 1px solid #222; border-radius: 8px;
    padding: 1.25rem; display: flex; flex-direction: column; gap: 0.5rem;
  }
  h2 { font-size: 0.9rem; color: #00d4ff; margin: 0; text-transform: uppercase; }
  .stat { display: flex; justify-content: space-between; padding: 0.25rem 0; }
  .stat-label { color: #666; }
  .stat-value { color: #e0e0e0; font-weight: bold; }
  .focus-card {
    display: flex; align-items: center; gap: 0.75rem; padding: 1rem;
    background: #1a1a1a; border-radius: 6px; border: 1px solid #333;
  }
  .focus-active { border-color: #f59e0b; background: #1a1510; }
  .focus-icon { font-size: 1.5rem; }
  .focus-label { font-weight: bold; }
  .focus-desc { color: #888; font-size: 0.8rem; }
  .btn {
    padding: 0.5rem 1rem; background: #1a2a3a; color: #60a5fa;
    border: none; border-radius: 4px; font-family: inherit; font-size: 0.8rem;
    cursor: pointer; transition: all 0.2s; align-self: flex-start;
  }
  .btn:hover { background: #2a3a4a; }
  .btn-send { background: #1a3a1a; color: #22c55e; }
  .btn-send:hover { background: #2a4a2a; }
  .notif-card { background: #1a1a1a; border-radius: 6px; padding: 0.75rem; }
  .notif-info { display: flex; gap: 0.5rem; padding: 0.15rem 0; }
  .notif-label { color: #666; }
  .notif-value { color: #e0e0e0; }
</style>
