# Inventariar testes espalhados (@general subagent)

- **sessão:** `ses_f2517f03effe0LlHzMjOtHLvMs`
- **quando:** 2026-09-25 23:30 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 12 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

Inventarie TODOS os materiais de teste/bench/harness espalhados nesta máquina (só leitura, nada de rodar). Locais: /tmp/l8* /tmp/l9* /tmp/parity* /tmp/*runner*.py /tmp/*check*.py /tmp/*prompt*.txt /tmp/*traj*.json /tmp/harbor-work /tmp/loop-* /tmp/overnight/* ~/projects/nixos-ai/scripts/overnight-24-09/ ~/projects/nixos-ai/scripts/*.py (harness/bench) ~/projects/nixos-ai/docs/audit/CYCLE-*.md ~/projects/nixos-ai/docs/benchmarks/ ~/projects/nixos-ai/modules/ai/jarvis/tests/test_*.py (só listar nomes+qtd) ~/.cache/terminal-bench. Para cada item: path, o que é (1 linha), tamanho/linhas, status (ativo vs lixo vs promovido). Entregue: tabela densa + lista do que é duplicado/órfão + proposta de estrutura consolidada (o que vai p/ repo, o que arquiva, o que apaga). NÃO apague nada, NÃO rode nada.

---

## · ?

Inventário só-leitura (nada executado, nada apagado). Tamanhos via `ls/wc/du/head` apenas.

# 1. Tabela densa

## /tmp/l8* — 232 entradas (família L8 intrusion-detection, 19–25/09)

| Path | O que é (1 linha) | Tam/linhas | Status |
|---|---|---|---|
| `/tmp/l8a1`, `l8a2`, `l8a3` + `l8a2.jsonl`/`l8a3.jsonl`/`*.err` | runs A (tentativas iniciais, jsonl=transcripts) | 52K/44K; jsonl 64KB/92KB, err 0B | **lixo** (superado por b–u) |
| `/tmp/l8b1..b6`, `l8c1..c3`, `l8d1..d3`, `l8e1..e3`, `l8f1..f3`, `l8g1..g2`, `l8h1..h3`, `l8j1..j3`, `l8k1..k3`, `l8n1..n3`, `l8o1..o3`, `l8p1..p3`, `l8r1..r3`, `l8s1..s3`, `l8t1..t3`, `l8u1..u3`, `l8q1`, `l8r4`, `l8v`, `l8v1`, `l8v10..v16` + cada `*-state/` | sandboxes de cada tentativa L8 (workdir + state) | cada 30–340B lista; ~190 dirs | **lixo** (só 1–2 viraram report) |
| `/tmp/l8fix2..fix6`, `l8-fix-recheck`, `l8n3b` | dirs de repair/HALT | ~36–100B lista | **lixo** |
| `/tmp/l8qm-gemma|phi|qwen` + `-state` | runs cross-model (gemma/phi/qwen) | pequena | **lixo**, checar antes se citado no `model-ceiling-l8` |
| `/tmp/l8moldtest{,2,3,4}` + `l8mold-det.sh` (1498B) + `l8mold-resp.sh` (399B) | teste de molde detector/response | 4 dirs ~212B lista | **lixo** |
| `/tmp/l8apex/` (`alert.json`, `report.json`, `intrusion_detector.sh`, `response.sh`, `rules/`, `logs/`, `incident_*`) | run apex consolidado | 52K | **lixo / candidato a arquivar 1 exemplar** |
| `/tmp/l8donk/`, `/tmp/l8qwen/` (`intrusion_detector.sh`, `response.sh`, `rules/`, `logs/`) | runs avulsos (donk; qwen 25/09) | pequena | **lixo** |
| `/tmp/l8-prompt.txt` (920B) vs `/tmp/l8_prompt.txt` (659B) | prompt canônico vs variante curta | <1KB | **lixo em /tmp; promovido se = L9-SPEC** |
| `/tmp/l8arch/det/env/fool/fv/hyb/kaz/m1/m2/m3/pal/pobre/r/val/v/zoro-prompt.txt` + `l8doctrine.txt` | 16 variantes de prompt (arch 26KB, env 27KB, val 26KB, doctrine 24KB são as grandes) | total ~148KB | **lixo (manter só as citadas em CYCLE-8/model-ceiling)** |
| `/tmp/l8_decomp.py` (233 lin) + `/tmp/l8-decomp-log.json` | CONTROL B: decomposição forçada 1 estágio=1 Agent | 10KB | **lixo / promover se virar doc** |
| `/tmp/l8hard-check.py` (55) `/tmp/l8r-check.py` `/tmp/l8v-check.py` (17) `/tmp/l8_world.py` (23) `/tmp/l8_world_check.py` (19) + `/tmp/l8v-api.jsonl` | verificadores de mundo do L8 | cada <3KB | **lixo; lógica canônica já está em `scripts/ux_world.py`** |
| `/tmp/l8qwen-run.py` (28) `/tmp/l8qwen-srv.sh` `/tmp/l8qwen-server.log` (14KB) `/tmp/l8qwen-traj.json` (4.5KB) `/tmp/l8qwen-run.log` (59B) | one-off Qwen 25/09 | pequena | **lixo** |

## /tmp/l9* — 37 entradas

| Path | O que é | Tam | Status |
|---|---|---|---|
| `/tmp/l9`, `l9-base-0..2`, `l9repo`, `l9repo-base-0..2` | sandboxes L9 fix-script (base vs repo) | 40K/4KB | **lixo** |
| `/tmp/l9-crash-0..4`, `l9-hunt-0..5`, `l9-hunt2-0..3`, `l9-dbg`, `l9-dbg-t`, `l9-forense`, `l9-run-0..2`, `l9-write-0..2`, `l9-werr{,2,3}` | runs crash/hunt/dbg/write do L9 | pequena | **lixo** |
| `/tmp/l9_prompt.txt` (143B) / `/tmp/l9_world.py` (13 lin) | prompt + verificador L9 | bytes | **promovido (espelho em `docs/benchmarks/L9-SPEC.md`); cópia /tmp=lixo** |

## /tmp/parity* + runner/check/prompt/traj

| Path | O que é | Tam | Status |
|---|---|---|---|
| `/tmp/parity.py` (108 lin) | harness paridade L: LOCAL vs API + salva JSON | ~108 lin | **lixo Ativo? — único harness parity legível; CANDIDATO A PROMOVER p/ `scripts/`** |
| `/tmp/parity_runner.py` (29) `/tmp/parity_real_runner.py` (22) `/tmp/parity_local_runner.py` (22) `/tmp/parity_run.py` (22) | shims `chdir(argv[1])` p/ workers | bytes | **lixo (3× quase idênticos, só batch usa)** |
| `/tmp/parity-batch-2026-09-19/` (5 tasks + `results.json`) | batch 19/09: csv-to-parquet, fix-permissions, heterogeneous-dates, intrusion-detection, sqlite-db-truncate | 96K | **promovido (resultado em `docs/benchmarks/harness-scores/2026-09-19-parity-batch.json`); dir /tmp=lixo** |
| `/tmp/parity-real/` (`L1-hello-file`) | fixture mínima parity real | 16K | **lixo** |
| `/tmp/runner_real.py` (318 lin) | runner paridade REAL L1–L8 simulando usuário | 318 lin | **lixo / avaliar promoção (maior runner em /tmp)** |
| `/tmp/test_runner.py` (15 lin) | smoke do KaraokeTUI (outro projeto!) | 15 lin | **órfão (karaok), lixo aqui** |
| `/tmp/*check*.py` (18): `check_api/devs2/finale/guide/lrclib/mic_dev/mic_devices/pick/stems/tui/wav` + `cdp-check`, `en-check`, `f0check` | 12× checks karaok + misc | cada <2KB | **órfãos karaok / lixo neste contexto** |
| `/tmp/*prompt*.txt` (22): `l6`, `l7`, 16× `l8*`, `l9`, `repl-system-prompt.txt` | prompts L6/L7/L8/L9 + system prompt REPL | 148KB total | **lixo; curadoria já em CYCLE-*/benchmarks** |
| `/tmp/l8qwen-traj.json` (único `*traj*.json`) | traj do one-off qwen | 4.5KB | **lixo** |

