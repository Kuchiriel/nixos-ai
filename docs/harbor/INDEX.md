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

### Budget derivado (30/09) — o dono tinha razão
`_ctx_derived_max_tokens` (ctx//12, piso) existe desde 19/09 para
exatamente isto. O nightwatch usava **1024 hardcoded**; meu "fix"
de 4096 hardcoded era o **mesmo buraco**. Grammar-limited
`response_format` garante JSON **válido**, não JSON **ilimitado** —
3 arquivos × 4000 chars + hunks estoura qualquer teto pequeno, e a
resposta morre no meio de uma string.

Corrigido sem número mágico: helper morou em
`core/context_budget.py` (módulo **neutro** — o nightwatch não pode
importar `core.agent`, fronteira do supervisor), `agent.py`
re-exporta, patcher usa `max(4096, ctx//12)` do registry e **loga o
valor** (auditável). `test_supervisor_does_not_own_the_loop` pegou a
import errada na primeira tentativa.

**Regra:** qualquer consumidor novo de token budget **herda** o
helper. Literal de tamanho fora do `models.nix` é bug por construção.

## Nightwatch — diagnóstico CORRIGIDO (30/09, verificação antes de agir)

O sumário da sessão anterior dizia que a falha do nightwatch era
**"`old_text` não casa com o arquivo real"**. **Estava errado.** Li o
log real antes de mexer — e era a 4ª vez que meu sumário ia me levar
a consertar a camada errada.

### O que o log mostra de verdade (`nw2.log`)
- `rag.py` → `Validation failed`, `2 passed, 1 failed, 1 skipped`
  (o patch APLICA; um teste quebra).
- `hackmd.py` → `Write failed`, `Syntax error: line 179: unterminated
  string` (o `safe_editor` barra — **comportamento correto**).
- Run 05:16 → `Syntax error: line 17: leading zeros` (mesma classe).

**Não é falha de apply/patcher.** O `safe_editor` fazendo o que deve:
barre sintaxe quebrada antes de corromper o arquivo.

### Causa raiz: o discovery gera lixo
`discover_docs` criava task de **qualquer** match de `TODO|FIXME|HACK`.
As 5 tasks da noite foram:
| Task | Por que é lixo |
|---|---|
| `security.py` "TODOS os paths" | `TODOS` (pt) casa dentro, sem boundary |
| `agent.py` "TODOS os .sh/.py" | idem |
| `devtools.py` "Troca TODOS" | idem |
| `hackmd.py` "HACKMD_TOOLS" | `HACK` casa no **nome do serviço** |
| `completion.py` `"TS","TBD","TODO"` | placeholder em lista de strings |

Feed de lixo → modelo inventa patch → quebra sintaxe → 6 falhas, 0
commits, 16 min. E a culpa quase caiu no patcher (lição 6: o nightwatch
é o **canário do harness**, e o canário apontou o gerador, não o patch).

### Correção (commit `1b38a41`)
`grep -E '\b(TODO|FIXME|HACK)\s*:'` — só **marcador acionável**
(dois-pontos = "isto é tarefa", não coincidência de substring).
- `discover_docs`: 5 de lixo → **0** (não há `TODO:` real no repo)
- fila total: 8 tasks **reais** (missao 5, dead_code, git_hygiene,
  performance) em vez de 5 de ruído que sempre falhavam.

**Não mexi no `apply_hunk`/`patcher`** — eles estão certos. A lição
mais cara da noite: *verificar o log real antes de agir*.

### Terceira camada + veredito (30/09, run pós-rebuild)

Run pós-rebuild: `Patch failed`×3 = **`No readable target files`**.
Causa: geradores alimentavam `target_path` com **descrição em prosa**,
não caminho (`Todos os módulos que usam...`, `` `AGENTS.md`, `HANDOFF.md` ``,
`core/`). `_read_file_for_llm`→ERROR→virava CREATE→modelo criava
arquivo chamado "Todos os módulos..."→falhava. 3 tentativas×~80s por task.

**Fix** (`2c78ef5`): `_target_is_actionable()` — target só é patch se for
**arquivo real** ou path limpo de CREATE (sem prosa/espaço/vírgula,
extensão de código). Diretório/prosa/backtick = não acionável.
`execute_task` skip com motivo em vez de retry cego.

**Verificação end-to-end:** run nova **2m55s** (era 15m58s), tasks
puladas com honestidade, 0 patch-garbage, `Deactivated successfully`.

### 🔴 Achado arquitetural honesto
As 8 tasks do discovery **scriptado são de REVIEW** ("586 functions",
"Models.nix profiles", "Systemd target topology") — **0 acionáveis** como
patch. Não é bug do guard: o discovery scriptado gera *observação*
("olha isso"), não *patch* ("mexe neste arquivo"). O guard está certo em
pular. Trabalho acionável tem que vir do **discovery por LLM com target
concreto** (LLM devolvendo `target_files` com path real), ou os geradores
precisam evoluir pra emitir path de arquivo em vez de prosa.

**Pendências pro nightwatch virar daemon confiável:**
1. **MoE não auto-sobe no contexto do serviço** — o `sudo systemctl start
   llama-cpp-ik` do harness não dispara (só funcionou q eu iniciei na mão),
   e o nightwatch fica em sleep-loop esperando :8084. Corrigir: unit
   com `Wants=llama-cpp-ik` ou `nsenter`/polkit sem prompt.
2. **Discovery por LLM precisa emitir target concreto** (o único caminho
   pra task realmente patchável).
3. Timer segue **desabilitado** (decisão do dono 16/09) — decisão nova
   depende de (1) e (2), senão a run só queima GPU em discovery e skip.

### ✅ Ciclo do MoE 100% no systemd (30/09, fim da pendência 1)

A lista de pendências tinha "MoE não auto-sobe no serviço". **Resolvido
— e a raiz era mais profunda que PATH.** Diagnóstico completo:

1. O `sudo` do PATH do serviço (`/run/current-system/sw/bin`) é symlink
   pro binário do **store, sem setuid** → morria com "deve ter bit
   setuid". Wrapper setuid vive em `/run/wrappers/bin`.
2. `NoNewPrivileges=yes` + `RestrictSUIDSGID=true` no unit → **o kernel
   bloqueia escalada setuid**, então `sudo` é *estruturalmente
   impossível* no serviço (rc=1, "sem novos privilégios"). Não era PATH,
   era o sandbox (que é proposital).
3. `sudo` com `capture_output` sem checar rc **engolia o erro** → o
   nightwatch dormia 30min achando que o MoE subia.

**Correção (arquitetural, não remendo):** quem tem privilégio é o
systemd, então ele gerencia o ciclo:
- `Wants=`/`After=` llama-cpp-ik no nightwatch.service → systemd sobe o
  MoE (Type=simple; o harness só espera :8084 healthy).
- `ExecStopPost = "+/bin/sh -c 'systemctl stop llama-cpp-ik; systemctl
  start llama-cpp-server'"` → o `+` roda com root (senão herda
  User=nixos → Access denied). Devolve a máquina pós-run: MoE para,
  router volta. ExecStart segue User=nixos, sandbox intacto.
- `ensure_strong_llm()`: se a unidade já está activating (systemd puxou),
  pula o gate de RAM (que dispararia DEFER espúrio durante o load de
  16GB do 35B) e só espera healthy.
- harness: restore best-effort sem privilégio; `_sudo_systemctl` fica
  como fallback pra run manual (fora do timer/sandbox).

**Verificado end-to-end (tudo DOWN → run):** systemd sobe MoE+router,
run executa, ExecStopPost devolve. Final: **MoE inactive, router
active**, `Deactivated successfully`, zero erro no log.

**Lição que vale mais que o fix:** o hardening do serviço (o "sudo não
funciona") não era o obstáculo — era o *sinal*. A solução não foi
contornar o sandbox, foi **dar o trabalho a quem tem o privilégio**
(systemd). Cegar o erro com `capture_output` foi o que escondeu o bug
por um dia inteiro.

### ✅ Fechada a 4a camada: LLM discovery emite target_files REAIS (30/09)

Falta (2) da lista — "o discovery por LLM precisa emitir target concreto"
— era **o único caminho pra task realmente patchável**. Fechado:

- `_normalize_target()`: tira crase/aspas/vírgula, absoluto→relativo ao
  root (o que o patch loop resolve).
- `_resolve_llm_targets()`: exige arquivo **EXISTENTE** (patch), com
  fallback por basename (`agent.py`→caminho completo). Path inventado é
  **descartado**. NÃO reusa `_target_is_actionable` de propósito: ela
  aceita path inexistente como CREATE, e isso faria o modelo criar
  arquivo que ninguém pediu — discovery é "melhorar o que existe".
- prompt: entrega ao LLM a lista REAL de arquivos acionáveis (relativos)
  e manda citar exatamente dela (antes: só 15 absolutos → chutava).
- task dict sem alvo acionável não entra na fila.

**Verificado com o LLM real (bonsai, filtro do dia):** 5 tasks, todas
com target validado e resolúvel (`archive/core/agent_loop.py`, …).
Nada de path inventado, nada de prosa.

Bug que meu PRÓPRIO teste pegou antes do commit: o path inventado
`.py` passava como CREATE válido. Segundo a lição (1): verifier/teste
antes de confiar no código — funcionou.

### 🔓 O que destrava: nightwatch pode SE AUTO-CORRIGIR
Com patch loop recebendo target real, o ciclo fecha:
**task válida → patch aplica → teste roda → feedback real → lição vira
aprendizado.** É o loop do RHO (arXiv 2606.06324) que faltava. Ainda
falta o harness *usar* o feedback (hoje ele só grava lição no
AGENTS.md), mas a pre-condição (patch aplicável) está resolvida.
