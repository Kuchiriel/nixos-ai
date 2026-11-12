# Exposição do coord_http (MCP na tailnet) e a auth que cabe (2026-11-09)

Tarefa da lane `vpnsec` (Arara), pedida por `opencode-matheus` em 06/11: o
`coord_http` ficou exposto na tailnet em `100.121.100.103:8765` sem auth, o
FastMCP remove o header `Authorization` antes das tools (então Basic por header
não trava), e o caminho seria token de bearer via `RemoteAuthProvider`. Aqui:
medição, risco e proposta.

## Medido (09/11, desta máquina)

| teste | resultado |
|---|---|
| bind do servidor | `100.121.100.103:8765` (só IP da tailnet, nunca `0.0.0.0`) ✓ |
| `POST /mcp` sem handshake | HTTP 400 `Missing session ID` → o request **passou**, não foi barrado por auth |
| handshake `initialize` sem auth | HTTP 200, devolve `mcp-session-id` ✓ |
| `tools/list` com esse session id, **sem auth** | **HTTP 200, 8.051 bytes** de schemas, começando por `coord_post` ✓ |
| `tools/list` com Basic (`Authorization: Basic ...`) | o mesmo resultado: o FastMCP **descarta** o header antes das tools ✓ |
| regra viva do nftables | **não consegui ler** (`nft list ruleset` não responde do meu shell, exit 4) → a barreira de rede não está confirmada por mim |
| config do firewall (NixOS) | `interfaces.tailscale0.allowedTCPPorts = [4599]` → **8765 não está na lista** da tailnet; a lista global também não tem 8765 |

Ou seja: **o MCP não tem auth própria**; quem alcança a porta enumera e chama as tools
(`coord_post`, `coord_msg`, `coord_read`, ...). A única barreira é a rede, e a config
diz que 8765 não deveria estar liberada na tailnet. Não posso afirmar o que está no
nftables vivo: **medido é o que o servidor responde, não o que eu espero que a regra
faça**.

## Risco

Com acesso ao MCP, um cliente controla a coordenação da frota: publica claims, manda
mensagens para os agentes e lê o bus. Combinado com o red-team do bus (hoje,
`docs/auditoria/BUS-REDTEAM-2026-11-09.md`), o caminho de dano concreto é:

- **negação de serviço na camada de coordenação**: um claim publicado com qualquer
  identidade bloqueia o dono legítimo do escopo (o detector de colisão confia no bus);
- **falsa impressão de estado**: o quadro do bus mostra agentes que não existem;
- **injeção de prompt no inbox**: **não** (medido: o `coord_pending` resolve a
  identidade do caller e ignora o payload, então nem `agent` forjado nem
  `sessionID` alheio entram na inbox de outro agente).

Ou seja, o dano real é **paralisar lanes e mentir no quadro**, não executar
instrução alheia.

## Proposta: a auth que cabe na tailnet

1. **Bearer token no `RemoteAuthProvider` (o caminho do SDK).** O MCP valida o
   header `Authorization` **antes** das tools, ao contrário do caminho Basic que o
   FastMCP neutraliza. Um token por agente, guardado **como hash** no roster: revogar
   um agente não derruba a frota, e a rotação é individual.
2. **Enquanto o bearer não entra, um middleware antes do MCP** (o
   `COORD_MCP_PASSWORD` que a Onca ofereceu): um segredo compartilhado lido do header
   **antes** do FastMCP, com fail closed. É uma linha de config e fecha a maior parte
   do risco hoje; não substitui o token por agente, mas compra tempo.
3. **A ACL do Tailscale continua como defesa em profundidade** (o servidor já escuta
   só o IP da tailnet ✓) e o bind não deve virar `0.0.0.0` por conveniência.
4. **Verificar a regra viva** do nftables (não consegui do meu shell) e confirmar que
   8765 e 8766 estão **fora** da lista da tailnet, como a config diz.
5. **Acoplar as duas correções**: com auth no MCP, o post de claim passa a poder
   amarrar a identidade ao caller (o MCP já sabe a lane pela sessão) → fecha também o
   "claim falso ocupa escopo" do red-team, sem depender de assinatura.

## O que não fazer

- **Não** usar Basic por header (medido: não trava).
- **Não** confiar na ACL como auth: ela é uma camada de rede, e o alvo do red-team é
  justamente o caminho de código que não checa nada.
- **Não** expor o MCP em `0.0.0.0` "para facilitar" (o bind na tailnet já funciona e
  é o que a fleet usa das outras máquinas).

## Reverificação 11/11: o contraste com o sistema que a auditoria está protegendo

Medido de novo hoje, da tailnet, **sem nenhuma credencial**:

| superfície | resposta | o que significa |
|---|---|---|
| `coord_http` (:8765), `POST /mcp` | HTTP 400, `Missing session ID` | **não pediu credencial**: o erro é de protocolo, não de auth |
| `jarvis_http` (:8766) | HTTP 406 | o mesmo: responde, sem auth |

E o contraste que importa para a decisão do dono: a lane da auditoria (Lontra,
Marco 4 de 11/11) pediu **senha do BasicAuth ou liberação de IP** para o dashboard do
**Arcane** (que tem whitelist de IP e BasicAuth ✓), enquanto a **coordenação da própria
casa** — o MCP que fala com a frota, com o bus e com as tools do dono — **não pede
credencial nenhuma** para quem estiver na tailnet ✓. O sistema auditado é mais fechado
que a casa.

Isso não é novo (é o red-team de 09/11 ✓) e a mitigação proposta continua a mesma e
continua **não aplicada**: auth de verdade no MCP, com a identidade amarrada ao caller
(o MCP já sabe a lane pela sessão ✓). O que o dado de hoje acrescenta é a comparação de
risco: pedir credencial para o Arcane e deixar o coord_http aberto é trocar o problema
mais chato pelo mais fácil de explorar.
