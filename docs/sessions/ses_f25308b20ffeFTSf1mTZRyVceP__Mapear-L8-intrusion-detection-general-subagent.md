# Mapear L8 intrusion-detection (@general subagent)

- **sessão:** `ses_f25308b20ffeFTSf1mTZRyVceP`
- **quando:** 2026-09-25 23:03 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 26 (exportadas: 2)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

No repo /home/nixos/projects/nixos-ai e memória do projeto: mapeie TUDO sobre o desafio "L8" (intrusion-detection: detector.sh + response.sh + detection_rules.json + auth.log/http.log, WORLD CHECK). Encontre: (1) definição exata da tarefa e script de verificação (onde estão? /tmp foi limpo?); (2) todos os relatórios CYCLE-*-REPORT.md e FINAL-EMPIRICAL-STATE.md — extraia a taxonomia das falhas do bonsai no L8 (b1-b6, 0/63, tese rainha, mold-clobber, poison, etc.); (3) L1-L7: o que cada um testava e que o bonsai passou; (4) L9: estado; (5) procedimento exato p/ rodar o L8 hoje (comando, harness, modelo). Retorne um resumo denso e terse com paths exatos e o procedimento de run. NÃO rode benches, NÃO pare serviços, só pesquisa.

---

## · ?

# L8 — mapa completo (só pesquisa, nada rodado)

## 1. Definição exata + verificação — /tmp INTACTO (não foi limpo)

Origem: task `intrusion-detection` do terminal-bench (`~/.cache/terminal-bench/terminal-bench-core/0.1.1/intrusion-detection/task.yaml`). Fixture: `logs/auth.log` (14 linhas) + `logs/http.log` (14 linhas) + `rules/detection_rules.json` (4 regras: SSH-BRUTE-FORCE `Failed password for` thr 5/high; WEB-SCAN `GET /admin|/phpmyadmin|/wp-admin|/manager/html|/.env|/config.php` thr 3/medium; INVALID-USER thr 2/low; SUDO-COMMAND thr 1/info). IP-alvo do check: `45.32.67.89`.

- Prompt original (paths `/app/...`): `/tmp/l8-prompt.txt` (1 linha; causa raiz de 7x `/app` sem `list_directory` em 19/09)
- Prompt atual **variante CWD** (mesmo p/ local e API): `/tmp/l8v-prompt.txt` (36 linhas, schemas `alert.json`/`report.json`, `response.sh <IP>` → `incident_<IP>_<timestamp>.txt`)
- Check original: `/tmp/l8v-check.py` — ambos `.sh` existem+exec, detector roda rc=0, algum `*alert*/*report*.json` parseia, response gera incident c/ IP + `(Failed password|GET /admin|GET /phpmyadmin)` → `WORLD OK`
- Check semântico/hard: `/tmp/l8hard-check.py` — + IDs ∈ regras, `matches` int>0, IPs válidos, `statistics` não-vazio, **PLACEHOLDERS banidos** (`rule_id, severity_level, TS, TODO, placeholder, sample, example, <IP>, <timestamp>, xxx`), timestamp não-vazio no nome do incident → `WORLD OK (hard)`
- Mundo de referência copiado de: `/tmp/eval-l8-local/{logs,rules}` (usado como `ref` por todos os setups)
- Série b `b1..b6`: `/tmp/l8b{1..6}/{logs,rules,traj.json}`; demais batches: `/tmp/l8{a,c,d,e,f,g,h,j,k,m,n,o,p,q,r,s,t,u,v,w,x,y,z}*`, `/tmp/l8v{1..42}`, `/tmp/l8qm-{gemma,phi,qwen}`, `/tmp/l8apex` (molde âncora)

## 2. Taxonomia das falhas do bonsai no L8 (memória + /tmp)

Placar geral: **local 0/3 STUCK vs API muse-spark-1.3 1/1 world True** (paridade 19/09); **b1–b6 0/6** (20/09, variante CWD, traj `STUCK` ×6 confirmado em `/tmp/l8b?/traj.json`); **fim-de-noite 20/09: local 0/23 vs API 3/3**; **0/54 L8-hard** (`docs/benchmarks/model-ceiling-l8-2026-09-20.md`: 2 VERIFIED, 0 WORLD OK, 1 weak-pass d3 desmascarado); troca de modelo **não resolve** (Gemma L3-interface sem tool_calls; Phi timeout 120s; Qwen STUCK 18t/247s inerte).

