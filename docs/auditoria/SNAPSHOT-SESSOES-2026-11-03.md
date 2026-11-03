# Snapshot de janelas/sessões opencode — 2026-11-03

Motivo: o reboot pendente (driver NVIDIA 615.78 vs kernel) **perde o layout do Hyprland**
(não há session-restore nativo no Hyprland 0.55.4). Este snapshot + o script
`scripts/restore-sessions.sh` devolvem as 6 sessões nas posições originais.

## Como o mapeamento foi provado (não é heurística)

Cada TUI foi aberto pelo dono como `opencode -s <sessionID>` → o PID do processo opencode
é filho do `foot` da janela, e o `-s` está na linha de comando:

```
foot 507903 (ws2) → zsh 507909  → opencode 1869988 -s ses_e752b601fffei1mSU87IeVJHqA
foot 508110 (ws2) → zsh 508111  → opencode 1869855 -s ses_e810156c0ffewjYiWj7zVwDZ3m
foot 515782 (ws3) → zsh 515783  → opencode 1345631 -s ses_eb612ed53ffeyqq6z3SMv6OSSf
foot 517641 (ws3) → zsh 517642  → opencode 1199612 -s ses_ea825420cffeGa62eQKzA4grBH
foot 510475 (ws4) → zsh 510476  → opencode 1870395 -s ses_ed0234976ffe6y6Ejh91b37m7s
foot 521331 (ws4) → zsh 521332  → opencode 1870313 -s ses_ed024086fffevWT7nQnGYXG371
```

Cruzamento com o `opencode.db` (título exato da sessão = título da janela, truncado pelo
Hyprland com "…"):

## Tabela

| ws | posição | sessão | título (DB) | modelo | cwd |
|----|---------|--------|-------------|--------|-----|
| 1 | (1 janela) | — | `(1) WhatsApp Business - Chromium` | — | — |
| 2 | left | `ses_e810156c0ffewjYiWj7zVwDZ3m` | Análise heurística de risco/retorno em EA MT5 | z-ai/glm-5.3-flash (nvidia, max) | ~/projects |
| 2 | right | `ses_e752b601fffei1mSU87IeVJHqA` | Coordenar trabalho com outro agente MT5 | z-ai/glm-5.3-flash (nvidia, max) | ~/projects |
| 3 | left | `ses_eb612ed53ffeyqq6z3SMv6OSSf` | (janela "OpenCode" = sessão deste agente) | minimaxai/minimax-m3.1-flash (nvidia) | ~/projects |
| 3 | right | `ses_ea825420cffeGa62eQKzA4grBH` | Agent heartbeat com systemd para comunicação entre agentes | minimax-m3.1-flash (nvidia, max) | ~/projects |
| 4 | left | `ses_ed024086fffevWT7nQnGYXG371` | nsncd daemon failed reboot, sessions lost, need to recover lost work | nemotron-3.5-lightning-30b-a3b (nvidia, high) | ~/projects |
| 4 | right | `ses_ed0234976ffe6y6Ejh91b37m7s` | Recuperar contexto e se reidratar após sessão do opencode | nemotron-3.5-lightning-30b-a3b (nvidia, high) | ~/projects |

- **ws1** era só o Chromium (WhatsApp Business) → o Chromium restaura a própria aba; não
  precisa de script.
- Monitor `eDP-1` (0), layout **dwindle**, escala do snapshot: janela 941×1022 (coluna),
  Chromium 1896×1022 (linha inteira).
- Snapshot bruto: `/tmp/opencode/snapshot/{windows.json,workspaces.json}` (volátil; esta
  tabela é a cópia durável).
- Foco final: ws4, janela "nsncd" (`focus=1` no TSV).

## Autostart (03/11, pedido do dono: "sim")

Para não depender de rodar o script na mão depois de cada reboot:

