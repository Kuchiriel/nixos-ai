const getApiBase = (): string => {
  if (typeof window !== 'undefined') {
    const host = window.location.hostname || '127.0.0.1';
    return `${window.location.protocol}//${host}:8090/api`;
  }
  return 'http://127.0.0.1:8090/api';
};

const API_BASE = getApiBase();

export interface SystemStatus {
  state: Record<string, Record<string, any>>;
  events: {
    events_published: number;
    events_delivered: number;
    events_failed: number;
    dlq_size: number;
    subscribers: number;
  };
  services: Record<string, {
    active: boolean;
    enabled: boolean;
    status: string;
  }>;
}

export interface Command {
  name: string;
  description: string;
  risk: string;
  category: string;
  requires_confirmation: boolean;
  enabled: boolean;
  args: Record<string, string> | null;
}

export interface CommandResult {
  command: string;
  success: boolean;
  result: any;
  error: string;
  duration_ms: number;
  ts: number;
  source: string;
}

export interface ServiceInfo {
  name: string;
  active: boolean;
  enabled: boolean;
  status: string;
  scope: string;
  description: string;
}

export async function fetchStatus(): Promise<SystemStatus> {
  const res = await fetch(`${API_BASE}/status`);
  if (!res.ok) throw new Error(`Status fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchState(): Promise<Record<string, Record<string, any>>> {
  const res = await fetch(`${API_BASE}/state`);
  if (!res.ok) throw new Error(`State fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchCommands(): Promise<Command[]> {
  const res = await fetch(`${API_BASE}/commands`);
  if (!res.ok) throw new Error(`Commands fetch failed: ${res.status}`);
  return res.json();
}

export async function executeCommand(
  name: string,
  args: Record<string, any> = {},
  confirmed = false
): Promise<CommandResult> {
  const res = await fetch(`${API_BASE}/commands/${name}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ args, source: 'webui', confirmed }),
  });
  if (!res.ok) throw new Error(`Command execution failed: ${res.status}`);
  return res.json();
}

export async function fetchServices(): Promise<ServiceInfo[]> {
  const res = await fetch(`${API_BASE}/services`);
  if (!res.ok) throw new Error(`Services fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchLLMInfo(): Promise<any> {
  const res = await fetch(`${API_BASE}/llm`);
  if (!res.ok) throw new Error(`LLM fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchVoiceInfo(): Promise<any> {
  const res = await fetch(`${API_BASE}/voice`);
  if (!res.ok) throw new Error(`Voice fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchMemoryInfo(): Promise<any> {
  const res = await fetch(`${API_BASE}/memory`);
  if (!res.ok) throw new Error(`Memory fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchAgentInfo(): Promise<any> {
  const res = await fetch(`${API_BASE}/agent`);
  if (!res.ok) throw new Error(`Agent fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchNightwatchInfo(): Promise<any> {
  const res = await fetch(`${API_BASE}/nightwatch`);
  if (!res.ok) throw new Error(`Nightwatch fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchProjects(): Promise<any[]> {
  const res = await fetch(`${API_BASE}/projects`);
  if (!res.ok) throw new Error(`Projects fetch failed: ${res.status}`);
  return res.json();
}

export async function fetchEventHistory(limit = 100): Promise<any[]> {
  const res = await fetch(`${API_BASE}/events/history?limit=${limit}`);
  if (!res.ok) throw new Error(`Event history fetch failed: ${res.status}`);
  return res.json();
}

export interface TaskInfo {
  id: string;
  project: string;
  description: string;
  status: string;
  priority: number;
  risk: string;
  attempts: number;
  last_error: string | null;
  commit_sha: string | null;
  created_at: number;
  updated_at: number;
  target_files: string[];
}

export interface TasksResponse {
  tasks: TaskInfo[];
  mission: Record<string, any>;
  total: number;
}

export async function fetchTasks(limit = 50): Promise<TasksResponse> {
  const res = await fetch(`${API_BASE}/tasks?limit=${limit}`);
  if (!res.ok) throw new Error(`Tasks fetch failed: ${res.status}`);
  return res.json();
}

export async function sendNotification(
  title: string,
  body: string = '',
  severity: string = 'info'
): Promise<{ notified: string[] }> {
  const res = await fetch(`${API_BASE}/notify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, body, severity }),
  });
  if (!res.ok) throw new Error(`Notify failed: ${res.status}`);
  return res.json();
}

export function connectSSE(
  onStateChange: (data: any) => void,
  onError?: (err: Event) => void
): EventSource {
  const es = new EventSource(`${API_BASE}/events/stream`);
  es.onopen = () => {
    onStateChange({ type: 'sse_connected' });
  };
  es.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onStateChange(data);
    } catch {
      // heartbeat or malformed
    }
  };
  if (onError) es.onerror = onError;
  return es;
}
