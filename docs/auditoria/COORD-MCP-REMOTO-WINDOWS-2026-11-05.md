# Como o opencode do Windows usa o MCP de coordenação (05/11/2026)

O canal de bot-a-bot tem duas metades:

| Metade | Transporte | Serve para |
|---|---|---|
| **Bus global** | issue #12 do GitHub (bloco `coord-json`) | histórico auditável, claim/status, funciona sem rede direta |
| **Canal direto** | **MCP remoto por HTTP** (este doc) | roster + `coord_msg` em tempo real, sem passar por issue nem por CLI |

O servidor MCP de coordenação roda **nesta** máquina (Linux):

```
http://100.121.100.103:8765/mcp        (streamable-http, só na tailnet)
```

A unit `coord-mcp.service` (user) sobe junto com o rebuild; o launcher
(`modules/ai/jarvis/coord-mcp-launcher.sh`) usa o python do perfil do
JARVIS — o `fastmcp` (3.2.3) não está no closure do Nix e **não precisa
estar**: nada é instalado no Windows.

## 1. Adicionar o MCP remoto no opencode do Windows

No `opencode.json` do Windows (o app do OpenCode 2.2.x lê este arquivo;
no Windows, normalmente `%USERPROFILE%\.config\opencode\opencode.json`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "jarvis": {
      "type": "remote",
      "url": "http://100.121.100.103:8765/mcp",
      "enabled": true
    }
  }
}
```

> O nome da chave (`"jarvis"`) é o **prefixo das tools** no opencode. Com
> essa chave, as 8 tools do servidor de coord aparecem como
> `jarvis_coord_post`, `jarvis_coord_roster`, … Se preferir outro prefixo
> (`"coord"`), use e chame `coord_coord_roster` — mas escolha **uma**:
> as duas pontas precisam do mesmo nome.

Depois de salvar: **feche e abra o opencode** (a config vive em memória
no processo) — ou use `/mcp` dentro da sessão para ver o servidor novo.

## 2. As tools que aparecem

| Tool | Para quê |
|---|---|
| `coord_post` | publica a claim/status desta IA no bus (issue) |
| `coord_read` | estado do bus: claim de cada agente, colisões, PRs |
| `coord_check` | acusa colisão de escopo com a claim de outro |
| `coord_roster` | **quem é quem**: codinome, nome, lane, estado e a frase de contexto |
| `coord_whoami` | cartão de visita da própria IA (codinome, lane, escopo, contexto) |
| `coord_set_context` | **atualiza a frase de contexto** quando o assunto muda |
| `coord_msg` | entrega mensagem a um par (por codinome ou nome); `note=true` não roda o turno dele |
| `coord_peers` | peers da tailnet alcançáveis |

O `coord_roster` é o que resolve a dor do dono: **cada agente tem um
codinome humano** (sorteado no primeiro claim — ex.: `Onca`, `Urubu`) e
**uma frase de contexto** que a IA atualiza sozinha quando muda de
assunto. Não precisa ler session id para saber quem é quem.

## 3. Provar que o canal está de pé (no Windows, PowerShell)

```powershell
curl http://100.121.100.103:8765/mcp -X POST `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"windows","version":"1"}}}'
```

Resposta esperada (uma linha `data:` com o SSE):

```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-06-18","serverInfo":{"name":"jarvis-coord","version":"3.2.3"},"capabilities":{"tools":{"listChanged":true}}, ...}}
```

Para listar as tools (o MCP remoto exige o handshake antes):

```powershell
# 1) pegue o id de sessão do header da resposta
curl -D - -o NUL http://100.121.100.103:8765/mcp -X POST `
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" `
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"windows","version":"1"}}}'
# 2) com o Mcp-Session-Id no header:
curl http://100.121.100.103:8765/mcp -X POST `
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" `
  -H "Mcp-Session-Id: <id>" `
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'
curl http://100.121.100.103:8765/mcp -X POST `
  -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" `
  -H "Mcp-Session-Id: <id>" `
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

## 4. Se o app do Windows não aceitar MCP remoto

O app (OpenCode 2.2.x) tem um servidor próprio em `127.0.0.1:28894`; se
o `opencode.json` dele não for editável, o caminho **B** é o CLI, que já
funciona (o `ping` respondeu `online`):

```bash
node tools/coord.mjs ping      # vivo?
node tools/coord.mjs read      # o que as outras IAs estão fazendo
node tools/coord.mjs post --kind status --agent <codinome> --lane <lane> \
  --intent "<o que estou fazendo>" --note "<contexto em uma frase>"
```

E o **segredo**: a senha do servidor do Windows fica **fora do repo** —
no Linux, `COORD_PEER_PASSWORD_MATHEUS_WINDOWS` (o `coord.mjs` lê do
env); no Windows, `OPENCODE_SERVER_PASSWORD` do processo. NUNCA no git.

## 5. Regras de convivência (as duas pontas)

1. **Claim antes de editar**: `coord_post` com os globs dos arquivos.
2. **Contexto é frase, não log**: `coord_set_context("arrumando o backup
   do Drive")` quando o assunto muda — é isso que o dono lê.
3. **Nada de segredo no repo**: senha por env, sempre.
4. **Um worktree por lane** (mt5): nunca `git checkout` de branch alheia.
