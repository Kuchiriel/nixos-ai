# Harbor — calibração externa do harness (índice)

> Entry point p/ "teste harbor" / "evolução de harness". Detalhe de método
> em `.agents/harbor-e-harness.md` (gatilhos: harbor, calibração, trial).

## Placar

| Data | Célula | Modelo | Resultado |
|---|---|---|---|
| 21/09 | A (adapter /tmp) | bonsai | 0/4 |
| 28/09 | A (adapter repo + ponte) | bonsai | ~~2/3~~ → **0/3 honesto** (reward hacking: src sobrescrito; verifiers agora usam sha256 pristino) |
| 28/09 | B (direta :8084) | MoE Qwen3.6-35B | 0/3 (header leak + normalização bytes) |
| 29/09 | C (router :8083) | Qwen3-4B fast | 0/2 (escape-fighting; +1 env flake) |
| 29/09 | task2-bin (binário 0x00-0xFF) | bonsai | 0/4 (sem `cp` não há cópia; flag BINÁRIO adicionada) |
| 29/09 | X-cell (template xLAM obtido) | xLAM-2-8B | incompatível: sem template 400 (parser); com template 500 (output fora do peg-native). Precisa dialeto nativo (formato fc-r + parser de arrays), não tweak. |
| 29/09 | D-cell (byte + bin) | Phi-4-mini-instruct | 0/4 (text-fight, src-overwrite; diag 0.0%) |
| 29/09 | E-cell (Groq, mesmo harness) | gpt-oss-120b | 0/1 (relative-path drift: usa `src.txt`, nunca `/app`; bytes) |
| 29/09 | **F-cell bash-first (tese mini-SWE-agent)** | bonsai | **4/4** (byte+bin; cerca ```bash→shell, chaining liberado no container). Mesmo modelo: 0/25+ → 4/4. |
| 29/09 | F-cell bash-first | Qwen3-4B fast | **3/4** (incl. 1 `cp-executed` real) |
| 29/09 | F-cell bash-first | MoE Qwen3.6 | 0/4 (dialeto próprio `f(path=)`, ignora cerca; 500s frios) |
| 29/09 | task3 extract-line (transferência) | bonsai bash-first | 0/4 (`sed -n 2p` descoberto mas fabricação persiste; guarda write-without-read adicionada) |
| 29/09 | task3 + read-gate bloqueante | bonsai bash-first | 0/2 (gate dispara mas modelo põe leitura-token e fabrica igual — dado negativo; completion container-aware é o próximo candidato) |
| 29/09 | dev loop + prompt | MoE Qwen3.6 | prompt full = 500; `JARVIS_PROMPT_PROFILE=minimal` = sem 500 e com tool calls. Prompt gigante é o gatilho, não o modelo. Fix: `MINIMAL_PROMPT` sem LANG_NAME (KeyError) + `_COMPACT_SYSTEM_TEMPLATE` p/ tiny/small (auto) e `JARVIS_COMPACT_PROMPT=1/0` p/ experimento |
| 29/09 | task3 + grounding + source-readonly | bonsai bash-first | 0/2 (ponte agora conta execs/writes, COMPLETED sem exec → UNVERIFIED, fonte lida é read-only p/ redirect, dica "ONE shell command / never re-type". Gate dispara certo — modelo insiste no clobber em vez de se adaptar: parede de capacidade em transferência exata, não falta de gate) |
| 29/09 | task3 fast tier | Qwen3-4B fast | 0/2 mas técnica perfeita (`head -n2\|tail -n1`) num trial → zerou por FIXTURE quebrada (ver abaixo), não por modelo |
| 29/09 | **task3 fixture fix** | bonsai bash-first | **2/2 (1.0)** — `Dockerfile` usava `printf "\n" a b c` (=4×`\n`, fonte sem conteúdo!). O "muro de capacidade" era bug do instrumento. Lição: validar fixture com `cat` antes de atribuir falha ao modelo |
| 29/09 | infra: VRAM leak | — | servidor efêmero `--alias jarvis-fast :42911` (origem desconhecida, 12:16) segurou 3.2GB VRAM → bonsai 500 "unable to allocate CUDA0". `kill -9` resolveu. TODO: guarda anti-vazamento (pgrep antes de bench/trial) |
| 29/09 | F-cell regressão pós-rebuild | bonsai bash-first | **3/3 (1.0)** — harness intacto |
| 29/09 | task3 fast (fixture fixa) | Qwen3-4B fast | **1/2** — `sed -n 2p A > B` single-command converte (1.0); outro trial fabrica fonte ("as deliverable", 0.0). Série fast em task3: 1/4 |
| 29/09 | task2-bin | bonsai bash-first | **1/2** — `cp` single-command = 1.0; `read_file\|write_file` como shell + touch = 0.0. Padrão geral: transferência num comando só vence, resto perde |
| 29/09 | A/B lean vs minimal (dev, bonsai, piloto n=1) | bonsai | inconclusivo: minimal 4.4s vs lean 17.2s wall, mas NENHUM escreveu o arquivo (RC 0 sem deliverable). Gap: grounding de completion só existe nos trials, não no loop dev |
| 29/09 | ensure multi-serviço | — | **sem evicção cross-service**: bonsai (4.3GB :8080) × fast (2.6GB :8083) não coexistem; ensure falha 300s sem despejar o outro. Dança manual `/models/unload` necessária. TODO: ensure com evicção |
| 29/09 | **ensure com evicção** | — | **`JARVIS_ENSURE_EVICT=1`**: `_evict_peers` despeja residentes de outros endpoints do registry antes do load. Validado ida e volta (bonsai→fast→bonsai). `harbor-lite.sh fast` já exporta. Opt-in (bot não despeja ninguém por padrão) |
| 29/09 | **bateria Lite fixa** | bonsai bash-first | **`scripts/harbor-lite.sh [bonsai\|fast]`**: bytecopy + bin + extract-line. Baseline bonsai **4/5** (bin 2/2, byte 1/1, line 1/2 — sensível, bom p/ regressão) |
| 29/09 | no-tool nudge (dev loop) | bonsai | texto final sem nenhuma tool na sessão ganhava RC 0 direto (A/B lean/minimal). Agora 1 nudge limitado + teste. Q&A em texto segue funcionando |
| 29/09 | **RC honesto + claim rastreia shell** | bonsai | claim-checker rastreia `>`/`cp` do shell; texto final após nudge com evidência e sem sucesso posterior = **RC 1** (validado ao vivo: era RC 0). Reset de attrs por run (bug latente). Série A/B: lean≈minimal p/ bonsai (ambos falham igual), minimal 2-4x mais rápido em wall |
| 29/09 | **lite fast 4/5 (evicção automática)** | Qwen3-4B fast | bin 2/2, byte 1/1, line 1/2 — sem dança manual (ensure+evict). Custo: fast 55-390s wall vs bonsai 2-5s (10-80x). `harbor-lite.sh` restaura bonsai no fim |
| 29/09 | **grounding no REPL + VERIFIED honesto** | — | `dev_once` exibe veredito check_completion + grava no transcript. Verbos imperativo PT cobram deliverable (falso VERIFIED ao vivo corrigido). **conftest sem keys**: cascata Groq/NVIDIA real furava mocks (teste quebrado há dias). Suite: **1405 verdes** |
| 29/09 | **gate por observação (menção≠leitura)** | bonsai bash-first | `_reads` só com observação efetiva (rc 0); flags ignoradas; retry de output próprio permitido. 1/2. Série task3 bonsai total: **5/9 (~55%)**. Falha restante típica: acerta (turn 3) e sobrescreve o próprio output certo (turn 5) — déficit de verificação do modelo, próximo alvo (ritual de read-back) |

## Estratégia por modelo (`scripts/grade-harbor.py`)

Só o MoE descobriu `cp` (escreveu `copy.sh`, nunca executou → `cp-written-only`).
Bonsai/fast/Phi: text-fight, src-overwrite, prosa-only. Nenhum executou `cp`.

## Arquivos

| O quê | Onde |
|---|---|
| Adapter F10 | `modules/ai/jarvis/src/jarvis/runtime/harbor_agent.py` |
| `agent_class` no runtime | `modules/ai/jarvis/src/jarvis/runtime/agent_runtime.py` |
| Testes (mock, sem LLM) | `modules/ai/jarvis/tests/test_harbor_adapter.py` |
| Log de auditoria | `docs/audit/HARBOR-INTEGRATION.md` |
| Guia do agente | `.agents/harbor-e-harness.md` |
| Matriz modelo×harness | `docs/benchmarks/MODEL-HARNESS-MATRIX.md` |
| venv Harbor 0.23.0 | `/tmp/harbor-env` (fora do repo; some no reboot — recriar) |
| Tasks + jobs + evidência | `/tmp/harbor-work` (fora do repo) |

## Comandos (resumo; exato em `.agents/harbor-e-harness.md`)

```bash
nix develop --command python3 -m pytest modules/ai/jarvis/tests/test_harbor_adapter.py -q
source /tmp/harbor-env/ldenv.sh
sg docker -c "/tmp/harbor-env/bin/harbor job start --config /tmp/harbor-work/job-acell.json --job-name <nome>"
```
