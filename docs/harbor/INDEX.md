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
| 29/09 | **N-cell NVIDIA (deepseek-v4.1-flash)** | DeepSeek v4.1 | **5/5 (100%)**: byte 1/1, bin 2/2, line 2/2. Vencedor faz read-back ritual + `od -c` espontâneo. Infra: `--env-file` p/ vars no worker; `JARVIS_REMOTE_BASE_URL` (não `JARVIS_BASE_URL`) manda no backend remoto; base sem `/v1` (duplica); modelo 0731→410 (usar v4.1-flash). Groq segue instável (payload validado 200 no replay) |
| 29/09 | **R1-distill-7B local** | DeepSeek-R1-Distill-Qwen-7B Q4_K_M | **KV cache q4_0 DESTRÓI a saída** (texto lixo repetido); **KV fp16 = raciocínio funcionando**. Sem template de tool-call → `_parse_dsml` não (é outro dialeto): responde em prosa. 4.68GB, roda em VRAM 6GB a 8k ctx, ~5.5GB usado |
| 29/09 | **missão multi-etapas (R1-7B local)** | — | 6 falhas de harness consertadas, ver linhas seguintes. Modelo continua sem entregar: teto de capacidade do distill a Q4, não falta de nudge |
| 29/09 | **parser DSML** | — | DeepSeek-NVIDIA emite XML próprio (barras U+FF5C), não OpenAI calls — 1 trial perdido p/ dialeto. `_parse_dsml_calls` no fallback (command→cmd) + teste. task3 DeepSeek: 1/2 → **2/2** |
| 29/09 | **sandbox declara /app** | — | `environment_block(for_container)` (CWD/host vazavam; DeepSeek vagou em `/home/...` e zerou). Host-wandering: 2+ steps → **0**. Via `_sandbox` no ContainerAgent |

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

## Missão multi-etapas (29/09) — 6 falhas de harness achadas por 1 task

Missão: rodar script que falha → achar a linha de CSV defeituosa →
corrigir o CSV → rodar de novo → escrever o total. Verifier: total
correto **e** CSV original preservado. Fora da caixa do Harbor, porque
o gargalo é o loop do dev REPL, não o adapter.

| # | Falha | Sintoma | Correção |
|---|---|---|---|
| 1 | CWD do host no prompt do trial | modelo explorava `/home/...` dentro do container | `environment_block(for_container=True)` declara `/app` e nega o host |
| 2 | Loop detector antes do parse | 8× mesmo comando, nunca abortava (via `n_tc=0` em toda call de fence) | detector roda **depois** do parse de texto/fence |
| 3 | Recuperação só por texto | warning→change_strategy→warning, ambos ignorados | `ABORT` quando 2 recoveries são ignoradas sem mudar assinatura |
| 4 | `continue` dentro do laço de tool_calls | reiniciava a iteração das calls, não o turno | nudge movido para fora do laço |
| 5 | `sed -i` fora do allowlist | modelo lia o dado, tentava a correção **certa**, era barrado | `sed -i` liberado + **HARD-NEVER** cobre `/nix/store` (brecha que o allowlist novo abriu) |
| 6 | Nudge mandava "olhe o arquivo" | modelo nunca olhava (rodava o mesmo cmd) | nudge **anexa o conteúdo real** do input citado, via `_safe_path` |

Sobreviventes do R1-7B: escalada pra bash-first (funcionou), razão
injetada, nudge de erro repetido, ABORT honesto (parou em vez de
queimar 8 turnos). Ainda assim 0 entrega. **Diagnóstico: teto de
capacidade do distill a Q4 em 8k de contexto**, não falta de nudge —
o modelo tem raciocínio mas não converge. O harness está honesto
nas duas direções: não declara sucesso vazio, e aborta beco.

### O que o R1 provou sobre planning
Raciocínio ≠ convergência. O `reasoning_content` chega (o REPL mostra),
o modelo articula um plano correto em prosa ("identificar a linha,
depois corrigir") — e mesmo assim executa o comando errado 8×. Reasoning
tokens **não** substituem o mecanismo de **forçar novelty de ação**
(que aqui é o ABORT). Planning simulado não é o gargalo; grounding +
variedade de ação são.

## Portão de promoção (29/09) — R1-distill-7B **não** promovido

Modelo só entra no `models.nix` se ganhar do baseline no **mesmo**
harness, mesmas tasks, mesmo container. Lite battery:

| Modelo | byte | bin | line | **total** | miss��o multi-etapa |
|---|---|---|---|---|---|
| bonsai 8B ternary | 1/1 | 2/2 | 1/2 | **4/5** | 0 (nem chega longe) |
| Qwen3-4B fast | 1/1 | 2/2 | 1/2 | **4/5** | 0 |
| R1-distill-7B (local) | 1/1 | 2/2 | **0/2** | **3/5** | 0 |
| DeepSeek-NVIDIA 120B | 1/1 | 2/2 | 2/2 | **5/5** | — |

**R1-7B: 3/5 — abaixo do bonsai. Não promovido.** Modo de falha novo:
erro de sintaxe shell (`python3 -c` com `with` numa linha só) e confusão
de interface (nomes de tool como comando). Contexto **não** era o
limite (3387 tokens em 6 turnos, janela é 8k).

### O experimento que responde "reasoning converte?"

O **MoE local (Qwen3.6-35B, tier reasoning)** na missão multi-etapas:
rodou → leu o CSV com numeração de linha → `str_replace "5;50"→"5,50"`
cirúrgico → rodou de novo → **550 (total correto)**. 5 tool calls,
caminho perfeito. Perdeu **um passo**: encerrou sem escrever
`total.txt`, e o final veio vazio.

Isso é a resposta: **raciocínio converte na decisão; o que faltava era
o harness cobrar o último passo.** Duas correções que vieram disso:
1. final vazio = parada silenciosa (nunca entrava em nudge)
2. parser de zero-width (o tokenizer emitia U+200B após `<` e a
   tool-call Hermes virava prosa — a ação **válida** morria no parser)

O MoE já é `jarvis-strong`; nenhum flag novo, nenhuma promoção
pendente. O R1 fica em `~/models/` como experimento documentado.
