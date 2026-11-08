# Mapear budgets context-shift (@general subagent)

- **sessão:** `ses_ee94c66ffffeI1njEKFoYz7Zof`
- **quando:** 2026-10-07 14:10 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 9 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

READ-ONLY. Em /home/nixos/projects/nixos-ai: (1) ache budgets.py (ou similar: context_budget.py, context shift) — como funciona o context-shift do harness (quando dispara, o que descarta/preserva, limites por modelo); (2) ache como opencode configura compaction (opencode.json compaction, auto-compaction) e se dá para replicar a política do harness (preservar X, resumir Y); (3) liste os limites de contexto por modelo local (do models.nix: ctx de cada um). Devolva: mecanismo budgets (arquivo:linha + regra), config compaction opencode atual, e proposta concreta de ponte (o que copiar de um para o outro). Terse.

---

## · ?

Mapping your harness budgets, opencode compaction, and local ctx limits.

---

## · ?

Found the budget core and model scopes — now pulling the exact trigger rules and your current compaction setup.

---

## · ?

Almost complete — checking the final preservation details and remaining provider limits.

---

## · ?

## 1. Mecanismo budgets (harness)

`modules/ai/jarvis/src/jarvis/core/context_budget.py` (canônico; `nightwatch/context_budget.py:1-15` é só shim re-export).

* `ContextBudget:298-313`: `max_tokens=32000`, `reserved=2000`, `warning=0.80`, `compaction=0.85`. `__post_init__:333-339` sobrescreve com `/props` n_ctx real se default.
* Disparo `should_compact:595-599`: `current >= max*0.85`. `get_recommendation:632-666`: `>0.9 critical/compact_aggressively`, `>0.8 high/compact`, `>0.6 medium/monitor`, `>0.7 suggest_drop=[old_tool_outputs,completed_task_history,nonessential_files]`.
* `truncate_tool_outputs:468-499`: por `TOOL_OUTPUT_PRIORITY:33-42` + `TRUNCATE_LIMITS:45-54` (shell 4000, read 3000, search 2000/run_tests 3000, ls 1000, resto 500; `aggressive` = /2). Pula `<500ch`. **Preserva** `_anchor_lines:287-294` (regex `VEREDITO:|CONFIRMADO|CORRIGIDO|HIPÓTESE:|/home/nixos/…`, max 20, 200ch cada) em tail `[âncoras preservadas]`.
* `compress_history:501-565` (`keep_last=6`): mantém `system[0]+user[1]+últimos 6`. Tool → 5 primeiras linhas + keywords (`error/fail/traceback/.py/.nix/commit/passed/failed…`, max 15). Assistant → só blocos ` ``` ` senão 300ch. Outro role → marcador genérico.
* Send-time (não muta store) `core/agent.py:198-230`: `_HIST_TOOL_BUDGET=12000ch`, `_HIST_KEEP_LAST=2` intactos, tool antiga `>500ch→floor 500ch + [truncated…re-read]`; assistant intocado.
* REPL `cli/dev.py:2284-2318` + `_compact_session:506-536`: dispara `est>70% ctx→alvo 50%`. Preserva `system + resumo (user 150ch/assistant 150ch/tool 80ch) + últimos 6`, realinha p/ começar em `user`.
* Harness `nightwatch/harness.py:147` usa `compaction_threshold=0.7` (≠ 0.85 do core); init `1730-1744` auto-detect `/props` senão `MIN_PROFILE_CONTEXT=8192`; Step 0b `2214-2225` só **registra** `record_compaction(est, est//2)` + notify — não trunca mensagem (teatro); `classify_failure:75-77` marca `CONTEXT_EXHAUSTION` em `context/token/exceeds/overflow`.
* Aux: `ctx_derived_max_tokens:61-82` = `ctx//12` (fallback 2048); `sync_from_slots:417-426`, `record_actual*:392-416` calibra estimado vs `usage` real; `CANONICAL_CONTEXT=32768 / MIN=8192` em `core/provider_registry.py:40,44`.

## 2. Compaction opencode atual

`home-manager/home.nix:561-572` (global, vale p/ todos providers):
```nix
small_model="local/bonsai"; compaction={auto=true; prune=true;};
tool_output={max_lines=200; max_bytes=8192;};
```
Sem threshold configurável (opencode decide; `limit.context` por modelo é o denominador — sem `limit` contexto=0 → auto-compact no 1º prompt, bug 03/10 comentado em `:312-313`). `prune` ≈ `truncate_tool_outputs`; sem equivalente a âncoras/resumo seletivo.

## 3. Limites ctx por modelo local

`models.nix:routing.ctx` vs `profiles.ctxSize` vs `opencode limit.context` (divergem!):

| modelo | routing.ctx | profile ctxSize real servido | opencode limit |
|---|---|---|---|
| bonsai 8B (:8080) | 49152 | bonsai 49152 | 49152 / out 8192 |
| jarvis-fast (:8083) | 49152 | qwen-fast **16384** | 16384 / out 4096 |
| jarvis-strong (:8084) | 32768 | chat **8192** | — (35B via local-uncensored 8192/2048) |
| raw-fast / raw-strong | 16384 / 8192 | idem | — |
| direct: 4b-MTP :8092 | — | 65536 | 65536/4096 |
| deepseek :8085 | — | 16384 | 16384/8192 |
| phi :8086, gemma :8087 | — | 32768 | 32768/4096 |
| xlam :8089, 30b :8091, q4kp :8093, 35b :8084 | — | 8192 | 8192 (+out 2048/4096) |
| jarvis profile | — | 4096 | — |

## 4. Ponte concreta (copiar)

1. Alinhar `limit.context` ao `ctxSize` servido (não ao `routing.ctx`): `jarvis-fast 49152→16384` já ok; corrigir doc que cita 49152 como real.
2. Replicar âncoras no opencode: não há hook; o aproximado é `compaction{auto,prune}` + `tool_output{200/8192}` atuais + mover vereditos/paths p/ arquivo (fora do transcript podado) — equivale a `_anchor_lines`.
3. Trazer números do harness p/ cá: `threshold 70%→50%` (dev.py) cabe como convenção manual (opencode não expõe threshold); `keep_last 6` e `floor 500ch/12000ch` já cobertos por `prune + max_bytes 8192`.
4. Trazer p/ lá: `small_model=bonsai` (resumos fora do 35B) + `max_bytes` hard-cap (harness só trunca por prioridade, sem teto absoluto de 8KB).

---

