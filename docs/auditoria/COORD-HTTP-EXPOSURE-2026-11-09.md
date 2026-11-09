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
