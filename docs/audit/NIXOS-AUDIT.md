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

## 5. Unidades de usuário: Nix vs arquivo solto (medido 19/11)

Método (importa): `systemctl --user show <u> -p FragmentPath` devolve o caminho
do **symlink**, não o alvo — ler o retorno ao pé da letra dá 44 falsos
"imperativos" (agent-hub, coord-mcp, night-comms etc. SÃO symlinks de
`/nix/store/...-home-manager-files/`). O teste correto é `readlink -f`.

Resultado com `readlink -f` em `~/.config/systemd/user/*.service|*.timer`:
**17 unidades servidas por arquivo comum** (não-Nix). Cruzando com o repo:

| unidade | estado |
|---|---|
| `vpn-guard` (.service/.timer) | **estava solta** (instalada à mão no conserto do Mullvad, 18/11) — agora declarada em `home-manager/modules/services/vpn-guard.nix` (`54845ffa`), com migration do arquivo antigo |
| `duplex-voice.service` | declarada hoje em `services/duplex-voice.nix`, mas **sem migration** — o switch abortaria com "file in the way"; migration adicionada no mesmo commit |
| `chisel-client`, `chisel-tunnel` | soltas, fora do repo |
| `context-guard` (.service/.timer) | soltas, fora do repo |
| `dono-gate-ivan.service` | solta, fora do repo |
| `fleet-milestone`, `fleet-watchdog` (.service/.timer) | soltas, fora do repo |
| `llama-wackmall.service` | solta, fora do repo |
| `night-watch.service` | solta, fora do repo (o `nightwatch` declarado é outro: systemd de sistema) |
| `wurm-macro`, `wurm-sandbox`, `wurm-standalone` | soltas, fora do repo |

Veredicto: 12 famílias continuam sem declaração. Converter todas é um lote à
parte (cada uma precisa do dono e da migration); a de `vpn-guard` era dívida
desta auditoria e foi fechada.

**Consequência operacional:** enquanto a unit for arquivo comum, um rebuild do
home-manager **aborta** ao tentar criar o symlink (daí a migration obrigatória)
e uma máquina montada do zero não tem o serviço. O padrão da casa
(`home.activation."a-migrate-legacy-*"` + `lib.hm.dag.entryBefore
["checkFilesChanged"]`) resolve os dois.

**Validado sem rebuild:** `nix eval` do flake em `nitro-v15` lista
`systemd.user.timers.vpn-guard` e as duas activations
(`a-migrate-legacy-vpn-guard`, `a-migrate-legacy-duplex-voice`). Nada foi
ativado no host.

## 6. Próxima investigação (Fase 5 restante)
- Comparar `home-manager/files/opencode/plugins/memory.js` com o arquivo ativo
  `~/.config/opencode/plugins/memory.js` (diff real) antes de qualquer sync.
- Verificar `hyper-v`/VM intocados (fora do escopo desta missão).
- Lote das 12 famílias soltas restantes, uma por commit, com o dono de cada uma.