- **b1 poison + quote loop** — 3× `write_file` idêntico falhado, `missing: nenhuma tool com sucesso (zero ground truth)`, STUCK 2 turns (`/tmp/eval-l8-local.json`)
- **b2 mold-clobber** — modelo reescreveu `.sh` via molde destruindo conteúdo → **guard anti-mold criado** (+ `mold 0/63` em `docs/architecture/CAPABILITY-MATRIX.md` ID G: JSON/schema 🔴 MODEL-LIMITED)
- **b3 tese rainha confirmada** — detector válido-executável mas **JSON lixo** (scaffold OK, serialização falha; cf. `test_completion.py:746`, `test_agent.py:1846/2575`)
- **b4** response sem deliverable / **b5** falso-positivo de gate matou run (absoluto legítimo no CWD) / **b6** 0/6 fecha
- Batches: **c1–c3 enxame cigarra 0/3** (poison real barrado sem rewrite, bash-bar linha 27, zero writes, 12 guards); **p1–p3 pobre 0/3** (placeholder-gate, guard inputs imutáveis); **w1–w3 0/3** (doubled-quote `"$VAR""`, matches/ips fabricados 123); **x1**: detector 688B rc=0 mas chama `read_file` no shell e cospe `null`
- Molde que **passa**: `/tmp/l8mold-det.sh` + `/tmp/l8mold-resp.sh` (v6: `jq -n --arg/--argjson`, `grep -c`/`date`/`awk NF-2`, zero backslash; `/tmp/l8apex` WORLD OK) — é a âncora determinística, não geração do modelo
- Relatórios: `docs/audit/CYCLE-{4,5,6,7,8,9}-REPORT.md` + `CYCLE-9-PLAN.md` — o "L8 WORLD OK" neles = **âncora apex/molde**, não o bonsai. `FINAL-EMPIRICAL-STATE.md` (cycle 2, 20/09) é sobre RAG/lessons/MCP/entropia; L8 aparece só como "generaliza beyond L8". L9-anatomia: `L9-FAILURE-ANATOMY.md`, `L9-PIVOT-EXPERIMENT.md`, `COMPOSITION-LADDER.md`, `MODEL-BOUNDARY-CYCLE6.md`

## 3. L1–L7 (escada `runner_real.py`, prompts EN; bonsai passou n=1)

| L | ID | teste | resultado |
|---|---|---|---|
| L1 | hello-file | pasta `trabalho/nota.txt` = `paridade-ok` | ✓✓ (local 3s < API 17s) |
| L2 | heterogeneous-dates | avg(high−low) SF = 11.428571428571429 em `avg_temp.txt` | ✓ ambos (API exato 80/7; local exigiu linha `compute via python3 stdlib, nunca awk`) |
| L3 | count-dataset-tokens | contar 4 linhas → `count.txt` | ✓✓ |
| L4 | sanitize-secrets | trocar `AKIAIOSFODNN7EXAMPLE` por `{{API_KEY}}` (tool determinística) | ✓✓ |
| L5 | org-json | 3 CSVs + schema → `organization.json` | ✓✓ (API via GLM; muse sem TTFT) |
| L6 | sqlite-recover | `trunc.db` → `recover.json`, score 8/8 | ✓✓ |
| L7 | csv-parquet | `data.csv` → `data.parquet` idêntico (kvenv pandas) | ✓✓ |

## 4. L9 — estado

**0/12 congelada** (CYCLE-5..9), MODEL-LIMITED (pivot_rate 0.67→0.83 sem mover world; serialização+evidência bytes). Spec: `docs/benchmarks/L9-SPEC.md` (inventory.csv 8 linhas + manual.txt c/ regra QX*, `report.json` + `summary.txt`, checker `l9_check.py`). Runner vivo: `/tmp/l9/run_l9.py` (+ `l9_lib.py`, dirs `/tmp/l9-run-*`, `/tmp/l9-hunt*`). Nota: L9-paridade `fix-permissions` (`/tmp/l9_prompt.txt`, `process_data.sh` 0644→+x) é outra task e passa 1/2 local, 1/1 API — não confundir com a L9-spec.

## 5. Procedimento p/ rodar o L8 hoje (sem rodar agora)

Repo **não tem** runner L8 (`rg L8DIR scripts/` = vazio). Usar os de /tmp:
1. Modelo: **bonsai via router :8080** (default, `modules/ai/models.nix`); nunca outro `llama-server` junto (VRAM 6GB); preflight: 1 completion real (health mente)
2. Preparar dir: `mkdir /tmp/l8run && cp -r /tmp/eval-l8-local/logs /tmp/eval-l8-local/rules /tmp/l8run/`
3. Prompt: `/tmp/l8v-prompt.txt`; env `JARVIS_AGENT_MAX_TURNS=18`, `TIME_S=400` (valores da campanha `model-ceiling-l8`, harness HEAD `94d8ed1+` ≙ repo atual `80e4575`)
4. Run local (molde em `/tmp/parity_real_runner.py`): `nix develop --command python3` + `Agent(Config(), approve=True)` c/ `human_approve=lambda cmd: True`, `os.chdir(taskdir)`, PATH prefixado `/home/nixos/kvenv/bin` (pandas/sqlite p/ L6–L7)
5. Check: `L8DIR=/tmp/l8run python3 /tmp/l8hard-check.py` (rígido) e/ou `/tmp/l8v-check.py` (orig); sucesso = `WORLD OK (hard)`
6. Braço API (comparação): `opencode run --auto -m opencode/muse-spark-1.3-contributor-free --format json` c/ cwd=taskdir (molde em `/tmp/parity.py::run_api`, fallback `nvidia/z-ai/glm-5.3-flash`)
7. ⚠️ **BLOQUEADO até o dono liberar**: `docs/HANDOFF-2026-09-25.md §CONSTRANGIMENTO` — modelo em treino, nenhum bench / restart de serviço / briga por GPU.

---

