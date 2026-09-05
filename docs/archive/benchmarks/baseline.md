# Baseline — Fase 0

> Registrado em 2026-08-16, **antes** de qualquer alteração no sistema.
> Auditoria inicial — nenhuma mudança foi feita.

## 1. Estado do Git (Kuchiriel/nixos-ai → `nixos-config-reborn`)

| Item | Valor |
|---|---|
| Branch | `main` |
| Commit atual | `7d8d9b4` — "chore: update system configuration" |
| Em relação ao remoto | 1 commit à frente de `origin/main` |
| Remote | `https://github.com/Kuchiriel/nixos-ai.git` |
| Untracked | `mount_manjaro.sh`, `shell.nix` |
| Histórico | ~60+ commits todos com mensagem `chore: update system configuration` (gerados pelo `rebuild.sh` que faz `git commit -m "chore: update system configuration"` automaticamente) |

Working tree limpo (exceto 2 untracked listados acima).

## 2. Versões

| Componente | Versão |
|---|---|
| NixOS | **24.11** (`24.11.20250630.50ab793`, codinome Vicuna) — **release EOL** (sem atualizações de segurança desde ~2025-12-31) |
| Nix | 2.24.14 |
| nixpkgs (pinned) | `nixos-24.11` rev `50ab793786d9de88ee30ec4e4c24fb4236fc2674` (snapshot 2025-06-30) |
| nixpkgs-unstable | `nixos-unstable` rev `0e251e24a4f2…` (snapshot ~2026-08-13) |
| home-manager | `release-24.11` rev `d5f1f641b289` |
| stylix | `release-24.11` rev `d22e58f427f9` |
| Kernel em execução | 6.6.94 (linuxPackages default, forçado em `hosts/nixos-lab/configuration.nix`) |
| llama.cpp (serviço) | build `10273` (rev `a6aa6f5`), via overlay nixpkgs-unstable |
| Qdrant (serviço) | 1.12.1 (nixpkgs 24.11) |

## 3. Hardware (VM de laboratório)

| Item | Valor |
|---|---|
| Hipervisor | **Microsoft Hyper-V** (`systemd-detect-virt` = microsoft) |
| CPU | 8 vCPU — Intel Core i7-13620H (4 cores × 2 threads do host físico) |
| RAM | 19 GiB (host físico: 32 GB) |
| GPU | **Nenhuma visível** (sem GPU-P/vGPU — `lspci` sem VGA/3D) |
| Swap | zram 9,5 GiB (zstd, 50%) |
| Disco | sda 80 GiB btrfs (subvols `root`, `home`, `nix`); sdb 476,9 GiB LUKS (`manjaro-rescue`, snapshot legado) |
| Drivers NVIDIA | Configurados declarativamente (`hardware.nvidia` + `videoDrivers = ["nvidia"]`) mas **sem dispositivo presente na VM** — a mesma config deve funcionar em bare metal (RTX 4050) |

## 4. Serviços ativos relevantes (16-08-2026 17:00 BRT)

| Serviço | Estado | Observação |
|---|---|---|
| `llama-cpp-server.service` (custom) | **ativo** | `qwen2.5-coder-7b-instruct-q4_k_m.gguf`, ctx 16384, 4 threads, `-ngl 0` (perfil VM), porta 8080 |
| `qdrant.service` (nixpkgs) | **ativo** | 127.0.0.1:6333/6334, storage `/var/lib/qdrant/storage` |
| `jarvis-wakeword.service` (home-manager) | **falhando** | `ModuleNotFoundError: numpy` — restart counter **429** (crash-loop) |
| `git-sync-obsidian.service` (home-manager) | **falhando** | `cd: /home/nixos/para: No such file or directory` (vault não existe) |

Portas escutando: 8080 (llama-cpp), 6333/6334 (qdrant). Nada em 11434 (Ollama não existe no sistema atual — porta aberta no firewall é resquício).

## 5. Modelos presentes

`/home/nixos/models/`:
- `qwen2.5-coder-7b-instruct-q4_k_m.gguf` (4,7 GB) — usado na VM
- `qwen2.5-coder-32b-instruct-q4_k_m.gguf` (19,9 GB) — perfil bare metal

## 6. Pontos de atenção imediatos (sem ação tomada)

1. **NixOS 24.11 EOL** — nixpkgs pinned de 2025-06-30; decisão de upgrade (25.11/26.05) necessária no plano.
2. `nix.settings.substituters` inclui `https://nixos-cuda.org` com **chave pública que não corresponde** (usa a key de `nix-community.cachix.org`); cache falha verificação de assinatura.
3. Firewall libera porta **11434** (Ollama) sem serviço correspondente.
4. `systemd.tmpfiles.rules` referencia `/var/lib/private/ollama` (legado Manjaro, inexistente no NixOS atual).
5. `rebuild.sh` cria commits vazios e automáticos ("chore: update system configuration") — responsável pelo histórico inútil.
6. `services.llama-cpp-server` é módulo **custom**; o nixpkgs 24.11 já fornece o módulo oficial `services.llama-cpp` (ver `docs/audit/01-current-nixos.md`).

## 7. Estado da configuração

- Flake define **1 host** (`nixos-lab`), mas existem dirs stale: `hosts/slim3`, `hosts/330-15ARR`, `hosts/nixos-lab/slim3` (herdados do template `Andrey0189/nixos-config-reborn`, não referenciados no flake).
- Backups commitados: `flake.nix.bak`, `flake.nix.bak2`, `home-manager/home.nix.bak`, `home-manager/home-packages.nix.bak`.
- `README.md` ainda referencia o repositório antigo (`Andrey0189/nixos-config-reborn`) e fluxo de instalação desatualizado.
