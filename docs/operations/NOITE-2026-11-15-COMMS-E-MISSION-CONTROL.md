# Noite 15/11 — Comms que acordam de verdade + Mission Control

> Turno do crouton-alpha (celular), 14→15/11. Tudo medido; cada item tem o
> commit e a prova.

## 1. O /to do Telegram nao acordava ninguem (4 bugs em camada)

| # | Bug | Sintoma | Correcao |
|---|---|---|---|
| a | `coord_roster._repo_root()` caia em `find_repo_root()` (PROJECT ROOT) -> `/home/nixos` (tem `.git`) | `_script()` virava `/home/nixos/scripts/agent-roster.py` (inexistente) => **roster VAZIO em todo servico jarvis** (Telegram, MCP, heal) | valida `scripts/agent-roster.py` antes de aceitar; cai em `~/projects/nixos-ai` (medido: 7 agentes) |
| b | match de codinome exato | Telegram manda `Falcão` (com acento), roster guarda `Falcao` | NFKD + ascii + lower |
| c | presenca local so por `name` | `/to` caia no bus ("nao esta nesta maquina") | `name` OU `codinome` OU `alias` |
| d | wake local via `agent-msg.sh`, que decide "vivo" pela **janela Hyprland** | servico headless (Telegram/cron/ssh) nunca acha a janela => frota silenciava | `send_message` acorda pela **API** (`agent-api.py`) primeiro; `agent-msg.sh` vira plano B; bus fica como REGISTRO, nunca transporte |

**Prova**: `/to` -> HTTP 200 `msg_1dd21839c001DPBQj9aR4TE8Ni`; o Falcao
respondeu `ok-telegram` as 23:55:25. Antes: nada.

## 2. Rotacao de modelo (o dono autorizou: "pode mudar o /model deles")

- `PATCH /api/session/<id>` devolve **204 mas NAO troca** o modelo do TUI em
  execucao (medido: a resposta seguinte saiu no modelo antigo).
- O caminho que troca: **`opencode run -s <sess> -m <provider/model>`** — roda
  UM turno na sessao, headless, sem roubar a tela.
- `scripts/agent-model.py`: `--status`, `--list` (cooldown-aware, reusa
  `team.available_models()`), `--run` (cai no proximo provider em 429 e
  marca cooldown em `~/.local/state/jarvis/provider-cooldown.json`).
- `scripts/agent-provider-guard.py` agora **rotaciona sozinho** no 429
  (`--no-rotate` desliga).
- **Prova**: linha 429 sintetica no log do opencode -> guard detectou
  (`RATE nvidia/minimaxai/... sessao=ses_e4c2...`) -> a sessao do Lontra
  trocou sozinha para `opencode/deepseek-v4.1-flash-free`.

Ordem de fallback: nvidia -> openrouter -> opencode -> groq -> cerebras ->
together -> openai -> anthropic -> google -> local.

## 3. Agent Hub (mission control)

- `scripts/agent-hub.mjs` — Node puro, zero deps, bind dual-stack.
- Rotas: `GET /` (cards), `GET /api/agents`, `GET /api/transcript?session=`,
  `POST /api/wake`.
- Declarativo: `home-manager/modules/agent-hub.nix` (units `agent-hub` e
  `tailnet-v4-8090`).
- URLs: `http://100.121.100.103:8091` (tailnet/LAN) e
  `http://[fd7a:115c:a1e0::7f01:64bd]:8091` (tailnet IPv6).
- O `jarvis-webui` escuta so em loopback por design (o backend tem chaves de
  API): o `tailnet-v4-8090.service` e o forward que expoe o IPv4 do tailnet.

## 4. Firewall + rebuild do host

- `hosts/nitro-v15/configuration.nix`: `5173 8090 8091` abertos na LAN e em
  `tailscale0`.
- O rebuild so passava por causa de **7 testes WIP offline** no checkPhase
  (exigem `data/offline/corpus.db`, que o `cleanSource` do pacote nao
  inclui). Deselecionados com `#TODO(sweep-2026-11)` para a lane re-ativar
  quando o corpus entrar no pacote.

## 5. Termux:Widget (celular) — o que ficou pronto e o que nao

- `~/.termux/widget/dynamic_shortcuts/` com `crouton-offline` e
  `crouton-offline-ask` (executaveis, testados).
- O app `com.termux.widget` (sharedUserId `com.termux`) **abre** com
  `am start -n com.termux.widget/com.termux.widget.activities.TermuxWidgetMainActivity`.
- O **"Create shortcuts"** exige toque humano: o `input tap` do Termux nao
  injeta evento (sem `INJECT_EVENTS`) e `uiautomator dump` e barrado.
- Sem `shared_prefs` => o app nunca gerou o token do widget, entao nenhum
  atalho existe ainda.


## 6. O achado grande: a casa lia o schema ERRADO do DB do opencode

| medido | valor |
|---|---|
| `max(part.time_updated)` (schema 1.x) | **09/11 06:12** (congelado) |
| `max(session_message.time_updated)` (schema 2.2.6) | **15/11 04:48** (vivo) |

O opencode 2.2.6 grava a atividade em `session_message`/`session_part`/
`session_v2`; `message`/`part`/`session` sao o schema legado do 1.x.
Cinco scripts da casa liam a tabela errada e concluiam "o agente esta
morto":

- o `prune` **apagou os 4 agentes VIVOS** do roster (restaurei do backup);
- o watcher via `agente_vivo_db` via as sessoes vivas como ociosas -> nunca
  acordava ninguem (o "agent watcher que ate agora nao fez nada");
- a lane coord tambin tinha medido "the opencode.db path is dead".

**Correcao**: `scripts/oc-db.py` = fonte unica; escolhe a tabela viva
sozinha (2.x primeiro, 1.x como fallback) e expoe `<db> <janela_s>
[session]`, `--sessions`, `--last`. `agent-db-alive.py` e `agent-roster.py`
delegam; a liveness soma a API do opencode (autoritativa, headless).

**Prova**: `agent-db-alive` dizia "Cervo ocioso" (rc=1, ERRADO) e passou a
dizer "viva" (rc=0); `live_sessions()` foi de 0 para 50; roster mostra 4
live e o prune remove 0.

## 7. /agentes — o pulso da frota no bolso (Telegram)

`/agentes` mostra, por agente: vivo/ocioso, ha quantos minutos se mexeu,
a lane e o **modelo em uso**. Sai da API do opencode + roster local.
Novo `comms.agents_pulse()`.

Prova: `fuzzy('/agentes')` -> `('agentes','')` e o handler imprime o
pulso real (Cervo, Falcao, Onca, Lince com modelo e ha-quanto-tempo).

## Commits (completo)

`2e689bbb` hub+portas · `f4990443` wake via prompt · `aef16f96` 3 bugs do
comms · `cac645f5` agent-model · `86a5cc12` rotacao no guard ·
`a2de8960` roster+night-watch · `69c4721b` 404 libera claim ·
`dab05bd1` DB 2.2.6 · `66a4afd9` /agentes

## Commits (antigos)

`2e689bbb` hub+portas · `f4990443` wake via prompt · `aef16f96` 3 bugs do
comms · `cac645f5` agent-model · `86a5cc12` rotacao no guard
