# Frota muda por ~5h: HTTP 405 em todo POST (2026-11-08)

## Sintoma
`agent-msg.sh` reportava "nota entregue ... HTTP 405". Todo
`POST /session/:id/message` e `/prompt_async` devolvia **405**; todo GET
devolvia 200 (a SPA fallback). Silencioso: o log dizia "entregue".

## Causa (medida)
O `opencode-serve.service` rodava o binario do nixpkgs = **opencode 2.2.6**,
cuja API e nova (backend de sessao proprio; as rotas da 1.x nao existem).
A frota (agent-msg.sh, agents-watcher.sh) e o TUI do dono falam a API do
**1.18.34**. Duas versoes, duas linguas.

O segundo processo do 2.2.6 (PID 4049886) tambem estava vivo.

## Fix imediato (sem rebuild)
Drop-in systemd `~/.config/systemd/user/opencode-serve.service.d/10-binario.conf`:
`ExecStart = /nix/store/phl68...-opencode-1.18.34/bin/opencode serve --hostname 100.121.100.103 --port 4599`
-> POST voltou a 200; entrega real testada nas sessoes do dono e do coord-naming.

## Pendente (fix definitivo, precisa de rebuild autorizado)
`programs.opencode` no home-manager esta fixando a versao do nixpkgs
(2.2.6) em vez da que a frota usa. Enquanto o drop-in existir, um
`rebuild-host.sh` pode sobrescrever o ExecStart. Pinar a versao no Nix.

## Achado lateral
O 2.2.6 nao usa `~/.local/share/opencode/opencode.db`: a sessao do
"heartbeat" (ses_ea825420) nao existe no DB do 1.18.34. As sessoes do TUI
(dono, jarvis, Cervo, Onca) estao todas no `opencode.db` e respondem 200.

## Licao
"entregue no log" nao e prova: o HTTP no fim da linha e a prova. Quando a
frota fica muda, olhar o HTTP antes de culpar o agente.

## Update 08/11 (tarde) — estado VERIFICADO

- Serve rodando **2.2.6** (`systemctl --user cat opencode-serve.service`:
  ExecStart = kilo 2.2.6, `:4599`, tailnet). O drop-in 1.18.34 foi **removido**.
- **A frota está entregando com o 2.2.6** (medido em `~/projects/AGENTS-MSG.log`):
  09:25 PROVIDER API (sweep-2026-11), 09:27/09:32 PROVIDER CTX (coord-naming),
  09:38 dúvida Dory no bus. O `agent-msg.sh`/`agents-watcher.sh` (dual-stack,
  08:14/08:16) funcionam — o 405 não se repetiu.
- **Pin da versão no Nix** (o item PENDENTE original): `programs.opencode`
  continua pinando kilo 2.2.6 (o TUI/serve atuais) — não mexido: pinar versão
  contra o dono é decisão de produto, não minha. O nag continua: SOMENTE um
  pin explícito no home-manager blinda um rebuild contra troca silenciosa.
- **Crash-loop do nv-gate** (o único incidente do dia): 09:24→09:34,
  `Restart=always`+3s + kill externo → storm até counter≥23; sessões tomaram
  erros llama.cpp-style "available context size (4096 tokens)" nessa janela.
  Fix em `home-manager/modules/services/nv-gate.nix` (on-failure +
  StartLimitBurst=5/Interval=180s) — commit `2de5a11c`. Gate estável desde
  09:34 (ping 200; prefill de 8,7k / 50k / **300k** tokens aceitos).
- **NIM saudável o dia inteiro de medições diretas** — ver
  commit `2de5a11c` e o repo `opencode-nvidia-fix`.