## /tmp/harbor-work, harbor-env, loop, overnight

| Path | O que é | Tam | Status |
|---|---|---|---|
| `/tmp/harbor-work/` (`bytecopy-task/`, `dataset.toml`, `jarvis_adapter.py`, `jobs/6×2026-09-21`, `README`) | checkout Harbor + adapter jarvis + 6 job-runs | 528K | **semi-ativo (único adapter+evidência Harbor fora do repo); PROMOVER adapter+1 job)** |
| `/tmp/harbor-env/` (venv) | venv do harbor | grande (venv) | **lixo (recriável)** |
| `/tmp/loop-check.txt` | flag vazia do loop | 19B, 0 lin | **lixo** |
| `/tmp/overnight/` — 219 arqs, 14MB | acúmulo overnight: `overnight.py` (110 lin, fila L9+lesson/kb-regression/DPO), `LOOP-MUSE.md/QUEUE/STATE`, `LOOP-PROMPT.md`, `MORNING-REPORT*.md`, `CLAIMS.md`, `matrix.sh/log/json` (bonsai/strong/ptbr), `bench-ik35*.sh/log/jsonl` + `bench-qwen4b*.sh/log` + `qwen4b-*.jsonl`, `eval-aligned/uncensored/ab*`, `harbor-easy/med/hard-v1..v6.json+logs`, `loop-bonsai-20260925-*` (~150 JSONs pfull/plean/pminimal 11:56–13:57), `ocr_*.txt`, `ocr_task.py`, `prompt-ab*`, `rebuild*.log`, `moe-*.log`, `fullsuite.log`, `disk-report.txt` | 14MB | **lixo ativo (fonte bruta); curadoria = `overnight-24-09/` + `harness-scores/` + CYCLE-9)** |

