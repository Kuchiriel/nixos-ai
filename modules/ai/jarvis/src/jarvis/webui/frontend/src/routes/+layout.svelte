<script lang="ts">
  import { page } from '$app/state';
  let { children } = $props();

  const nav = [
    { href: '/', label: 'Dashboard', icon: '◉' },
    { href: '/activity', label: 'Activity', icon: '◈' },
    { href: '/agent', label: 'Agent', icon: '◎' },
    { href: '/tasks', label: 'Tasks', icon: '◇' },
    { href: '/services', label: 'Services', icon: '⬡' },
    { href: '/llm', label: 'LLM', icon: '⬢' },
    { href: '/voice', label: 'Voice', icon: '◉' },
    { href: '/memory', label: 'Memory', icon: '◇' },
    { href: '/projects', label: 'Projects', icon: '◈' },
    { href: '/nightwatch', label: 'Nightwatch', icon: '◎' },
    { href: '/commands', label: 'Commands', icon: '⬡' },
    { href: '/mcp', label: 'MCP Tools', icon: '⚙' },
    { href: '/config', label: 'Config', icon: '⚙' },
    { href: '/system', label: 'System', icon: '⬢' },
  ];
</script>

<div class="app">
  <nav class="sidebar">
    <div class="logo">🤖 JARVIS</div>
    {#each nav as item}
      <a
        href={item.href}
        class="nav-item"
        class:active={item.href === '/' ? page.url.pathname === '/' : page.url.pathname.startsWith(item.href)}
      >
        <span class="nav-icon">{item.icon}</span>
        <span class="nav-label">{item.label}</span>
      </a>
    {/each}
  </nav>
  <main class="content">
    {@render children()}
  </main>
</div>

<style>
  :global(*) { box-sizing: border-box; margin: 0; padding: 0; }
  :global(body) {
    background: #0a0a0a; color: #e0e0e0;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 13px;
  }
  :global(a) { color: #00d4ff; text-decoration: none; }
  :global(button) { cursor: pointer; }

  .app { display: flex; height: 100vh; }
  .sidebar {
    width: 180px; background: #111; border-right: 1px solid #222;
    display: flex; flex-direction: column; padding: 0.5rem 0;
    overflow-y: auto; flex-shrink: 0;
  }
  .logo {
    padding: 0.75rem 1rem; font-size: 1rem; font-weight: bold;
    color: #00d4ff; border-bottom: 1px solid #222; margin-bottom: 0.25rem;
  }
  .nav-item {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.4rem 1rem; color: #888; font-size: 0.8rem;
    transition: all 0.15s;
  }
  .nav-item:hover { color: #e0e0e0; background: #1a1a1a; }
  .nav-item.active { color: #00d4ff; background: #0a1a2a; border-left: 2px solid #00d4ff; }
  .nav-icon { font-size: 0.7rem; min-width: 16px; text-align: center; }
  .content { flex: 1; overflow-y: auto; padding: 1rem 1.5rem; }
</style>
