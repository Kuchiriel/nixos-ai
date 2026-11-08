# Baseline docs summary (@general subagent)

- **sessão:** `ses_f7ea66dffffe0ZZg3w8sWb2HdH`
- **quando:** 2026-09-08 14:08 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 3 (exportadas: 3)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai, read BUFFY.md, HANDOFF.md, docs/FORENSIC-SYSTEM-COHERENCE-2026-09-08.md (read-only, no edits). Return a COMPRESSED baseline (max 60 lines): (1) what changed in recent forensic sessions (commits/features), (2) what was intentionally left unresolved + declared BLOCKED, (3) what was declared verified/tested with what evidence, (4) remaining product decisions. Include exact file paths and commit hashes mentioned. Be factual, cite sections.

---

## · ?

Compressing those three forensic docs into a 60-line baseline.

---

## · ?

BASELINE COMPRESSED — nixos-ai 2026-09-08 (read-only, no edits)

SOURCES: `BUFFY.md` §11/§23, `HANDOFF.md` §§2026-09-07/08, `docs/FORENSIC-SYSTEM-COHERENCE-2026-09-08.md` (=FORENSIC) + `docs/audit/DEEP-ARCHITECTURAL-AUDIT-2026-09.md` §9/§10

(1) CHANGED — recent forensic sessions:
1. 2026-09-07 S2 [BUFFY §11]: `core/agent.py` malformed-tool guards (`func` non-dict, bad-JSON `arguments`, non-dict `args`) — `tests/test_solar_probe.py` 8→0; removed double PAST LESSONS re-injection; deleted ~200L dead (`execute_tool`/`run_loop`/`TOOLS`/`_extract_tool_calls`/`AgentError`); killed 4 `config.py` bypasses (`JARVIS_LLM_URL`,`LLAMA_CPP_URL`x2,`BackendHealthMonitor()`→`JARVIS_LLM_BASE_URL`); removed `_regex.txt`→`tool_patterns.py`.
2. 2026-09-08 S3 checkpoint [BUFFY §11/HANDOFF 2026-09-08 S3]: validated Codebuff `a0ae4ea` OK, `e4a4e24`+1 edge, `873d94f` dupe-spawn→`532f135` (single `_run_driver`, `clone_wav` adapter, CPU_ONLY via CUDA_VISIBLE_DEVICES); `1723b4b` `_get_llm_response()`→`LLMClient` (26 mocks +**kw); `1482622` `read_file`+`read` route + `tests/test_read_route.py` (11 contracts); `1ffb095` `run()` wiring (ToolValidator post-exec, per-prompt budget, dupe-breaker removed +2 tests).
3. 2026-09-08 coherence [HANDOFF pré-missão/FORENSIC §§Executive/Refactors]: `core/paths.py` NEW (`c98288a`,19 files, ctx>env>walk, contextvar replaces 5×monkeypatch, fixed `or True`); `scripts/rvc-env.sh` canonical (patchelf venv→nix-ld, proof `env -i`); STT small declarative (`models.nix`×4+symlinks, tiny.en 149MB removed, no `||true`); `8770df8` MCP `_handle_rag_search`→`QdrantStore`; `lessons("")`→`lessons(prompt)`; waybar ts fix; Agent suite unmarked 833→834 in Nix sandbox; earlier LoopDetector wired + `content=None` fix + profile-aware payload [HANDOFF 2026-09 Deep Audit]; older: `88c34f6,b02af88,296767a,d94fb10,840ab17,55e8088`, Corretor E2E `bd3919f2`.
4. Voice/RVC proven [FORENSIC §§Voice/Addendum, BUFFY §23]: zsh-env+stale-binary root-cause → 15.9s real Jarvis; 2 rebuilds OK; waybar flicker fix (`-x` in `feedback.py`+daemon, `wait $PPID` removed); `hearing` state until scorer confirm.

(2) INTENTIONALLY UNRESOLVED + BLOCKED:
5. FORENSIC §Remaining BLOCKED (5): [1] personas jarvismodes ADR-003 (stack+non-persist overlap proven); [2] `provider_registry` privacy ADR-004 (zero consumers, unwired); [3] `dev.py` (2529L) convergence (`agent_loop.py` plan not started); [4] WebUI canonical-state audit + long-run >30min E2E (TODO-MISSAO P3-2); [5] `jarvis chat` vs `ask` overlap (observed, uninvestigated). + product: default multi-provider (cost×latency×privacy).
6. Infra BLOCKED, not regressions [BUFFY §11 09-07/09-08]: `nightwatch_real_e2e`×3 + `platform_e2e`×2 need live Qdrant/llama.cpp. Older UNVERIFIED carried [BUFFY §§5-6/9]: SvelteKit browser (12 routes), real desktop/sound/telegram/voice delivery, service start/stop via real systemctl, `chat` routing privacy hot-path.

(3) VERIFIED/TESTED + EVIDENCE:
7. Suites: sandbox Nix `834 passed,0 failed` (was 781+50 skipped) [FORENSIC §Before/after]; local `998+/5 infra` (same 5) [FORENSIC §Evidence]; S2 `987/5` [BUFFY]; older `859/0/26 skipped/5 xpassed` [BUFFY §7/HANDOFF §Tests]; `test_agent.py` 30, `test_loop_detector.py` 15.
8. Live proofs: `/tmp/opencode/prova_sem_ld.wav`, `jarvis_tts_538684693-clone.wav` (15.9s 24kHz), logs clone_e2e/direct/nold/final, stt_probe/postrebuild [FORENSIC §Evidence]; post-rebuild-4 `jarvis speak <270ch>` 17.4s exit 0 + daemon RMS 630-1075 reject-correct + speaking→listening→idle [HANDOFF]. STT PT-BR + wakeword VAD proven live.
9. No-regression audits (no change): ContextBudget single (`c866439`), EventBus single async-safe, privacy cap PUBLIC, `except:pass` only optional/telemetry, `archive/` zero prod imports [BUFFY §11 09-07].

(4) REMAINING PRODUCT DECISIONS:
10. Resolve ADR-003 (1 Registry vs 3 mechanisms `persona.py` vs `persona_executor.py` vs `.jarvismodes`); ADR-004 wire-or-drop privacy choke; fund `dev.py` rewrite vs shim; define WebUI source-of-truth + fund >30min E2E; merge or split `chat`/`ask`; pick default provider policy.

---

