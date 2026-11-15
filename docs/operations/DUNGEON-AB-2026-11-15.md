# Dungeon A/B — bonsai vs qwen 4b MTP (15/11/2026)

> Pedido do dono: "Foi feito com bonsai ainda modelo ruim em ptbr e erra muito,
> hoje temos qwen 4b mtp, melhor para isso. Reproduzir teste e analisar
> qualidade do jarvis-dungeon e o jarvis-dungeon-new que seria o a/b que nao
> existe ainda."

## O que existe (medido)

| item | estado |
|---|---|
| `~/projects/jarvis-dungeon` | jogo pygame com A* — **NAO usa LLM** (src/dungeon/*.py so tem render/map/entities/game) |
| o "dungeon" do legado | harness de AGENTES dentro do jogo: `~/projects/team/` (`dev-bot.sh` -> `dev.py autopilot` + harness SafeEditor/Evaluator/Checkpoint/team_bridge) |
| relatórios do A/B original | `~/projects/team/reports/*dungeon*.md` (11 arquivos) |
| veredito com **bonsai** | **8 FAIL em 10** (7 e 10/out) + 2 PASS depois (validate-dungeon-001, dungeon-002) |
| onde parou | `~/projects/team/dev/` está **VAZIO** e o `dev.py` não existe mais (só sobraram os units em `~/.local/state/jarvis/legacy-units-2026-11-12/`) |

### O que dava errado (do relatório `2026-10-07-2146-dungeon-010.md`)

O agente (bonsai) fazia plano de 5 etapas com dependências, lia `src/dungeon/render.py`,
mas o passo 1 foi判 **"assumir que o arquivo existe"** em vez de ler — o
avaliador reprovou. Ou seja: **plano certo, execução shaky, e o raciocínio em
inglês** (o bonsai é fraco em PT-BR — a complaint do dono).

## A/B que falta (jarvis-dungeon-new)

Mesma tarefa, dois modelos, checker **fixado** (regra do video: escrever o
checker ANTES e nao mexer depois):

| item | decisao |
|---|---|
| modelo A | bonsai (router :8080) — a linha de base |
| modelo B | **qwen 4b MTP** (directServer :8092, duplex) — o candidato do dono |
| checker | 4 pontos do video: (1) producao igual? (2) sandbox separado? (3) sandbox funciona? (4) o script corrige a producao? |
| sandbox | worktree por lane (a casa ja tem a regra; falta o checker) |
| prompt | o mesmo dos 7/out: "add a settings menu toggle in src/dungeon/render.py" + plano de 5 etapas com deps + avaliador que exige LER o arquivo antes deassume |
| veredito | PASS/FAIL por modelo + onde falhou (passo) |

**Por que o MTP e o candidato certo (medido no video)**: o video mediu que
time com especialista SEM o pedido original passa MENOS de 3 de 8, enquanto o
especialista sozinho passa 6 de 8. Nosso wake ja anexa o
[PEDIDO ORIGINAL] (fix de hoje). E o planner tem de ser forte: no video, 4B
planejador deu 2/4 e 35B deu 4/4.

## Modelos citados no transcript x o NOSSO hardware

| modelo | param | video | cabe aqui? (6 GB VRAM, 11 GB RAM livres) |
|---|---|---|---|
| TMax-4B (AI2) | 4B | 27% do terminal-bench | **SIM** — GGUF Q4_K_M 2,7 GB (registrado no `models.nix`) |
| TMax-9B / 27B | 9/27B | 9B = mais forte <10B | 9B Q4 ~5,5 GB: apertado, 27B não |
| Carbon-X (HF) | 15B | ~1 ponto do GPT-6.1 SOL em DNA | **NAO** — repo oficial e safetensors (29,6 GB), sem GGUF oficial |
| Vibe Thinker | 3B | matematica dePreheat > Gemini 3 Pro | SIM (~2 GB) — a avaliar |
| Teley OCR | 1B | documentos > Gemini 3 Pro | SIM (~1 GB) — util p/ o corpus |
| Kimi K3 | grande | +11 pontos ao consultar Carbon-X | via API (openrouter), nao local |

## Hot swap (o que a casa NAO tem)

Hoje o router so serve `bonsai` e o MTP roda em directServer :8092 (5,5 GB de
VRAM). Trocar = **parar um para subir o outro** (a VRAM esta cheia com o MTP).
Falta: (a) registrar o TMax como profile servivel; (b) um `llama-swap` que
troca o preset em idle (o `models.nix` ja tem `extraProfiles` para o `/model
jarvis-raw*`, mas o router so carrega o bonsai).

## Fila

1. `dungeon-ab.sh`: roda a MESMA task com A e B, grava veredito + o passo que falhou.
2. `jarvis-dungeon-new`: harness novo (o legado sumiu) — 5 etapas com deps, sandbox por worktree, checker de 4 pontos fixado antes.
3. Medir: quantos passos o MTP acerta vs o bonsai, em PT-BR.
4. Hot swap: perfil do TMax no router + troca em idle.
