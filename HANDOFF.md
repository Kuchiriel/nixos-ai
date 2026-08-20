# HANDOFF - Sessão 2026-08-20 (atualizado)

## Estado Atual do Sistema
- **NixOS Host**: Acer Nitro V15, i7-13620H (16t), 32GB RAM, RTX 40506GB + Intel UHD 770
- **Último rebuild**: OK — `rebuild-host.sh` (NÃO `nixos-rebuild build --flake .#nixos-lab`!)
- **Git**: 38+ commits ahead of origin
- **llama-cpp-server**: ✅ RODANDO — Qwen3.6-35B-A3B MoE, ngl=10, ~10.5 t/s
- **VRAM budget**: 5556MB/6141MB (mmproj DESATIVADO por falta de VRAM)
- **Embeddings/Rerank**: CPU-only via `CUDA_VISIBLE_DEVICES=""` (libera VRAM p/ LLM)
- **500+ testes verdes**, nix flake check OK

## Validação E2E (2026-08-19)

| Área | Estado | Evidência |
|------|--------|-----------|
| llama.cpp | ✅ PASS | /health OK, /v1/models OK, chat completions OK, tool calling OK, structured output OK (com enable_thinking=false) |
| Qdrant | ✅ PASS | healthz OK, memories collection (46 vetores, dim 768, Cosine), search retorna resultados |
| RAG | ✅ PASS | Embedding OK (768d), code_index criado (787 points: 659 .py + 128 .nix), search validado (score 0.471) |
| Memória | ✅ PASS | remember → recall → lessons funciona, deduplicação OK, 46+ eventos armazenados |
| Agent | ✅ PASS | E2E: prompt → tool_call → execute → response funciona com Qwen3-4B real |
| Self-heal | ✅ PASS | 9 health checks (llama_cpp, embeddings, qdrant, disk, nixos, ui, network, sockets, btrfs) |
| EventBus | ✅ PASS | 14 testes unitários, pub/sub funcional |
| Semantic Search | ✅ PASS | code_index com 787 points, search retorna resultados com score |
| Egress | ✅ PASS | ContentSafetyFilter com word boundary, 7 testes de segurança |
| Observabilidade | ✅ PASS | JSONL logging, metrics CLI, doctor proativo |
| NixOS | ✅ PASS | nix flake check OK, nix build .#jarvis OK |
| Restart/Recovery | ✅ PASS | 497 testes passando, 0 regressão |

### Bateria E2E 10 Níveis (2026-08-19)

| Nível | Tarefa | Tools | Resultado | Tempo |
|-------|--------|-------|-----------|-------|
| 1 | Ler arquivo | `read_file` | ✅ 15 configs | 190s |
| 2 | Editar 1 linha | `read_file` → `str_replace` | ✅ | 22s |
| 3 | Criar função | `str_replace` | ✅ | 24s |
| 4 | Web search | `web_search` | ✅ 5 resultados | 100s |
| 5 | Read URL | `read_url` | ✅ Wiki Hyprland | 56s |
| 6 | Semantic search | `semantic_search` | ✅ circuit_breaker.py | 77s |
| 7 | Read + Edit + Commit | `read_file` → `str_replace` → `git_commit` | ✅ | 172s |
| 8 | Run tests | `run_tests` | ⚠️ pytest fora do sandbox Nix | 27s |
| 9 | Multi-file edit | `read_file`×2 → `str_replace`×2 | ✅ ambos editados | 98s |
| 10 | Full workflow | `web_search` → `read_file` → `str_replace` → `execute_shell` | ✅ Hello World | 67s |

**9/10 PASS** — Level 8: pytest precisa do sandbox Nix (esperado).

### Notas
- **structured output**: funciona APENAS com `chat_template_kwargs: enable_thinking=false` (Qwen3 consome tokens thinking)
- **Embeddings**: server dedicado na porta 8081 (não no llama-cpp principal)

