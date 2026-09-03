<script lang="ts">
  import { onMount } from 'svelte';
  import { fetchVoiceInfo } from '$lib/api/client';
  let voice: any = $state(null);
  onMount(async () => { voice = await fetchVoiceInfo(); });
</script>

<svelte:head><title>Jarvis — Voice</title></svelte:head>
<h1>Voice</h1>
{#if voice}
  <div class="info-grid">
    <div class="row"><span class="label">Status</span><span class="value">{voice.status}</span></div>
    <div class="row"><span class="label">Text</span><span class="value">{voice.text || '—'}</span></div>
    <div class="row"><span class="label">Last TTS</span><span class="value">{voice.last_tts_len ? `${voice.last_tts_len} chars` : '—'}</span></div>
  </div>
{:else}
  <p style="color:#666">Loading...</p>
{/if}

<style>
  h1 { font-size: 1.2rem; color: #00d4ff; margin-bottom: 1rem; }
  .info-grid { display: flex; flex-direction: column; gap: 2px; max-width: 500px; }
  .row { display: grid; grid-template-columns: 100px 1fr; padding: 0.5rem; background: #111; border-radius: 3px; font-size: 0.8rem; }
  .label { color: #666; text-transform: uppercase; font-size: 0.7rem; }
</style>
