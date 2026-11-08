# Voice chain audit (@general subagent)

- **sessão:** `ses_f7ea66dd4ffeGdkpLOfBvdHohn`
- **quando:** 2026-09-08 14:08 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 4 (exportadas: 4)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai (read-only, NO edits), audit the VOICE integration chain: home-manager/modules/services/jarvis-wakeword.nix (daemon: VAD gate, scorer, confirmation, capture duration, timeouts) + modules/ai/jarvis/src/jarvis/core/voice.py + voice_clone.py + feedback.py (set_status/get_status/waybar_format, TTL) + STT path. Check: (1) VAD→STT boundary (sample rate/channels/dtype validation, frame loss, pre-roll, end-of-speech); (2) does Waybar/notification show ACTUAL state or last-event (hearing/listening/speaking semantics); (3) TTS interruption/restart behavior; (4) STT model input validation; (5) timeout semantics across capture(10s?)/STT/LLM/TTS — who wins; (6) retry safety of voice steps (duplicate side effects?); (7) idempotency of state transitions. file:line + verdict each. Max 80 lines. Do NOT fix.

---

## · ?

Auditing the voice chain read-only — checking VAD, STT, state, and timeouts.

---

## · ?

Found the core chain — now tracing STT validation and scorer details.

---

## · ?

AUDIT — voice chain (read-only, no fixes):

(1) VAD→STT boundary:
- `jarvis-wakeword.nix:280-285` pw-record `s16 stereo RATE=16000` (opt `:637-641`); `476` blocking `read(CHUNK*4)`=512 frames; `484-491` int16→mono avg+clip — VERDICT: rate/ch/dtype implicit, no validation at capture.
- `nix:519-523,573` pre-roll 15ch ~770ms prepended — VERDICT: OK, no loss on onset.
- `nix:477-481` `if not data: restart` — VERDICT: FAIL-open, frame gap unlogged, no seqno/overflow count.
- `nix:592,603-613` end-of-speech `max(baseline*1.1,peak*0.4,200)` +1.0s min +1.5s below gate else `MAX_RECORD` `:596-602` (`:649` default 10s, comment stale 12s) — VERDICT: relative-gate OK, hard-cut dilutes score.
- `ww_scorer.py:27-43` `load_mono16k` stereo-avg + nearest-resample any rate — VERDICT: tolerant, not strict validation.
- `voice.py:291-344` `transcribe(path)` passes path straight to WhisperModel — VERDICT: no wav/sr/ch/dur/size check.

(2) Waybar actual vs last-event:
- `feedback.py:43-68` `set_status` last-write-wins + `pkill -RTMIN+8`; `78-92` `get_status` TTL 45s transient→idle; `163-222` `waybar_format` pure render of file — VERDICT: shows last-event, TTL only anti-stuck, no liveness probe.
- `jarvis-wakeword.nix:497-510` pulse only if `idle`, never clobbers `transcribing/thinking/speaking/busy/done/error/listening` — VERDICT: OK, fixed prior desync.
- `nix:580` `hearing` on onset vs `357,373` `listening` only post-confirm — VERDICT: OK semantics (no phantom REC).
- `nix:322-324` killTTS reads `speaking+ts<30s` — VERDICT: heuristic, races `voice.py:484,731` writers.

(3) TTS interrupt/restart:
- `nix:315-329` `KILL_TTS` `pkill -9 pw-play/paplay/aplay/audiobook` unless fresh `speaking` — VERDICT: kill-only, no pause/resume, can cut own ack-echo w/o `suppress/echo` windows.
- `voice.py:500-514` `_play` sequential fallback each `timeout=30` — VERDICT: worst ~150s block, no cancel.
- `nix:240` `_play_ack pw-play` no timeout — VERDICT: hang risk. `voice.py:482-494` signal `speaking→play→finally idle` — VERDICT: no mid-synth interrupt.

(4) STT input validation:
- `voice.py:226-262` `_audio_stats` diagnostic-only; `302-305` missing dep → `ERROR:` string; `314-329` faster-whisper `vad_filter threshold .5/min_speech250/min_silence1000/pad400` — VERDICT: no empty/short/corrupt/duration cap.
- `voice.py:338-341` low-conf `<-0.60` → `""` conflated with silence — VERDICT: caller `619-625,640-643` maps both → `idle/rc2`, indistinguishable.
- `voice.py:779-805` `main_stt` only `exists` check, prints `ERROR:` text — VERDICT: minimal.

(5) Timeouts — who wins:
- capture 10s `:649` / silence 1.5s `:608` / phase2 8s `:372` / followup 12s `:455` / suppress 5s `:469` / cooldown 5s `:105` / scorer 60s `:386` / `BRAIN_TIMEOUT=120` `:304` ⊃ STT 60s `voice.py:606` + LLM 120s `config.py:42` + `_play` 30s + RVC 300s `voice_clone.py:221`/1800s `:173` — VERDICT: inner STT-60 wins first; outer-120 only for LLM/TTS hang; `clone=True` outer always wins (300>120).

(6) Retry safety:
- `voice.py:597-639` STT subprocess read-only — VERDICT: safe to retry.
- `voice.py:442,465-474,734-743` `speak/clone/notify/eventbus/play` per attempt, filename `hash%1e9` collision-prone — VERDICT: NOT safe, duplicates TTS/notify/audio side-effects, no dedup key.
- `nix:198-203` `_gen_ack` move-newest-wav race — VERDICT: NOT atomic.

(7) Idempotency of transitions:
- `feedback.py:43-96` + `nix:123-131` duplicate `set_status` impls, no CAS/version — VERDICT: races, last-writer-wins.
- `nix:345,348,470` `followup/expect/suppress` single-shot in-mem — VERDICT: lost on `Restart=always :704`/`_restart_capture:400-418`.
- `voice.py:623,641,650,655,756` multi-path `idle/done` then daemon `416` immediate `idle` — VERDICT: `done` ephemeral, transitions not idempotent/replayable.

---