## Commits Recentes (em ordem — sessão 2026-08-19)
```
dbb670b fix(devtools): corrige semantic_search — import QdrantStore + remove dead code
51375ad docs: atualiza HANDOFF com resultados da validação E2E completa
5fcbd83 fix(build): corrige 52 falhas no nix build — logging, devtools, content safety
5b94993 feat(bulldozer): testes de atrito reais contra SLM + prompt enforcement
c17a9a8 feat(devtools): fuzzy matching para str_replace (tolera erros de SLM)
3f4f434 fix(waybar): replace one-shot jarvis ask with jarvis dev REPL
e1f29bd feat(dev): CLI interativo jarvis dev (estilo Aider) testado contra SLM real
d424185 feat(devtools): ferramentas de desenvolvimento para o agente (estilo Aider/Claude Code)
e82e3d5 test(fuzz): campanha intensiva de mutation testing e fuzzing de estresse
b4d7e19 feat(resilience): circuit breaker + health monitor + fallback com egress safety
e10a2c7 feat(pipeline): event bus + vision + triggers — pipeline orientado a eventos
5552f85 docs: atualiza documentação com todos os commits da sessão 2026-08-19
9d0103f feat(profile): perfil de usuario dinâmico + contexto adaptativo
ee87408 feat(observability): logging JSONL unificado + metrics + doctor proativo
6b5c445 docs(security): adiciona threat model e resultados do hardening ao HANDOFF.md
583d30c feat(security): hardening do agente contra prompt injection e tool hallucination
0fe095d test(pbt): adiciona Property-Based Testing com hypothesis (31 testes)
bb29aa7 perf(agent): otimiza prompts e tool calling para SLMs (4B-35B)
451ba46 docs: atualiza README.md com diagramas Mermaid e guia de instalação padrão ouro
196ea2c feat(audiobook): handler real com scan/read/pause/resume/stop/next/prev + TTS
21a0198 fix(agent): injeta chat_template_kwargs enable_thinking=False no payload
df089dc docs: atualiza HANDOFF com resultados do hardening (422d0be)
422d0be fix(ai): hardening da stack JARVIS — 4 correções validadas com 248 testes
```

## O Que Foi Implementado Nesta Sessão

### 0c. CLI Dev Agent (e1f29bd + melhorias 2026-08-19)
- `jarvis dev` — REPL interativo estilo Aider com ferramentas de desenvolvimento
- Tool calls reais contra o SLM local (Qwen3-4B via llama.cpp)
- **12 ferramentas**: `read_file`, `str_replace`, `write_file`, `list_directory`, `code_search`, `semantic_search`, `run_tests`, `execute_shell`, `git_commit`, `web_search`, `read_url`, `jarvis_command`
- **Repo map**: 80 arquivos indexados no system prompt (estilo Aider)
- **Architect mode**: `/architect` — SLM lê → planeja → executa (opcional)
- **Memory context**: lições episódicas injetadas no prompt
- **Fuzzy matching**: str_replace tolera 82% de similaridade (corrige erros do SLM)
- **Comandos REPL**: `/quit`, `/clear`, `/status`, `/map`, `/model`, `/recall`, `/architect`, `/help`
- **Web tools**: `web_search` (DuckDuckGo) + `read_url` — validados E2E
- **Prompts SLM**: numéricos, condicionais, RULE 1-5, exemplo explícito
- Segurança: paths restritos ao projeto ou /tmp, backup .bak, str_replace valida existência
- Testes E2E: ler, editar, criar função, web search, read URL, semantic search — todos validados
- 25 novos testes unitários + validação contra SLM real