## Repo (já em git)

| Path | O que é | Tam | Status |
|---|---|---|---|
| `nixos-ai/scripts/overnight-24-09/` — 113 arqs | curadoria 24–25/09: CLAIMS, eval-*-claims, harbor-*{easy,med,hard}-v{1,2,5,6}, chain27.log, ik-vs-upstream.log, loop-bonsai 11:56–13:48 | 624K | **ATIVO/PROMOVIDO (fonte canônica do overnight)** |
| `nixos-ai/scripts/*.py` — 18 arqs, 3666 lin | bench-final(155, sweep llama-server); eval-judge(132)/eval-model(300); harness-suite(246, E2E dev); memory-arena-lite(245); moe-profiler(430); ncmoe-sweep(505); vram-split-sweep(295); ux-autonomy(199, P0 20 tasks)/ux_driver(139, PTY)/ux-repl-session(124)/ux-suite(178)/ux_world(98); utils: corpus_inventory(169), fetch-resume(69), ingest_books(119), read_chatgpt(154), reindex_code(109) | 3666 lin | **ATIVO (harness/bench oficial)** |
| `nixos-ai/docs/audit/CYCLE-*.md` — 7 arqs | CYCLE-4(35)+5(31)+6(20)+7(17)+8(22)+9-PLAN(39)+9-REPORT(45) | 209 lin | **ATIVO (relatórios ciclos L)** |
| `nixos-ai/docs/benchmarks/` — 14 md raiz (1803 lin) + `harness-scores/`14 JSON + `results/`8 dirs | specs+MATRIZES (BENCHMARK/MODEL-HARNESS/INDEX/README/L9-SPEC/knowledge-spec/ncmoe-sweep/h1_h2_h3/bonsai-vs-qwen/flag-sweep/gpu-moe-fix/model-ceiling-l8/performance-audit/KNOWLEDGE-RESULTS) + série scores 16–19/09 + baselines 26/08 (baseline/ncmoe35/ehs25) + knowledge-e2e 19/09 | ~56K scores + mds | **ATIVO (benchmark canônico)** |
| `nixos-ai/modules/ai/jarvis/tests/test_*.py` — **103 arqs, 24219 lin** | famílias: nightwatch×6, eval/judge×4 (eval_harness/judge/rag/judge), harness_e2e/longrun_e2e/platform_e2e/mcp_tools_e2e, ux/devtools×3, rag/books×8 (rag/diversify/manifest/crypto/book_rag/book_tools/legacy_index), memory/consolidate/lesson_lint/context_drift/p3/p5/p7, agent/voice/audiobook×3/wakeword/vision/handoff/skills/router/model_routing/policy/llm×2/llm_backend/mcp×4/safety×5/security/validator/regression/property/fuzz/bulldozer etc. (listagem completa omitida: 103 nomes; total 24219 lin) | 24219 lin | **ATIVO (suite oficial 1105 testes)** |
| `~/.cache/terminal-bench/` | upstream terminal-bench-core 0.1.1 (datasets TB) | 36M | **ATIVO-externo (cache, não artefato próprio; não versionar)** |

# 2. Duplicados / órfãos

