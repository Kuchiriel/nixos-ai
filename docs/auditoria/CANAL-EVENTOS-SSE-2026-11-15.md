# O canal de eventos: o SSE do webui nao ve o que o coord-mcp publica

(15/11/2026, coord-naming — task t-2: "publicar eventos da frota em
/api/events/stream e plugar no Agent Hub")

## A pergunta feita

"poste 1 evento de heartbeat do coord-mcp e me diga se o SSE recebeu".

## A resposta honesta: NAO recebeu, e a causa esta medida

| probe | resultado |
|---|---|
| handshake MCP completo no coord-mcp (:8765) + `coord_post` (status "probe SSE") | o MCP responde **OK** (o post foi publicado no bus) |
| `curl -N http://127.0.0.1:8090/api/events/stream` aberto durante o post | o SSE emite `init` + os `: heartbeat` proprios e **ZERO** linhas do coord-mcp (grep "coord" = 0) |
| `get_bus().publish("coord.heartbeat", ...)` de um script separado | tambem **nao chega** (grep "coord.heartbeat" = 0) |

## A causa: o EventBus e' in-process

- `jarvis.core.eventbus.EventBus.publish()` (eventbus.py:163) despacha os
  handlers **na memoria daquele processo**; `get_bus()` devolve o bus local.
- O SSE do webui so assina o `get_bus()` do **proprio** processo
  (webui/api.py:1064-1066, subscriber unico por conexao) e o handler
  empurra para as filas SSE (api.py:95-118).
- O `core/coord.py:498` (`_publish_bus_event`) **ja** publica
  `coord.post` e `coord.read` no EventBus — mas no processo do coord-mcp.

E os processos sao distintos:

| processo | pid | porta |
|---|---|---|
| coord-mcp (`python -m jarvis.coord_http`) | 295050 | 8765 |
| webui backend (`jarvis-webui`) | 3144191 | 8090 (loopback) |
| forward tailnet (Node `tailnet-v4-8090.mjs`) | 3172462 | 8090 (tailnet) |
| Agent Hub (Node `agent-hub.mjs`) | 3172460 | 8091 |

O `:8090` da tailnet e' um **forward TCP puro** (`down.pipe(up).pipe(down)`):
ele repassa bytes, mas nao conhece eventos — e o SSE e' one-way, entao um
cliente que conecta depois do post nao ve nada (e o `hub` que leria o SSE
precisa estar conectado antes).

**Logo: falta o TRANSPORTE.** Nao ha rota para um processo publicar evento
no EventBus de outro.

## O que falta (desenho, nao aplicado)

1. **No webui** (lane do webui): `POST /api/events` com `{topic, data,
   source}`, que chama `get_bus().publish(...)`. E' a unica piece que
   transforma "publicar de fora" em "publicar no bus de quem escuta".
2. **No coord-mcp** (`core/coord*`, claim desta lane): ao publicar um
   evento, fazer ALSO um POST no webui (`http://127.0.0.1:8090/api/events`),
   **fail-open** — o bus nunca pode depender do hub estar de pe.
3. **No Agent Hub** (Node): consumir o SSE do webui e repassar os eventos
   da frota (o resto da task t-2).

## Cuidado de seguranca que ja vale para o item 3

O hub hoje escuta em todas as interfaces **sem token** (medido: `ss` mostra
`*:8091`, o iptables aceita 8091 de `0.0.0.0/0`, e `POST /api/wake` devolve
200 sem credencial). O patch pronto esta em
`docs/auditoria/patches/agent-hub-auth-2026-11-15.patch` — aplicar **antes**
de expor o SSE da frota pela tailnet.