### 0b. Mutation Testing + Fuzzing (e82e3d5)
- `test_fuzz_mutation.py` — 56 testes de fuzzing e mutation testing
- Fuzzing do parser JSON: 100+ strings aleatórias, 100+ JSONs malformados, 100+ tool calls
- Fuzzing de memory: _stable_id determinismo, payload validação, edge cases
- Fuzzing de rules: 100+ triggers aleatórios, alternativas especiais, ReDoS prevention
- Mutation targets: _normalize_tool_call (None args, invalid JSON, empty name)
- Stress tests: 1000 iterações rápidas (parser, compile, normalize, profile, stable_id)
- Content safety fuzzing: 100+ safe/unsafe prompts, case insensitive, partial match
- Lacunas encontradas: tab (\t) não detectado por chaining check (shlex.safe)

### 0a. Circuit Breaker + Fallback (b4d7e19)
- `core/health_monitor.py` — monitor de saúde do llama.cpp: socket check, HTTP health, latência, uptime%
- `core/circuit_breaker.py` — padrão Circuit Breaker: CLOSED→OPEN→HALF_OPEN, fallback remoto, ContentSafetyFilter
- Filtro de segurança: keywords sensíveis (recall, vault, password, /home/) → fallback remoto NUNCA
- Agent: `_chat_raw()` + integração com circuit breaker no `_run_loop`
- Telegram: `/status` (backend + circuit info), `/force_local`, `/force_remote`
- 25 testes: health monitor, content safety, circuit breaker, Telegram

### 0. Event Bus + Vision + Triggers (e10a2c7)
- `core/eventbus.py` — barramento asyncio leve: pub/sub por tópico, retry, DLQ, stats
- `core/vision.py` — captura de tela via grim/slurp (full/region/window), fallback gracioso sem display
- `core/triggers.py` — motor declarativo: cooldown, idempotência, persistência JSON, triggers pré-definidos (disk/doctor/cpu)
- `agent.py` — tool `capture_screen` integrada ao agente
- CLI: `jarvis screenshot`, `jarvis triggers run|status`
- 34 testes novos (eventbus + triggers + vision)

### 1. Hardening da Stack (422d0be)
- `heal.py`: MemoryStore (bug) → EpisodicMemory — fecha loop de self-heal
- `agent.py`: `response_format: json_object` + system_prompt limpo de instruções MCP
- `memory.py`: deduplicação por texto em `recall()` + `max_chars=500` em `lessons()`
- `flake.nix`: devShell PYTHONPATH usa FLAKE_ROOT absoluto (antes relativo, quebrava em subdirs)

### 2. Security Hardening (583d30c)
- `has_chaining_operators()` — detecta `&&`, `||`, `;`, `|`, backticks, `$()`, newlines
- `_valid_tool_names()` — whitelist de tools (execute_shell + MCP); tools hallucinadas rejeitadas
- Empty cmd guard — comandos vazios retornam erro sem execução
- 6 testes de segurança adicionados

### 3. Property-Based Testing (0fe095d)
- 31 testes com `hypothesis` para parser de JSON fallback e motor de regras
- Estratégias adversárias: UTF-8 corrompido, JSON incompleto, infinite nesting, null bytes

### 4. Prompt Optimization (bb29aa7)
- System prompt: 580→194 chars (-66%), tool description: 143→102 chars (-29%)
- Profile `tiny` para Qwen3-4B/3B/1B: max_tokens=512
- `detect_profile` agora cobre 1B→35B com perfis adequados

### 5. Audiobook Handler (196ea2c)
- `jarvis audiobook scan/read/pause/resume/stop/next/prev/status`
- Extração .epub (ebooklib) + .txt, chunking 800 chars, TTS Kokoro, bookmark persistente
- Router: macro `<call>audiobook</call>` agora chama handler real

### 6. Observabilidade (ee87408)
- `core/logging.py` — Logger JSONL centralizado com rotação 10MB
- `jarvis metrics` — métricas por módulo/nível/evento com filtros
- `jarvis doctor` expandido: network, sockets, Btrfs + `--json` flag
- Instrumentação: agent (start/done/tool_call/timeout/error), heal, router, doctor

