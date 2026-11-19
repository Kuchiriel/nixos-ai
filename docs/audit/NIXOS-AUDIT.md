# NIXOS-AUDIT — flake, módulos, Home Manager, segredos (Fase 5)

> Medido em 2026-11-19. Regras da missão preservadas: não rodar
> `rebuild-host.sh`/`nixos-rebuild switch`, não alterar Hyper-V/VM, não
> reiniciar serviços, não colocar segredos no Nix Store.

## 1. Era 0 (2024-11-23) — padrões perigosos verificados no código atual
| padrão no commit inicial (`ae8789fa`) | estado atual | veredito |
|---|---|---|
| `zramSwap.memoryPercent = 100` | `nixos/modules/zram.nix:10` = **50** (zstd, swappiness 10) | **corrigido** |
| boot duplicado em `configuration.nix` + `modules/boot.nix` | apenas `nixos/modules/boot.nix:5-6` | **corrigido** |
| `stateVersion = "23.11"` hardcoded | `home-manager/home.nix:1016` usa `homeStateVersion` (single source) | **corrigido** |
| `nh.flake = "/home/amper/flake"` (host inicial) | não encontrado | **corrigido** |
| usuário `amper` / Tashkent | substituído por `nixos` / nitro-v15 | **corrigido** |

## 2. Serviços declarados (amostra)
`jarvis-gaming-watcher.service`, `jarvis-heal.service`,
`jarvis-idle-worker.service`, `jarvis-keys-env.service`,
`jarvis-telegram.service`, `jarvis-vault-summarize.service`,
`jarvis-vault.service`, `jarvis-webui.service`, `vpn-guard.timer`.
`vpn-guard` resolve a causa P0 das duas VPNs (Mullvad + Tailscale matando a malha).

## 3. OpenCode declarativo
- `mcp.jarvis` é o único servidor MCP em `~/.config/opencode/opencode.json`;
  launcher resolve PYTHONPATH em runtime (`jarvis-mcp-launcher.sh`) — handle
  correto do problema de store path fixo sem PIL.
- `agents.compaction.model` = minimax (modelo que realmente resume) desde 15/11.
- `free-providers.json` + geração de providers: fonte única confirmada pela
  ausência de duplicação em `opencode.json` (1 único bloco `mcp`).

## 4. Riscos observados (sem alteração)
- `home-manager/files/opencode/plugins/memory.js` está **modificado** (guard de
  compactação portado, commit `57c91765` no repo, mas cópia de arquivo gerado
  ainda suja no working tree) — não sobrescrever sem verificar o diff.
- `flake.lock` pinado; não atualizar sem necessidade (regra de reprodutibilidade).
- Segredos: `~/.config/opencode/agent-hub.token` (0600), `/etc/litellm.env` —
  nunca no Nix Store, nunca no git/bus. Verificado: nenhum valor vazou nos docs
  de auditoria.

## 5. Próxima investigação (Fase 5 restante)
- Comparar `home-manager/files/opencode/plugins/memory.js` com o arquivo ativo
  `~/.config/opencode/plugins/memory.js` (diff real) antes de qualquer sync.
- Verificar `hyper-v`/VM intocados (fora do escopo desta missão).
