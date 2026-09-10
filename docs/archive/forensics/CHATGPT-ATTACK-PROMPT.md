# PROMPT CIRÚRGICO p/ ChatGPT — ataque ao gap de autonomia do JARVIS
# (cole no ChatGPT; ele devolve o plano de ataque priorizado)

Você é um arquiteto de sistemas agentivos. Contexto: NixOS-AI/JARVIS —
assistente de IA 100% local (NixOS, RTX 4050 6GB VRAM, 32GB RAM, llama.cpp,
Qdrant, sem Ollama/Chroma). Diálogo em PT-BR. Leia tudo antes de propor.

## ESTADO VERIFICADO (números reais, sem achismo)

**Arquitetura (implementada, testada, commitada):**
- `models.nix` = source of truth (arquivos fetchurl + profiles + bloco
  `routing` com tiers/capabilities) → gera preset INI do router NATIVO do
  llama-server (`--models-preset`, `--models-max 1`) + registry JSON em
  `/etc/jarvis/model-registry.json`. Sem segundo router, sem ModelManager.
- Tiers: `bonsai` (speed, default, 8B ternário Q2_0 via fork Prism),
  `jarvis-fast` (Qwen3-4B Q4_K_M), `jarvis-strong` (Qwen3.6-35B MoE+mmproj).
- Python: `ModelRegistry` (só carrega/valida) → `select_model()`
  (capabilities HARD, tier soft) → `ensure_model()` idempotente (flock,
  timeouts por fase, identidade via /v1/models, retry em 500-busy) →
  `LLMClient`/backends intactos. Alias `"default"` resolvido pelo registry.
- REPL `dev.py` (21 tools) + `Agent` (loop, validator, loop_detector,
  audit). Voz (wakeword→STT→agent→TTS→waybar). Suite: 1049 passed, 5
  falhas infra conhecidas. `nix flake check` verde.

**Modelos medidos (mesmo harness, temp 0, n=1–5):**
- A/B tool-use n=5 (7 tarefas, scoring AST-lite): Bonsai free 30/35,
  +sysprompt 35/35, constrained 35/35; Qwen3-4B free 35/35, constrained
  20/35; Gemma 3 4B free 0/35, constrained 35/35; Phi-4-mini free 0/35,
  constrained 30/35. Arquivos Gemma/Phi em `~/models/` (fiados no
  models.nix com sha256).
- Suíte 19 tarefas: Bonsai 15.5/19, MoE 16/19, Qwen ~14.5/19, Gemma ~10
  (só texto, zero calls), Phi ~10 (postura de recusa).
- Latência: Bonsai GPU TTFT 0.05s ~60-76 t/s; Qwen CPU 3–30s/tarefa;
  MoE CPU 5–215s; switch router 12s CPU; VRAM Bonsai 3.6GB + embed 0.4GB.

**O ABISMO (protocolo user-fiel: 1 prompt terso, fresh session, zero
ajuda — 12 runs, 0 conclusões):** desiste após 1 erro; Agent default era
cego (só read_file); param-count anulava o fast tier ("tiny" sem tools);
rc=0 na rendição; REPL sem loop detector; Bonsai age-errado, Qwen
trava/loops; especulação sem evidência (T3); NENHUM run com plano
multi-passo espontâneo ou auto-verificação.

**Já corrigido (com teste):** registry vence regex; recovery coach
(candidatos em file-not-found, 1 recovery verificada); LoopDetector no
REPL + rc honesto (stuck); TOOL_USE_DISCIPLINE no Agent+REPL;
Agent(strict_tools) via response_format; thinking plumbing
(chat_template_kwargs nos 3 backends + stream + fallback reasoning);
_Qwen3-4B validado no fork Prism (CPU)._

**Leads de pesquisa (não executados):** xLAM-2-8B Q4_K_M (~4.9GB, BFCL
SOTA, GGUF via tensorblock) como executor fast; patterns Anthropic
(orquestrador-workers, evaluator-optimizer, effort-scaling, tool-design);
plano-then-executa com MoE planejando + small executando; chamadas de
tools em paralelo (loop é serial!); verificação pós-edit forçada.

## O QUE QUERO DE VOCÊ

Um plano de ataque CIRÚRGICO e PRIORIZADO (P0/P1/P2, esforço estimado,
arquivos a tocar, critérios de pronto com métricas, o que NÃO fazer),
para: (1) autonomia real em tarefas de 3–8 passos com modelos 4–8B
locais; (2) paridade de UX supervisionada com Opencode/Roo/Cline;
(3) aproveitar vantagem NixOS (sandbox declarativo, MCP, RAG/vault);
(4) sem trocar engine, sem Ollama/Chroma, sem mexer em Hyper-V/VM,
sem reescrever histórico git, sem mudar default Bonsai silenciosamente.
Responda em PT-BR, denso, sem generalidades. Se alguma premissa acima
parecer errada, diga qual e por quê antes do plano.