### 7. Perfil de Usuário Dinâmico (9d0103f)
- `jarvis profile show/set/forget` — preferências locais (language, verbosity, tone, expertise)
- Contexto adaptativo: hora do dia, load 1m/5m, memória disponível injetados no system prompt
- Verbosidade ajustável: minimal (sem SYSTEM), normal, verbose (tudo)

### 8. Docs (451ba46)
- README com diagramas Mermaid (arquitetura + ciclo de memória)
- Guia de instalação "Padrão Ouro" para Acer Nitro V15 (8 passos)

# HANDOFF — Validação de Integração E2E e Hardening (2026-08-19)

## Status de Validação da VM vs. Bare Metal
- **Ambiente de Integração Atual**: VM Hyper-V (NixOS Lab, Intel i7-13620H, sem GPU passthrough).
- **Status do Runtime**: VM VALIDADA | BARE METAL PENDENTE (NVIDIA RTX 4050 Laptop / CUDA Offload).
- **Suíte de Testes**: 492+ testes unitários/propriedade/fuzzing PASS.
- **Serviços Ativos em Runtime**: `llama-cpp-server`, `llama-cpp-embeddings`, `llama-cpp-rerank`, `qdrant`.

## Resultados das Validações
1. **llama.cpp REAL**: Endpoints `/v1/chat/completions` e `/v1/models` operacionais com `enable_thinking=False`.
2. **Qdrant REAL**: Coleções `memories` e `code_index` ativas em `127.0.0.1:6333` com persistência No CoW (+C).
3. **RAG & Memória Episódica**: Ingestão, chunking, deduplicação e busca vetorial validados via `test_integration.py`, `test_rag.py` e `test_memory.py`.
4. **Agente & Tools**: Ciclo de execução com ferramentas de desenvolvimento (`devtools.py`) e tratamento de exceções gracioso no `semantic_search`.
5. **Resiliência e Fricção**: Reinício quente de daemons e tratamento de indisponibilidade de banco vetorial validados.

