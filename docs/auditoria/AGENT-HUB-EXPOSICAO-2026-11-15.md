# Agent Hub sem auth na LAN/tailnet (14/11/2026)

Achado de review pedido pelo proprio autor do hub (WAKE-HUB), medido por
`coord-naming` (Lince). **O arquivo vivo nao foi alterado**: a lane que o
construiu esta ativa em outra maquina e o dono dormiu. O que esta aqui e' o
**patch pronto e provado**, mais o comando de aplicacao.

## O que foi medido (o servico vivo, :8091)

| probe | resultado |
|---|---|
| `ss -ltnp` | `LISTEN *:8091` — escuta em **todas** as interfaces (o `BIND` padrao do codigo e' `'::'`, e o unit nao define `BIND`) |
| iptables | `nixos-fw-accept tcp 0.0.0.0/0 ... dpt:8091` — a **LAN inteira** alcanca a porta |
| `GET http://100.121.100.103:8091/api/transcript?session=<id>` | **200**, com o transcript (inclui `tool inputs`, ou seja, conteudo de arquivo em transito) |
| `POST http://100.121.100.103:8091/api/wake` com JSON | **200**, sem credencial nenhuma |

O servidor usa a senha do opencode como **confused deputy**: quem alcanca
a porta injeta um user-turn em **qualquer** sessao da frota (inclusive as do
red-team) e le qualquer transcript. O comentario do topo do arquivo diz
"Nada de credencial exposta: o token fica so no lado do servidor
(loopback)" — mas o bind nao e' loopback.

## O segundo defeito: `busy` morto

`const busy = s ? Number(s.busy || 0) : null;` — a API `/api/session` **nao
devolve** campo `busy` (medido: as chaves reais sao `agent`, `cost`, `id`,
`location`, `model`, `outcome`, `projectID`, `time`, `title`, `tokens`), e o
roster tambem nao tem. Logo `busy` era sempre 0 e **todo agente aparecia
"idle"**, mesmo trabalhando; a linha do HTML ainda calculava "ha Xs ativo"
com esse zero. A fonte real e' `time.updated`.

## O que o patch faz

1. **Token proprio** do hub, de `AGENT_HUB_TOKEN` ou de
   `~/.config/opencode/agent-hub.token` (0600), comparado em tempo
   constante (`timingSafeEqual`). **Fail-closed**: sem token configurado,
   as rotas sensiveis recusam.
2. Guarda de token em `/api/transcript` e `/api/wake` (as duas que vazam ou
   escrevem). `/api/agents` (leitura de estado) fica aberto.
3. `busy` derivado de `time.updated` (janela de 90 s, `AGENT_HUB_BUSY_MS`).
4. Corpo do `POST /api/wake` limitado a 64 KiB.
5. `BIND` padrao muda de `'::'` para `'127.0.0.1'`. Para usar na tailnet
   de novo, `BIND=::` **de proposito** — e o token continua obrigatorio.

## Prova (em porta temporaria, sem tocar no servico vivo)

```
1) bind: LISTEN 127.0.0.1:18091
2) transcript SEM token -> 401 {"error":"token required (x-agent-hub-token)"}
3) wake SEM token      -> 401 {"error":"token required (x-agent-hub-token)"}
4) transcript COM token -> 200
5) /api/agents (leitura, sem token) -> 200
6) campos de um agente: {'name': 'sweep-2026-11', 'status': 'busy', 'busy': True, 'updated': 1794712878810}
PROVA OK
```

O servico vivo foi deixado intacto (`systemctl --user is-active
agent-hub.service` = `active` durante a prova).

## Como aplicar (quando o dono acordar)

```bash
cd ~/projects/nixos-ai
patch -p0 < docs/auditoria/patches/agent-hub-auth-2026-11-15.patch
node --check scripts/agent-hub.mjs
# token do hub (o celular precisa do mesmo)
install -m 600 /dev/null ~/.config/opencode/agent-hub.token
openssl rand -hex 24 > ~/.config/opencode/agent-hub.token
systemctl --user restart agent-hub.service
```

Para a tailnet, no unit: `Environment=BIND=::` (e o token continua
obrigatorio nas rotas que vazam ou escrevem).