1. **Parity shims triplicados**: `parity_runner`≈`parity_real_runner`≈`parity_local_runner` (22–29 lin, só mudam de nome).
2. **Parity promovido 2×**: `/tmp/parity-batch-*/results.json` → `harness-scores/2026-09-19-parity-batch.json`; `bench_parity_batch.py` (/tmp, 158 lin) é o gerador órfão.
3. **Overnight duplicado**: `/tmp/overnight/loop-bonsai-*` + `harbor-*-v1..v6` + `CLAIMS` ≈ cópia crua do que foi curado em `scripts/overnight-24-09/` (113 dos 219 arqs). `/tmp` tem o resto (logs rebuild/moe/matrix, `*-v3/v4`, eval brutos).
4. **L8 prompts inflados**: 16 variantes (`arch/env/val/doctrine` ~24–27KB cada) + sandboxes ~200 dirs p/ 1–2 conclusões (CYCLE-8/model-ceiling). `l8-prompt` vs `l8_prompt` = dupla canônica curta.
5. **Verificadores L8 triplos**: `l8_world.py`/`l8_world_check.py`/`l8hard/r/v-check` ⊂ `scripts/ux_world.py` (canônico).
6. **Órfãos karaok em /tmp**: `test_runner.py` + 12 `check_*.py` (mic/wav/stems/tui/guide…) pertencem ao `karaok/`, não ao JARVIS.
7. **Vazios/zero-byte**: `l8a2.err`, `l8a3.err`, `eval-l8-api.err`, `eval-l9-api.err`, `loop-check.txt` (19B).
8. **One-offs 25/09**: `l8qwen-{run,srv,traj,logs}` + `eval-l8-now.json`, `eval-l8-local.msgs.json`.
9. **`harbor-env/`** = venv recriável, não evidência.
10. **Fora do escopo mas lixo dominante em /tmp**: ~500 `incident_*` + ~500 `jarvis_cmd_*.wav` + `cdp-*.py` (~30) + `bench-srv-*.log` — não pedidos, mas são o volume real do /tmp.

# 3. Proposta consolidada (só proposta, nada feito)

```
nixos-ai/
  scripts/
    bench/            # mover: bench-final, ncmoe-sweep, vram-split-sweep, moe-profiler (de scripts/*.py)
    harness/          # mover: harness-suite, ux-autonomy/suite/driver/repl-session/ux_world, eval-judge/eval-model, memory-arena-lite
    utils/            # ficar: corpus_inventory, fetch-resume, ingest_books, read_chatgpt, reindex_code
    overnight-24-09/  # MANTER como está (curadoria canônica) + acrescentar MORNING-REPORT*.md e LOOP-*.md do /tmp/overnight
    parity/           # NOVO: parity.py + runner_real.py (avaliar fusão) + results.json canônico
  docs/
    benchmarks/       # MANTER; acrescentar model-ceiling-l8 + referência ao parity/ ; harness-scores/ continua série temporal
    audit/CYCLE-*.md  # MANTER
  modules/ai/jarvis/tests/ # MANTER (103 arqs); nada a mover
  archive/            # NOVO (ou docs/archive/): 1 exemplar l8apex/ + 1 prompt L8 canônico + l8_decomp.py + harbor adapter+1 job + 1 loop-bonsai pfull/plean/pminimal
```

| Ação | O quê |
|---|---|
| **Vai p/ repo** | `parity.py` + `runner_real.py` (fundidos em `scripts/parity/`); `jarvis_adapter.py` + 1 job exemplar do harbor-work; `LOOP-MUSE*.md` + `MORNING-REPORT*.md` + `CLAIMS.md` do /tmp/overnight → `overnight-24-09/`; 1 prompt L8 canônico + `l8_decomp.py` → `archive/` com referência no CYCLE-8 |
| **Arquiva (fora do git quente)** | 1 tarball `/tmp/l8*` representativo (apex + 1 run por letra), 1 tarball `/tmp/overnight` bruto, 1 tarball harbor jobs — guardar em cold storage, não no repo |
| **Apaga (após confirmar curadoria)** | todo o resto de `/tmp/l8*`, `/tmp/l9*`, shims parity duplicados, `*check*.py` karaok em /tmp, prompts variantes não citadas, `harbor-env/`, `loop-check.txt`, `*.err` zerados, `l8qwen-*`, `eval-l*-local/api` brutos, `bench-srv-*.log`, `incident_*`, `jarvis_cmd_*.wav` |

Nada foi executado nem apagado neste inventário.

---