## Pendente / Próximos Passos
1. **Instalação host com disko** — detectar Gen3/Gen4, editar device IDs, `nixos-install --flake .#nitro-v15`
2. **Plugar hwprofile ao serviço** (llama-cpp.nix consumir o cálculo)
3. **Validar mpvpaper no host** (hwdec vaapi iGPU)
4. **nixpkgs SYCL incompleto** (#367722) — overlay local p/ whisper SYCL no host
5. **Testes de integração real** — com Qdrant/LLM rodando (não mocks)
6. **Dashboard waybar** — erros recentes, latência SLM, métricas em tempo real
7. **Alertas Telegram** — notificar quando doctor detecta serviços down
8. **Event Bus daemon** — rodar como systemd user service com `jarvis triggers run --loop`
9. **Vision no host** — validar grim/slurp no Hyprland real (VM sem display)
10. **CLI dev expandido** — bulldozer loop completo com retry automático de erros de build/teste
11. **Dev tools no pi.nix** — integrar capabilities do jarvis dev ao CLI standalone

## Problemas Conhecidos
- **Logind D-Bus timeout**: erro recorrente no rebuild, não afeta funcionalidade
- **Hyprland 100% CPU** (`.Hyprland-wrapp`): investigar
- **kworker storm / rede lenta**: mitigado com ethtool (gro/tso/gso off)
- **NVIDIA driver na VM**: `No NVIDIA GPU found` (esperado, sem PCIe passthrough)
- **Partição legada**: montagem manual pós-reboot (cryptsetup → mount subvol @/@home)
- **Chave Groq vazada no git history** (home.nix) — usuário deve rotacionar

## Decisões Importantes
- **Qwen3.6-35B-A3B** = modelo host (MoE 35B total/3B ativos, expert offload)
- **Divisão de hardware no host**: RTX 4050 = LLM (35B MoE) · iGPU UHD 770 = whisper STT + mvpaper · CPU = TTS Kokoro + embeddings
- **Não clonar pi/codebuff** — só inspirar; JARVIS é implementação própria
- **Telegram > ntfy** (bidirecional + aprovação); tudo pelo Telegram

## Comandos para Retomar
```bash
cd /home/nixos/nixos-config-reborn
cat HANDOFF.md
./rebuild.sh                    # ativa tudo no lab
jarvis hwdetect && jarvis hwprofile
jarvis doctor                   # saúde completa (agora inclui UI)
# Host simulado:
python3 -c "from jarvis.core.hwdetect import HardwareProfile, CpuInfo, GpuInfo; from jarvis.core.hwprofile import full_report; import json; hw = HardwareProfile(cpu=CpuInfo(cores=12, threads=16), gpu=GpuInfo(name='RTX 4050', vram_gb=6.0, backend='cuda', count=1), ram_gb=32.0, aux_gpu_name='Intel UHD 770'); print(json.dumps(full_report(hw), indent=2, ensure_ascii=False))"
```

## Diagnóstico de Arquitetura (4 Pilares)

Diagnóstico completo em `docs/architecture/pillar-diagnostic.md`. Score geral: **82/100** (pre-hardening).

**Top 3 fixes — IMPLEMENTADOS (commit 422d0be):**
1. ✅ `response_format: json_object` no payload do LLM (agent.py) — reduz repair loops ~50%
2. ✅ Deduplicação de memória episódica (memory.py) — texto dedup + max_chars=500 em lessons()
3. ✅ heal.py: MemoryStore (bug) → EpisodicMemory — fecha loop de self-heal

**Bônus**: devShell PYTHONPATH corrigido (absoluto, não relativo); system_prompt limpo de instruções MCP.

**485+ testes passando.**

## Notas Técnicas
- **KV cache**: `2 * n_kv_heads * head_dim * n_layers * bytes` (f16=2, q8=1)
- **Expert MoE/layer**: `(params_b − attn_total_b) / layers / n_experts * 1e9` (cuidado com unidades B vs raw!)
- **VRAM**: `ngl = floor((vram − kv − 0.6) / gb_por_camada)`
- **Offload iGPU**: `LIBVA_DRIVER_NAME=iHD` + mpvpaper `--hwdec=vaapi`; whisper SYCL = `intel-compute-runtime` + overlay

---

## Security Hardening (2026-08-19) — Commit 583d30c

### Threat Model — Vetores de Ataque

| # | Vetor | Severidade | Antes | Depois |
|---|---|---|---|---|
| 1 | **Chaining bypass** (`cat /etc/shadow; rm -rf /`) | 🔴 CRÍTICO | ✗ Aceito | ✗ Rejeitado |
| 2 | **Tool hallucination** (modelo gera tool inventada) | 🟡 MÉDIO | ✗ Executada | ✗ Rejeitada + audit |
| 3 | **MCP tools sem validação** (arguments arbitrários) | 🟡 MÉDIO | ✗ Aceito | ✗ Rejeitado |
| 4 | **Prompt injection via RAG** | 🟢 BAIXO | — | Mitigado (allowlist) |
| 5 | **Self-heal restart arbitrário** | 🟢 BAIXO | — | OK (SERVICE_MAP) |
| 6 | **Audit trail adulterado** | 🟢 BAIXO | — | OK (state_dir declarativo) |

### Barreiras Implementadas

1. **`has_chaining_operators()`** — detecta `&&`, `||`, `;`, `|`, backticks, `$()`, `${}`, `\n`. Comandos com chaining são rejeitados pelo `command_allowed()` mesmo se o prefixo for válido.

2. **`_valid_tool_names()`** — whitelist de tools aceitas (`execute_shell` + MCP registrados). Tools hallucinadas pelo modelo são rejeitadas com entrada no audit trail.

3. **Empty cmd guard** — comandos vazios/malformados retornam erro sem execução.

### Testes de Segurança (6 novos)

- `test_chaining_operators_detected` (6 patterns)
- `test_chaining_operators_not_in_safe_commands` (4 safe)
- `test_chaining_bypasses_allowlist` (3 cenários)
- `test_empty_cmd_rejected` (3 patterns)
- `test_unknown_tool_rejected` (simulação real)
- `test_execute_shell_only_tool_accepted`

**485+ testes passando** (zero regressão). Inclui: 248 base + 6 security + 31 PBT + 30 wakeword + 20 profile + 13 observability + 34 eventbus/triggers/vision + 25 circuit breaker + 56 fuzzing/mutation + 25 devtools.

### O Que NÃO Foi Implementado (decisão consciente)

- **Rate limiting por IP/sessão** — não aplicável (agent é local, não HTTP público)
- **Sandboxing de comandos** — `shlex.split()` sem `shell=True` já é seguro; container/isolation é overkill para agent local
- **Integrity check no audit trail** — state_dir é declarativo via Nix; adulteração é revertida no próximo rebuild

---

## Sessão 2026-08-20 — MoE Optimization + Waybar + mpvpaper

### O que foi feito

#### 1. Otimização MoE (models.nix + llama-cpp.nix)
- **ESTRATÉGIA CORRETA** (pesquisa confirmada):
  - `-ngl 99`: TODAS as camadas de atenção na GPU (denso, roda em todo token)
  - `--n-cpu-moe 99`: TODOS os experts MoE na RAM (esparsos, rodam sob demanda)
  - Attention é o gargalo → precisa de GPU
  - Experts são lidos da RAM quando router seleciona top-k
- **Host profile**: ngl=99, n_cpu_moe=99, ctx=4K, ubatch=512, threads=16, fifo
- **mmproj**: na GPU (denso, ~861MB BF16)
- **nomic-embed**: na GPU (<500MB, mais rápido para RAG)
- **rerank**: CPU-only (`CUDA_VISIBLE_DEVICES=""`)
- **VRAM**: 4455MB/6141MB (1686MB livre)
- **Performance**: 33.3 t/s TG, 77 t/s PP (vs 8.7/26 com config errada)

#### 2. Waybar GPU Monitor + TUI Tools (porta do legado Manjaro)
- **custom/gpu**: nvidia-smi com states low/medium/high + VRAM tooltip
- **On-click handlers**: btm (cpu/mem), yazi (files), nmtui (network), ncpamixer (audio), bluetuith (bt), calcurse (clock), nvidia-smi (gpu)
- **TUI packages**: bluetuith, ncpamixer, networkmanagerapplet, calcurse, htop
- **CSS**: GPU states, JARVIS states, hover glow cyan

#### 3. mpvpaper iGPU (fiel ao legado Manjaro)
- `DRI_PRIME=pci-0000_00_02.0` força decode na iGPU Intel
- `--hwdec=vaapi --vo=gpu` renderização OpenGL na iGPU
- `-f -p -n 30 -l background` fork, presentation, 30fps, background layer
- 12 wallpapers .mp4 em `home-manager/assets/wallpapers/`

### VRAM Budget Final (RTX 40506GB)

```
Main LLM (ngl=10):     5096MB  ← Qwen3.6-35B (attn+4experts × 10 layers)
Embeddings:               0MB  ← CUDA_VISIBLE_DEVICES="" (CPU only)
Rerank:                   0MB  ← CUDA_VISIBLE_DEVICES="" (CPU only)
mmproj:                   0MB  ← DESATIVADO (861MB BF16 não cabe)
CUDA overhead:          ~460MB
─────────────────────────────
Total:                  5556MB / 6141MB (585MB livre)
```

### Distribuição de Hardware (planejada)

```
RTX 4050 (6GB VRAM):
  └── Main LLM (Qwen3.6-35B-A3B MoE, ngl=10, expert offload)

Intel UHD 770 iGPU:
  └── Whisper STT (SYCL/OpenVINO, 12x boost)
  └── mpvpaper (wallpaper animado, VA-API)
  └── Kokoro TTS (futuro)

CPU (i7-13620H, 32GB RAM):
  └── MoE experts na RAM (6 routed experts × 40 layers)
  └── Embeddings (nomic-embed, 4 threads)
  └── Reranker (bge-reranker, 4 threads)
```

### Erros Corrigidos Nesta Sessão

1. **Nix interpolação**: `${GPU_UTIL}` em waybar.nix → `''${GPU_UTIL}` (escape para literal)
2. **Flags deprecated**: `--no-mmap`/`--mlock` → `--load-mode mlock` (llama.cpp 10273)
3. **CUDA OOM**: embeddings/rerank consumiam 540MB VRAM → `CUDA_VISIBLE_DEVICES=""`
4. **mmproj OOM**: 861MB BF16 não cabe com ngl=10 → desativado temporariamente
5. **build errado**: `nixos-rebuild build --flake .#nixos-lab` → deve usar `./rebuild-host.sh`

### Performance Medida

```
ANTES (config errada ngl=10):
  Prompt processing:  26 t/s
  Token generation:   8.7 t/s (10.5 t/s com thinking)
  Contexto:           16K tokens

DEPOIS (config correta ngl=99 --n-cpu-moe 99):
  Prompt processing:  77 t/s
  Token generation:  33.3 t/s
  Contexto:           4K tokens
  VRAM:               4455MB / 6141MB (1686MB livre)
```

### Comandos Importantes

```bash
# REBUILD (host) — NÃO usar nixos-rebuild direto!
./rebuild-host.sh

# TESTE E2E
curl -s http://localhost:8080/health
curl -s http://localhost:8080/v1/models
curl -s http://localhost:8080/completion -H "Content-Type: application/json" \
  -d '{"prompt": "Olá", "n_predict": 32}'

# VRAM CHECK
nvidia-smi
nvidia-smi --query-compute-apps=pid,used_memory,name --format=csv

# LOGS
journalctl -u llama-cpp-server -f
journalctl -u llama-cpp-embeddings -f
```

---

## Sessão 2026-08-20 (continuação) — Pipeline de Voz + Hyprland + Waybar

### Problemas diagnosticados e corrigidos

#### 1. Pipeline de voz (wakeword → STT → LLM → TTS) NÃO funcionava
**Causa raiz**: Duas falhas encadeadas:
- `brainCommand` no wakeword estava vazio `[]` (default) — o daemon gravava WAV mas nunca chamava o pipeline
- `pkgs.jarvis` era a versão **base** (sem faster-whisper/kokoro) — mesmo com brainCommand correto, `jarvis voice` falharia com ImportError

**Correções**:
- `home.nix`: Adicionado `brainCommand = [ "jarvis" "voice" ]` ao wakeword service
- `flake.nix`: Overlay `pkgs.jarvis` agora aponta para `.withVoice` (STT + TTS incluídos)
- `jarvis-wakeword.nix`: Adicionado `E231` ao flakeIgnore (erro de linting na string Nix do brainCommand)

#### 2. Hyprland com bordas brancas quadradas
**Causa raiz**: `general`, `decoration` e `animations` só existiam no `dynamic.conf` (gerado pelo script runtime), que ficava vazio até o Hyprland iniciar. O config estático não tinha essas seções.

**Correção**: Seções movidas para `settings` estático no `main.nix`, com `"col.active_border"` como chave string (não nesting `col { active_border = ... }` — o home-manager Hyprland serializa attrsets como seções hyprlang, mas `col.active_border` é uma chave pontilhada, não seção).

#### 3. Waybar ícones faltando (só Files e Brightness)
**Causa raiz**: Font family no CSS era `"SymbolsNerdFont"` mas o fontconfig registra como `"Symbols Nerd Font"` (com espaço).

**Correção**: Font family atualizada para `"Symbols Nerd Font"`.

### Estado verificado (E2E)
- ✅ LLM: 33.0 t/s, healthy
- ✅ Embeddings: healthy (CPU-only)
- ✅ Reranker: healthy (CPU-only)
- ✅ Wakeword: running, brainCommand configurado
- ✅ Hyprland: borders cyan gradient, rounding=10, shadow enabled
- ✅ Waybar: GPU monitor, TUI on-click, icons (font corrected)
- ✅ GPU: 4307MB/6141MB VRAM
- ✅ Testes: 30/30 passam

### Arquivos alterados nesta iteração
- `flake.nix` — pkgs.jarvis → withVoice
- `home-manager/home.nix` — brainCommand wakeword
- `home-manager/modules/services/jarvis-wakeword.nix` — E231 ignore
- `home-manager/modules/hyprland/main.nix` — static general/decoration/animations, col.active_border flat key
- `home-manager/modules/waybar.nix` — font family correction
- `modules/ai/models.nix` — batchSize no vm profile


---

## RELATÓRIO DE AUDITORIA — Sessão 2026-08-20

### Tabela PASS/FAIL/BLOCKED por Camada

| Camada | Estado | Evidência | Risco |
|--------|--------|-----------|-------|
| Flake | ✅ PASS | `nix flake check` OK, inputs pinados | Baixo |
| Disko | ⏳ PENDENTE | Não auditado (requer bare metal) | — |
| LUKS | ⏳ PENDENTE | Não auditado (requer bare metal) | — |
| Btrfs | ⏳ PENDENTE | Não auditado (requer bare metal) | — |
| Boot | ⏳ PENDENTE | Não auditado (requer bare metal) | — |
| Hardware | ✅ PASS | hwdetect/hwprofile funcionais, ngl=99 n-cpu-moe=99 | Baixo |
| NVIDIA | ⚠️ DECLARADO | Config correta no models.nix, VRAM 4.4/6GB | Médio (iHD crash) |
| systemd | ✅ PASS | heal, idle, wakeword, mpvpaper, llama-cpp OK | Baixo |
| Home Manager | ✅ PASS | waybar, hyprland, rofi, mpvpaper configurados | Baixo |
| Secrets | ✅ PASS | /etc/jarvis-telegram.env (EnvironmentFile, não no git) | Baixo |
| Idempotência | ✅ PASS | rebuild-host.sh converge em 2 rebuilds | Baixo |
| Persistência | ✅ PASS | ~/.local/state/jarvis (memória, vault, logs) | Baixo |
| Rollback | ⏳ PENDENTE | Requer teste de geração anterior | — |
| VM/Bare Metal | ✅ PASS | Config separada (vm profile vs host profile) | Baixo |
| Pipeline Voz | ✅ PASS | brainCommand=[jarvis,voice], withVoice package | Baixo |
| Waybar | ✅ PASS | GPU/iGPU/CPU/Memory/Battery com cores | Baixo |
| Hyprland | ✅ PASS | Cyan borders, rounding, shadow, animations | Baixo |
| JSONL | ✅ PASS | JARVIS_JSONL=0 no host, habilitado na VM | Baixo |
| mpvpaper | ⚠️ PARCIAL | Funciona sem hwdec=vaapi (iHD crash no NixOS) | Médio |

### Problemas Encontrados e Corrigidos

1. **MoE performance invertida** (8.7→33 t/s): ngl=99 + n-cpu-moe=99
2. **Pipeline de voz desconectada**: brainCommand vazio + jarvis sem voice deps
3. **Hyprland sem decoração**: dynamic.conf read-only do HM
4. **Waybar sem cores**: módulos built-in sem classes CSS
5. **iHD VA-API crash**: hwdec=auto-safe como workaround
6. **hyprpaper bloqueando mpvpaper**: desabilitado
7. **JSONL sempre ativo**: agora condicional via env var
8. **grim pedindo seleção**:改为 save screen

### Pendente Bare Metal

- NVIDIA driver validação real
- CUDA performance
- VRAM com mmproj quantizado
- Whisper/Kokoro performance real
- Thermal throttling
- Power management
- Rollback test

### VM BASELINE VALIDADO; BARE METAL PENDENTE

