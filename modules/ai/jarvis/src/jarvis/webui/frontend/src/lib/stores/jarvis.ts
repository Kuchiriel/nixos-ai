import { writable, derived } from 'svelte/store';
import {
  fetchStatus,
  fetchCommands,
  fetchServices,
  connectSSE,
  type SystemStatus,
  type Command,
  type ServiceInfo
} from '$lib/api/client';

// ─── Stores ───────────────────────────────────────────────────────────

export const status = writable<SystemStatus | null>(null);
export const commands = writable<Command[]>([]);
export const services = writable<ServiceInfo[]>([]);
export const state = writable<Record<string, Record<string, any>>>({});
export const events = writable<any[]>([]);
export const loading = writable(true);
export const error = writable<string | null>(null);
export const connected = writable(false);

// ─── Derived ──────────────────────────────────────────────────────────

export const health = derived(status, ($s) => $s?.state?.health?.overall ?? 'unknown');
export const gamingProfile = derived(status, ($s) => $s?.state?.gaming?.profile ?? 'normal');
export const llmModel = derived(status, ($s) => $s?.state?.llm?.model ?? 'unknown');
export const voiceStatus = derived(status, ($s) => $s?.state?.voice?.status ?? 'idle');
export const activeServices = derived(services, ($s) => $s.filter(s => s.active).length);
export const totalServices = derived(services, ($s) => $s.length);

export const commandsByCategory = derived(commands, ($cmds) => {
  const cats: Record<string, Command[]> = {};
  for (const cmd of $cmds) {
    if (!cats[cmd.category]) cats[cmd.category] = [];
    cats[cmd.category].push(cmd);
  }
  return cats;
});

// ─── Actions ──────────────────────────────────────────────────────────

let sseConnection: EventSource | null = null;

export async function loadAll() {
  loading.set(true);
  error.set(null);
  try {
    const [s, c, svc] = await Promise.all([
      fetchStatus(),
      fetchCommands(),
      fetchServices(),
    ]);
    status.set(s);
    commands.set(c);
    services.set(svc);
    state.set(s.state);
    connected.set(true);
  } catch (e: any) {
    error.set(e.message);
    connected.set(false);
  } finally {
    loading.set(false);
  }
}

export function connectRealtime() {
  if (sseConnection) sseConnection.close();

  sseConnection = connectSSE(
    (data) => {
      connected.set(true);
      if (data.type === 'init') {
        state.set(data.state);
      } else if (data.type === 'state_change') {
        state.update((s) => {
          if (!s[data.section]) s[data.section] = {};
          s[data.section][data.key] = data.value;
          return { ...s };
        });
      }
      // Keep last 100 events
      events.update((evts) => {
        const newEvts = [...evts, { ...data, ts: Date.now() }];
        return newEvts.slice(-100);
      });
    },
    () => connected.set(false)
  );
}

export function disconnectRealtime() {
  if (sseConnection) {
    sseConnection.close();
    sseConnection = null;
  }
  connected.set(false);
}
