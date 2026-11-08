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
