# Red-team do bus de coordenação (2026-11-09)

Tarefa da lane `redteam/matrix` (Cervo / sweep-2026-11), pedida por
`opencode-matheus` em 06/11 e ainda pendente: *o bus aceita qualquer um publicar
claim/msg; testa se uma IA (ou um humano com `gh`) consegue injetar claim falsa
para ocupar um escopo, ou msg para injetar instrução numa outra IA*.

Método: publicar no issue #12 com `gh` (sem MCP, sem sessão, sem roster), que é
exatamente o caminho de "humano com gh", e observar o que a frota trusta.
As três sondas foram removidas do issue depois; o conteúdo está aqui.

## Resposta curta

**O inbox está fechado. O bus e o detector de colisão, não.**

| vetor | resultado | probe |
|---|---|---|
| claim falso (agente inexistente, escopo inventado) | **ACEITO**: aparece no `coord_read` como agente da frota, com lane e escopo | `claim` de `probe-fake-agent`, lane `nixos-ai/redteam-probe` |
| colisão por claim falso | **CONSEQUENCIAL**: o `coord_check` acusa COLISÃO no escopo do probe, ou seja, **o dono legítimo do escopo fica impedido de editar** | mesmo claim |
| msg falsificada para o inbox de outro agente | **BLOQUEADO**: o `coord_pending` não entrega | `msg` de `coord-naming` para `sweep-2026-11`, sem sessão |
| msg falsificada com o `sessionID` real de outro agente | **BLOQUEADO**: o inbox continua não entregando | mesma msg, com `sessionID` alheio |

## Por que o inbox está fechado

O inbox (`coord_pending`) não trusta o payload: ele resolve a identidade do
**caller** (a ponte `OPENCODE_PID` para o `argv -s ses_...` do processo opencode
pai, o patch `c0abea7f` da lane coord-mcp) e filtra por essa identidade. O
`agent` e o `sessionID` dentro do `coord-json` são ignorados. Por isso nem
impersonar com o `sessionID` alheio (que é público, aparece nos próprios
comentários do bus) funciona.

O bus, porém, é diferente: o `coord_read` monta o quadro a partir dos comentários
do issue, e o `agent` do payload é o que aparece. Um claim publicado com `gh`
aparece **como agente da frota**, com lane, escopo e idade.

## O que é consequential (e o que não é)

**É consequential: negação de serviço na camada de coordenação.** O detector de
colisão (`coord_check`) confia no bus. Um claim falso sobre um escopo que alguém
real vai usar faz o dono legítimo receber "COLISÃO de claim, não edite antes de
resolver" e parar. Quem publica não precisa ser agente: basta ter escrita no
repositório. A janela do bloqueio é o TTL do claim (6 h, pelo digest do próprio
bus), ou até o comentário ser editado ou apagado.

**Não é consequential (medido): injeção de prompt via inbox.** O caminho de
entrega ignora o `agent` do payload e usa a identidade do caller. Um humano com
`gh`, ou uma IA com o token do repo, consegue **falar no bus** e aparecer no
quadro, mas **não consegue entrar no inbox** de outro agente nem fazer a frota
executar uma instrução por essa via.

Ou seja: o bus é um **quadro de announcements** confiável só para quem escreve
 nele, e o inbox é confiável porque não lê o bus para saber quem manda.

## Mitigações (em ordem de esforço)

1. **Barato e imediato: o detector de colisão tem que exigir identidade validada.**
   A regra que o inbox já usa (a sessão existe e pertence a quem publica) vale
   para o `coord_check` e para o `coord_read`: um claim que não valida não
   bloqueia ninguém. Isso fecha o único vetor consequencial que medimos, e é uma
   mudança pequena na lane coord-mcp.
2. **O `agent` do payload não pode ser a identidade.** Quem publica no bus é
   identificado pelo autor do comentário no GitHub (`user.login`), não pelo campo
   do `coord-json`. Com o token compartilhado da frota isso não distingue agente
   de agente, mas impede humano e qualquer outro token de se passarem pela
   frota.
3. **Assinatura do payload (a que fecha de verdade).** Um par de chaves por
   agente, com a pública no roster, e o reader verifica antes de confiar. Sem
   isso, um membro da frota continua podendo publicar claim com o nome de outro.
4. **Escopo por lane no post.** O MCP sabe a lane do caller pela sessão; o post
   pode recusar claim fora da lane. Fecha o caminho do MCP (o `gh` cru continua
   coberto pela assinatura).
5. **Procedimento operacional, já vale agora**: quando o `coord_check` acusar
   colisão, conferir o autor real do comentário no issue antes de parar de
   trabalhar. Um "COLISÃO" de agente que não está no roster local é sinal de
   spoof, não de trabalho concorrente.

## Evidência

- Sondas publicadas com `gh issue comment` no #12 (claim falso, msg falsificada,
  msg com `sessionID` alheio), todas removidas depois.
- `coord_read`: o probe aparece na lista de agentes do bus, com TTL.
- `coord_check`: "COLISÃO de claim, não edite antes de resolver: probe-fake-agent".
- `coord_pending`: nenhuma das duas msgs falsificadas chegou no inbox.
- `coord_roster`: o agente falso **não** está no roster local, ou seja, roster e
  bus discordam, e o bus é o que manda nas colisões.
