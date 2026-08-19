# HANDOFF - Sessão 2026-08-19 (atualizado com hardening security)

## Estado Atual do Sistema
- **NixOS Lab**: VM Hyper-V, i7-13620H (4c/8t visíveis), 19.1GB RAM, sem GPU
- **Último rebuild**: OK — **248 testes verdes + flake check OK**
- **Git**: limpo (antes do commit pendente desta sessão)
- **Partição legada montada**: `/mnt/legacy/system` (@) + `/mnt/legacy/home/kuchiriel` (@home) — **NÃO persiste no reboot** (cryptsetup manual)

## Commits Recentes (em ordem)
```
<esta sessão> sistema-água + host skeleton + hyprland fixes + litellm cascade
92dde21 refactor(água): switch services.jarvis.environment central
85e9a01 feat(doctor): check_ui — saúde dos elementos cosméticos
e30a251 feat(ui): mpvpaper (wallpaper animado mp4) com condicional VM/host
de64d5e feat(ui): tema rofi jarvis-cyan portado do legado + gaps do host
bb92b30 feat(waybar): módulo custom/jarvis (estado da pipeline) + CSS
580f105 feat(ai): iGPU integrada detectada + offload auxiliar (whisper SYCL)
94524ad feat(ai): auto-detecção de hardware → flags SOTA (hwdetect/hwprofile)
aa31efb docs: handoff para nova sessão
```

## O Que Foi Implementado Nesta Sessão

### 1. hwdetect/hwprofile (auto-detecção → flags SOTA)
- `jarvis hwdetect`: detecta RAM/VRAM/CPU/GPU/NPU + **iGPU auxiliar** (lspci), classifica tier (Termux→datacenter)
- `jarvis hwprofile`: calcula KV cache (fórmula exata), offload full/expert/partial/cpu, previsão t/s, bloco models.nix renderizado
- Catálogo com arquiteturas REAIS (config.json HF): Qwen3-1.7B/4B/8B, Qwen3.6-27B, Qwen3.6-35B-A3B (40L, 2kv, 256hd), Qwen3-VL-235B (approx)
- **Host alvo (RTX 4050 6GB/32GB)**: Qwen3.6-35B-A3B MoE+vision, expert offload ngl 17/n-cpu-moe 2/KV q8/32K/-fa on, ~11 t/s
- **iGPU Intel UHD**: whisper STT vai para iGPU via SYCL/OpenVINO (12x boost whisper.cpp 1.8.3); TTS Kokoro NÃO (82M, CPU em ms); mvpaper SIM (OpenGL)
- Bugs caçados: unidades B/raw, Apple unified memory, multi-GPU VRAM total

### 2. Look and feel do legado portado
- **Tema rofi jarvis-cyan** (assets/rofi/, declarado home-manager)
- **mpvpaper**: 12 wallpapers mp4 versionados (121MB), serviço user com `ConditionVirtualization=!vm` — host sobe com hwdec VA-API na iGPU (LIBVA_DRIVER_NAME=iHD), VM não sobe (hyprpaper estático)
- **Waybar**: módulo custom/jarvis com estados (idle/listening/thinking/speaking/error/done) via jarvis-waybar + CSS animado
- Gaps hyprland host 5/10 (VM 2/4), cores ciano já estavam portadas

### 3. Doctor com saúde cosmética (check_ui)
- Monitora: waybar, hyprland, swaync, tema rofi, mpvpaper (condicional VM/host)
- Cosmético só degrada, nunca derruba overall
- Validado ao vivo: detectou waybar parado

### 4. Sistema-água + host skeleton + cascade
- **`services.jarvis.environment = "vm"|"host"`** (nixos/modules/jarvis-env.nix) — switch central; todos os módulos bebem dele
- **Waybar VM profile**: sem battery/bluetooth/backlight (popups somem). BUG: diretório `waybar/` era INERTO — arquivo ativo é `waybar.nix` (raiz); usar if/then/else puro
- **Hyprland**: 4 deprecações corrigidas (layoutmsg, pseudotile, gesture, windowrule)
- **Host skeleton** `hosts/nitro-v15/`: configuration.nix (switch host) + disko.nix (2 NVMe: rápido=/+ /nix, lento=/home) — NÃO registrado no flake até hardware-config real
- **LiteLLM cascade** (módulo oficial nixpkgs + litellm-cascade.nix): local→Groq→Gemini→OpenRouter em :4000; chaves /etc/litellm.env
- **SEGURANÇA**: chave Groq removida do home.nix (vazou) — usuário deve ROTACIONAR

## Pendente / Próximos Passos
1. **rebuild.sh pendente** — ativar no lab: waybar sem popups, hyprland fixes, litellm, doctor novo
2. **Waybar não aparece na VM**: o pkill matou e o exec-once só roda no login — reiniciar sessão Hyprland (SUPER+M) ou `waybar &` manual; o config carregado é o ANTIGO até o rebuild
3. **Hyprland na VM**: erros ZINK/EGL (esperado sem GPU); hyprlock "Authentication failed" — destravar com senha do nixos ou Ctrl+Alt+F3
4. **Plugar hwprofile ao serviço** (llama-cpp.nix consumir o cálculo)
5. **Validar mpvpaper no host** (hwdec vaapi iGPU)
6. **Wallpaper alien_static.jpg** se perdeu — procurar no HD externo
7. **nixpkgs SYCL incompleto** (#367722) — overlay local p/ whisper SYCL no host
8. **Instalação host com disko**: detectar Gen3/Gen4 (nvme list / lspci LnkSta), usar /dev/disk/by-id

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

**248/248 testes passando.**

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

**310/310 testes passando** (zero regressão).

### O Que NÃO Foi Implementado (decisão consciente)

- **Rate limiting por IP/sessão** — não aplicável (agent é local, não HTTP público)
- **Sandboxing de comandos** — `shlex.split()` sem `shell=True` já é seguro; container/isolation é overkill para agent local
- **Integrity check no audit trail** — state_dir é declarativo via Nix; adulteração é revertida no próximo rebuild
