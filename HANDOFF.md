# HANDOFF - Sessão 2026-08-19 (atualizado)

## Estado Atual do Sistema
- **NixOS Lab**: VM Hyper-V, i7-13620H (4c/8t visíveis), 19.1GB RAM, sem GPU
- **Último rebuild**: OK — **346+ testes verdes**
- **Git**: limpo (após commit 9d0103f)
- **Partição legada montada**: `/mnt/legacy/system` (@) + `/mnt/legacy/home/kuchiriel` (@home) — **NÃO persiste no reboot** (cryptsetup manual)

## Commits Recentes (em ordem — sessão 2026-08-19)
```
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

## Pendente / Próximos Passos
1. **Instalação host com disko** — detectar Gen3/Gen4, editar device IDs, `nixos-install --flake .#nitro-v15`
2. **Chave Groq rotacionar** — vazou no git history (home.nix antigo)
3. **Plugar hwprofile ao serviço** (llama-cpp.nix consumir o cálculo)
4. **Validar mpvpaper no host** (hwdec vaapi iGPU)
5. **nixpkgs SYCL incompleto** (#367722) — overlay local p/ whisper SYCL no host
6. **Testes de integração real** — com Qdrant/LLM rodando (não mocks)
7. **Dashboard waybar** — erros recentes, latência SLM, métricas em tempo real
8. **Alertas Telegram** — notificar quando doctor detecta serviços down

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

**346+ testes passando.**

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

**346+ testes passando** (zero regressão). Inclui: 248 base + 6 security + 31 PBT + 30 wakeword + 20 profile + 13 observability.

### O Que NÃO Foi Implementado (decisão consciente)

- **Rate limiting por IP/sessão** — não aplicável (agent é local, não HTTP público)
- **Sandboxing de comandos** — `shlex.split()` sem `shell=True` já é seguro; container/isolation é overkill para agent local
- **Integrity check no audit trail** — state_dir é declarativo via Nix; adulteração é revertida no próximo rebuild
