# Map voice pipeline (@explore subagent)

- **sessão:** `ses_f8289e3b8ffeA8Xaow5B8arpVn`
- **quando:** 2026-09-07 20:01 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 9 (exportadas: 8)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Explore the JARVIS codebase at /home/nixos/projects/nixos-ai/modules/ai/jarvis/src and /home/nixos/projects/nixos-ai/scripts. Be very thorough. Focus on the voice pipeline: wakeword, capture, VAD, STT, TTS, state machine, feedback.

Read these files:
- jarvis/core/voice.py (830 lines)
- any file with "wakeword" in name (glob **/*wakeword*)
- any file with "stt" or "tts" in name
- jarvis/core/feedback.py
- jarvis/core/eventbus.py
- scripts/voice-selftest.sh
- scripts/jarvis-cli.sh

Also grep for: wakeword, VAD, faster-whisper, whisper.cpp, kokoro, stt, tts, voice state, "Hey Jarvis" across src/.

Report precisely:
1. Voice pipeline components: wakeword detection (model, threshold, sample rate, device), audio capture (source, format, pre-roll?), VAD, STT (which engine), TTS (which engine), playback. With file:line.
2. Is there a single voice state machine? What states? Or multiple independent states?
3. Is there feedback (waybar/notifications/sounds) tied to voice state? Does it read canonical state or maintain its own copies?
4. Hardcoded device IDs, sample rates, model paths, thresholds in voice code.
5. Is there a wakeword circular buffer / pre-roll to avoid losing speech after wakeword?
6. Does voice.py block the agent/eventbus (sync subprocess, time.sleep in async)?
7. How is voice wired to the agent (which function turns voice text into agent query)?

Return structured report with file:line references. Do NOT modify anything.

---

## · ?

I'll explore the JARVIS codebase thoroughly. Let me start by understanding the structure.

---

## · ?

Let me read the key files and explore the voice-related structure.

---

## · ?

Now let me read feedback.py, eventbus.py, the scripts, and the wakeword files.

---

## · ?

Now let me read the wakeword files and grep across the source for the key terms.

---

## · ?

Let me read the ww_scorer and grep for more voice-related terms.

---

## · ?

Let me look at the control plane, router, lang, busy modules, and how voice connects to the agent.

---

## · ?

Now let me look at the router (agent wiring), CLI main, providers interfaces, and the Nix models/audio config.

---

