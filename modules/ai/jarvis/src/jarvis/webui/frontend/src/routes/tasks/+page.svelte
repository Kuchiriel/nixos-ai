<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { fetchTasks, executeCommand, connectSSE, type TaskInfo } from '$lib/api/client';

  let tasks: TaskInfo[] = $state([]);
  let mission: Record<string, any> = $state({});
  let loading = $state(true);
  let connected = $state(false);
  let filter = $state('');
  let sse: EventSource | null = null;
  let actionPending = $state('');

  async function retryTask(taskId: string) {
    actionPending = taskId;
    try {
      await executeCommand('task.retry', { task_id: taskId }, true);
      const data = await fetchTasks(100);
      tasks = data.tasks;
    } catch (e) { console.error(e); }
    actionPending = '';
  }

  async function cancelTask(taskId: string) {
    if (!confirm('Abandon this task?')) return;
    actionPending = taskId;
    try {
      await executeCommand('task.cancel', { task_id: taskId }, true);
      const data = await fetchTasks(100);
      tasks = data.tasks;
    } catch (e) { console.error(e); }
    actionPending = '';
  }

  onMount(async () => {
    try {
      const data = await fetchTasks(100);
      tasks = data.tasks;
      mission = data.mission;
    } catch (e) {
      console.error(e);
    }
    loading = false;

    sse = connectSSE((data) => {
      connected = true;
      // Refresh tasks when harness events arrive
      if (data.type === 'event' && data.topic?.startsWith('harness.')) {
        fetchTasks(100).then(d => { tasks = d.tasks; mission = d.mission; });
      }
    }, () => connected = false);
  });

  onDestroy(() => sse?.close());

  function filtered(items: TaskInfo[]) {
    if (!filter) return items;
    const f = filter.toLowerCase();
    return items.filter(t =>
      t.description.toLowerCase().includes(f) ||
      t.project.toLowerCase().includes(f) ||
      t.status.toLowerCase().includes(f)
    );
  }

  function statusColor(s: string) {
    switch (s) {
      case 'COMPLETED': return '#22c55e';
      case 'IN_PROGRESS': return '#3b82f6';
      case 'VALIDATING': return '#a855f7';
      case 'REVIEW': return '#f59e0b';
      case 'READY': return '#06b6d4';
      case 'FAILED': return '#ef4444';
      case 'BLOCKED': return '#f97316';
      case 'ABANDONED': return '#6b7280';
      default: return '#555';
    }
  }

  function timeAgo(ts: number) {
    if (!ts) return '—';
    const diff = Date.now() / 1000 - ts;
    if (diff < 60) return `${Math.floor(diff)}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  let activeCount = $derived(tasks.filter(t => ['IN_PROGRESS', 'VALIDATING', 'REVIEW'].includes(t.status)).length);
  let completedCount = $derived(tasks.filter(t => t.status === 'COMPLETED').length);
  let failedCount = $derived(tasks.filter(t => t.status === 'FAILED').length);
  let readyCount = $derived(tasks.filter(t => t.status === 'READY' || t.status === 'DISCOVERED').length);
</script>

<svelte:head><title>Jarvis — Tasks</title></svelte:head>

<div class="header">
  <h1>Tasks</h1>
  <span class="live">{connected ? '● LIVE' : '○ OFFLINE'}</span>
  <input class="filter" placeholder="Filter tasks..." bind:value={filter} />
</div>

{#if loading}
  <p style="color:#666">Loading...</p>
{:else}
  <!-- Stats -->
  <div class="stats">
    <div class="stat">
      <span class="stat-value" style="color:#3b82f6">{activeCount}</span>
      <span class="stat-label">Active</span>
    </div>
    <div class="stat">
      <span class="stat-value" style="color:#06b6d4">{readyCount}</span>
      <span class="stat-label">Ready</span>
    </div>
    <div class="stat">
      <span class="stat-value" style="color:#22c55e">{completedCount}</span>
      <span class="stat-label">Completed</span>
    </div>
    <div class="stat">
      <span class="stat-value" style="color:#ef4444">{failedCount}</span>
      <span class="stat-label">Failed</span>
    </div>
    {#if mission.active}
      <div class="stat">
        <span class="stat-value" style="color:#f59e0b">●</span>
        <span class="stat-label">Mission Active</span>
      </div>
    {/if}
  </div>

  <!-- Task list -->
  <div class="task-list">
    {#each filtered(tasks) as task (task.id)}
      <div class="task">
        <div class="task-header">
          <span class="task-status" style="color:{statusColor(task.status)}">{task.status}</span>
          <span class="task-project">{task.project}</span>
          <span class="task-id">{task.id.slice(0, 12)}</span>
          <span class="task-time">{timeAgo(task.updated_at)}</span>
        </div>
        <div class="task-desc">{task.description}</div>
        {#if task.last_error}
          <div class="task-error">❌ {task.last_error.slice(0, 120)}</div>
        {/if}
        {#if task.commit_sha}
          <div class="task-commit">✅ Commit: {task.commit_sha.slice(0, 8)}</div>
        {/if}
        <div class="task-meta">
          <span>p{task.priority}</span>
          <span>risk:{task.risk}</span>
          <span>attempts:{task.attempts}</span>
          {#if task.target_files.length > 0}
            <span>files:{task.target_files.length}</span>
          {/if}
          <span class="task-actions">
            {#if task.status === 'FAILED' || task.status === 'BLOCKED'}
              <button class="btn-retry" disabled={actionPending === task.id} onclick={() => retryTask(task.id)}>
                {actionPending === task.id ? '...' : 'Retry'}
              </button>
            {/if}
            {#if !['COMPLETED', 'ABANDONED'].includes(task.status)}
              <button class="btn-cancel" disabled={actionPending === task.id} onclick={() => cancelTask(task.id)}>
                {actionPending === task.id ? '...' : 'Cancel'}
              </button>
            {/if}
          </span>
        </div>
      </div>
    {/each}
    {#if filtered(tasks).length === 0}
      <div class="empty">No tasks found. Tasks appear when Nightwatch discovers or executes work.</div>
    {/if}
  </div>
{/if}

<style>
  .header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem; }
  h1 { font-size: 1.2rem; color: #00d4ff; }
  .live { font-size: 0.75rem; color: #22c55e; }
  .filter { background: #111; border: 1px solid #333; color: #e0e0e0; padding: 0.3rem 0.6rem; border-radius: 4px; font-family: inherit; font-size: 0.8rem; width: 200px; }

  .stats { display: flex; gap: 1.5rem; margin-bottom: 1.5rem; }
  .stat { display: flex; flex-direction: column; align-items: center; }
  .stat-value { font-size: 1.5rem; font-weight: bold; }
  .stat-label { font-size: 0.65rem; color: #666; text-transform: uppercase; }

  .task-list { display: flex; flex-direction: column; gap: 4px; max-height: calc(100vh - 200px); overflow-y: auto; }
  .task { background: #111; border-radius: 4px; padding: 0.6rem 0.8rem; border-left: 3px solid #333; }
  .task:hover { border-left-color: #00d4ff; }
  .task-header { display: flex; gap: 0.75rem; align-items: center; margin-bottom: 0.3rem; }
  .task-status { font-weight: bold; font-size: 0.7rem; min-width: 90px; }
  .task-project { color: #00d4ff; font-size: 0.7rem; }
  .task-id { color: #555; font-family: monospace; font-size: 0.65rem; }
  .task-time { color: #555; font-size: 0.65rem; margin-left: auto; }
  .task-desc { color: #ccc; font-size: 0.8rem; margin-bottom: 0.2rem; }
  .task-error { color: #ef4444; font-size: 0.7rem; font-family: monospace; margin: 0.2rem 0; }
  .task-commit { color: #22c55e; font-size: 0.7rem; font-family: monospace; margin: 0.2rem 0; }
  .task-meta { display: flex; gap: 0.75rem; color: #555; font-size: 0.65rem; align-items: center; }
  .task-actions { margin-left: auto; display: flex; gap: 0.3rem; }
  .task-actions button { padding: 0.1rem 0.4rem; border: none; border-radius: 3px; font-size: 0.65rem; font-family: inherit; cursor: pointer; }
  .btn-retry { background: #1a3a1a; color: #22c55e; }
  .btn-retry:hover { background: #2a4a2a; }
  .btn-cancel { background: #3a1a1a; color: #ef4444; }
  .btn-cancel:hover { background: #4a2a2a; }
  .task-actions button:disabled { opacity: 0.4; cursor: not-allowed; }
  .empty { color: #555; font-style: italic; padding: 2rem; text-align: center; }
</style>
