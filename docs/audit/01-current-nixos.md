# Auditoria do NixOS atual — Fase 1

> Analisado o repositório **antes** do legado. Nenhuma alteração feita.

## 1. Estrutura do repositório

```
flake.nix / flake.lock
hosts/
  nixos-lab/            ← único host ativo no flake
    configuration.nix   (IA + NVIDIA + greeter + firewall…)
    hardware-configuration.nix
    local-packages.nix
  slim3/                ← STALE (não referenciado)
  330-15ARR/            ← STALE
  nixos-lab/slim3/      ← STALE
nixos/modules/          ← módulos base (audio, boot, kernel, user, net, …)
modules/services/       ← IA: llama-cpp.nix, qdrant.nix (import dinâmico + explícito)
home-manager/
  home.nix
  home-packages.nix
  modules/              ← desktop (hyprland, waybar, neovim, …), ai/pi.nix, services/jarvis-wakeword.nix
scripts: rebuild.sh, limpar_nixos.sh, mount_manjaro.sh, shell.nix
```

## 2. O que funciona hoje

- **llama-cpp**: serviço systemd custom (`services.llama-cpp-server`) com download automático do GGUF via `aria2c`, perfil adaptativo VM vs bare metal (detecção via `systemd-detect-virt`), chat OpenAI-compatível em 127.0.0.1:8080. Build vindo de **nixpkgs-unstable** via overlay.
- **Qdrant**: serviço nativo nixpkgs (`services.qdrant`) com usuário/grupo dedicados e tmpfiles. ✓
- **Pi Agent** (`home-manager/modules/ai/pi.nix`): CLI Python (`pi`) com tool calling (`execute_shell`) contra o llama-server; tem fallback de extração de tool_call em texto puro (bug conhecido do Qwen no llama.cpp). É o único "agente" do sistema atual.
- **Wakeword**: módulo home-manager `services.jarvis-wakeword` (openwakeword "hey jarvis") — **conceito certo, implementação quebrada** (ver §4).
- Desktop, theme, synths — fora do escopo da missão IA, mas funcionais.

## 3. Componentes de IA atuais (inventário)

| Componente | Onde | Estado |
|---|---|---|
| Servidor LLM | `modules/services/llama-cpp.nix` (custom) | funciona (VM: 7B, 0 GPU layers) |
| Vector DB | `modules/services/qdrant.nix` (nixpkgs) | funciona, sem coleções |
| Wakeword | `home-manager/modules/services/jarvis-wakeword.nix` | **quebrado** (numpy) + pipeline incompleto |
| Agente CLI | `home-manager/modules/ai/pi.nix` | funciona (experimental) |
| RAG / memória / STT / TTS / vision | — | **inexistentes** no sistema atual |

## 4. Problemas encontrados (débito técnico)

1. **`jarvis-wakeword` crash-loop**: `pkgs.writers.writePython3Bin` recebe `libraries = [ jarvisPythonEnv ]` (um *env*, não uma lista de pacotes) → numpy ausente no runtime. Além disso o módulo **não implementa o pipeline** (não grava áudio, não chama STT/brain — o legado fazia tudo isso). Path do modelo hardcoded para `python3.14/site-packages` (frágil).
2. **`git-sync-obsidian`** falha (vault `~/para` inexistente) → timer reinicia a cada 15 min.
3. **Import duplicado** de `qdrant.nix` (import explícito + `dynamicServiceImports` que varre todo `modules/services`).
4. **`services.llama-cpp-server` custom duplica** o módulo oficial do nixpkgs (`services.llama-cpp`, presente em 24.11: opções `enable/package/model/extraFlags/host/port/openFirewall`). O módulo custom adiciona o download de modelo + perfil VM/bare metal — funcionalidade que deve ser preservada, mas o serviço base pode ser nativo.
5. **Download de modelo no runtime** (aria2c no ExecStart) — frágil (rede, espaço, checksum); preferível provisionar modelo de forma verificável.
6. **Modelos em `/home/nixos/models`**: o módulo oficial tem `ProtectHome=true` → modelos precisariam ficar fora de `/home` (ex.: `/var/lib`), decisão de arquitetura.
7. **Firewall**: porta 11434 (Ollama) morta; 8080 aberto para o mundo (0.0.0.0) sem auth — o daemon interno deveria falar com o servidor via loopback.
8. **`rebuild.sh`** faz commit automático genérico — polui o histórico (ver baseline §6.5).
9. **`env.nix`** injeta `$HOME/.local/bin` no PATH (resquício de scripts imperativos) — viola o princípio "sem estado imperativo em ~".
10. **Sem testes, sem docs, sem separação core/adapters** — tudo que a missão pede para construir.
11. **Sem observabilidade** além do journal.
12. NixOS **24.11 EOL** (nixpkgs de 2025-06) — a base deve ser atualizada (decisão no plano).

## 5. O que deve permanecer / ser corrigido (resumo)

- **Permanecer**: conceito do Pi Agent (CLI + tool calling), Qdrant via nixpkgs, llama-cpp via unstable, estilo "1 host ativo".
- **Corrigir**: módulo wakeword (build do pacote + pipeline completo), import dinâmico de serviços, chave do cache CUDA, firewall, tmpfiles legado, rebuild.sh, EOL do NixOS.
- **Remover (em commits isolados, após confirmar ausência de referências)**: hosts stale, `.bak` commitados, porta 11434, cleanup ollama, README desatualizado.

---
**Ver também:** [[../../HANDOFF]] | [[../PLATFORM-ASSESSMENT]] | [[../GAP-ANALYSIS-2026-08-29]]