- **Captura contínua**: `systemd --user` timer `session-snapshot` roda
  `restore-sessions.sh --capture` a cada **60s** (`OnBootSec=2min`) e grava o
  layout ATUAL em `~/.local/state/jarvis/sessions-snapshot.tsv`.
  O modo `--capture` mapeia `foot` → `opencode -s <id>` por `/proc` (ppid até
  achar o `foot`) + `hyprctl clients -j` (workspace, X → left/right, foco).
- **Restore no login**: `exec-once` do Hyprland
  (`home-manager/modules/hyprland/main.nix`) espera o `opencode-serve`
  (até 45s) e roda `restore-sessions.sh` — idempotente, reabre o que faltar.
- Declarativo: `home-manager/modules/session-snapshot.nix` (importado no
  `home.nix`). **Só vale a partir do próximo rebuild** — neste reboot ainda
  é o script na mão (o state já está gravado, então o restore manual pega o
  layout de agora).

O restore sem `--file` prefere o snapshot do state e cai no TSV datado do repo
se o state não existir.

## Como restaurar

```bash
cd ~/projects/nixos-ai
./scripts/restore-sessions.sh --dry-run     # só imprime o que faria
./scripts/restore-sessions.sh               # relança as 6 sessões no layout original
```

O script é **idempotente**: pula sessões já abertas (`pgrep -f "opencode -s <id>"`),
relança só o que falta e foca a janela marcada `focus=1`.

Reabrir uma sessão na mão (o `-s` não aparece no `opencode --help`, mas existe e é o
mesmo que o dono usava):

```bash
cd ~/projects && opencode -s ses_ed0234976ffe6y6Ejh91b37m7s
```

Backup completo do histórico (sem abrir TUI): `opencode export <sessionID>`.


## 03/11 (tarde) — fechar o TUI não pode custar a sessão

**Sintoma (dono)**: fechar o TUI com Ctrl+C fechava a janela INTEIRA (o foot
morre junto) e a mensagem do opencode sobre reabrir a sessão sumia com ela —
depois era preciso garimpar o id no histórico.

**Causa**: o restore abria `foot -e opencode -s <id>` (sem nada depois), então
o fim do opencode = fim do foot. O launcher (`SUPER+A`) já usava `exec bash`
e por isso não tinha o problema.

**Correção (3 peças)**:
1. `scripts/opencode-session.sh` — wrapper do TUI: a janela **sobrevive** ao
   opencode, imprime `sessão: <id>` + o comando de reabertura, registra a
   sessão encerrada em `~/.local/state/jarvis/last-closed-session.json` e
   só fecha no Enter. O launcher (`jarvis/cli/launcher.sh`) e o restore
   passaram a usá-lo.
2. `scripts/opencode-resume.sh` — o caminho inverso: `--list` (sessões
   recentes do SQLite, marcando as abertas), `--last` (a última encerrada),
   `--session <id>` (uma específica). Reabre em janela nova, no diretório
   original, sob o mesmo wrapper. Se a sessão já estiver aberta, **foca** a
   janela em vez de duplicar.
3. `scripts/opencode-sessions.py` — a fonte de dados (SQLite
   `~/.local/share/opencode/opencode.db`, modo ro): `list`, `last`, `closed`,
   `directory`, `resolve`.

**Atalho**: `SUPER+SHIFT+R` → reabre a última sessão fechada (declarativo em
`home-manager/modules/hyprland/binds.nix`).

**Delta do restore**: `restore-sessions.sh` agora tem DELTA por padrão —
sessão já aberta → foca a janela, não abre outra (`--force` abre mesmo assim).
O snapshot ganhou a coluna `dir` (cwd da sessão) para reabrir no lugar certo.

**Verificado**: `list` marca ABERTA/fechada corretamente; `resolve` acha a
sessão criada depois do start; o wrapper testado com um `opencode` stub
(exit 130) imprime a dica e grava o registro; `restore-sessions.sh --dry-run`
com as 2 sessões abertas → "já aberta (focada)" nas duas (zero janelas novas).
