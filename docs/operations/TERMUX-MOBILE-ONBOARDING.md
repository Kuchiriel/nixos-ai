# TERMUX e Mobile Onboarding (opencode no celular)

> Objetivo: entrar na frota pelo tailnet com identidade clara, sem quebrar coordenação e sem confundir "porta aberta" com serviço saudável.
> Complementa: `docs/operations/COORD-PERSONAS-KANBAN.md` (coord/personas/kanban/Telegram).

## 1. Identidade e claim

- Origem: informe `termux`/celular no claim/contexto para a frota saber de onde você vem.
- Codinome: use o codinome da lane (nunca apelido pessoal do dono). Se o roster atribuir codinome por modelo, mantenha consistência com `agent-roster.py claim --model provider/id`.
- Contexto: declare o que está fazendo (escopo/arquivos/tarefa). Atualize quando o assunto mudar (`coord_set_context` ou fluxo equivalente).
- MBTI/persona (quando útil): pode registrar `--mbti`/`--persona` no roster para enquadrar o papel da tarefa atual; trate como papel fluido por tarefa, não identidade fixa.

Exemplo (ajuste ao seu modelo/tarefa):

```bash
# no host/repo, se tiver acesso ao script:
python3 scripts/agent-roster.py claim \
  --model provider/model-id \
  --mbti INTJ \
  --persona architect \
  --context "termux: tarefa X em repo Y"
```

Se estiver só com MCP remoto, use `coord_roster`/`coord_set_context`/`coord_claim` conforme exposto pelo servidor.

## 2. Acesso pelo tailnet

- `opencode serve` (host nixos-ai): `http://100.121.100.103:4599`
  - Use a UI/cliente apontando para esse endpoint no tailnet.
  - Autenticação/senha do `opencode serve` segue a configuração do host: não invente credenciais; use as que já existem no ambiente autorizado.
- Coord MCP (streamable-http): `http://100.121.100.103:8765/mcp`
  - Tools `coord_*`: bus, roster, workitems (`coord_workitem`), mensagens, pains, recall/health conforme exposto.
  - No opencode/cliente MCP remoto, configure `type: remote` com URL acima e headers de auth exigidos pelo host (ex.: `Authorization: Basic ...`) se aplicável.
- Conhecimento/jarvis-http (quando exposto): `:8766` foi reportado em contextos anteriores; confirme no host antes de depender (`coord_health`/config), pois a superfície pode variar.

## 3. SSH e confiança

- Acesso SSH é por chave já confiável (relação de confiança existente). Não gere nem publique chaves novas sem necessidade.
- Antes de assumir que o canal SSH está ok: teste a porta e a sessão; **PID vivo não prova serviço utilizável**.
- Não exponha IP público em logs/docs; prefira endereços tailnet internos e nomes de host.

## 4. Health por porta (regra prática)

- `nv-gate`: health correto é `GET /__gate/health` (ex.: `curl -fsS http://127.0.0.1:<porta>/__gate/health` no host). **`/health` não é o health local do gate** e pode ser relayado/travar; não usar para concluir queda.
- Serviços de LLM/embeddings/rerank escutam em loopback do host; do celular você não "vê" TCP direto como no host. Use `coord_health` (dentro do host) ou peça verificação por quem tem acesso local.
- Regra geral: **teste a porta/endpoint que responde de verdade**. `systemctl is-active`, PID ou socket "parecendo vivo" não bastam.

## 5. Kanban e coordenação (o que usar)

- Bus/roster/claims: fonte de coordenação da frota (`AGENTS-QUEUE.md`, `coord_*`, board).
- Kanban de execução: `coord_workitem` / `nightwatch.task_queue` (fila persistente). No Telegram: `/work [projeto]`, `/work stats|next`, `/work <id>`.
- Lista leve/A2A: `agent-roster task` (arquivo `.agents/roster.json`) é diferente do kanban de execução: não confundir.
- Antes de agir: leia estado real (`AGENTS-QUEUE.md`, roster, workitems) em vez de confiar só em wake antigo.

## 6. Cuidados operacionais

- Não rode `git push`, deploys, resets ou comandos destrutivos sem pedido explícito.
- Não commite segredos, tokens, chaves ou `.env`.
- Jobs pesados (GPU/build/bench): um por vez; respeite janelas noturnas e guards (`bench-qwen` 04:00, `swap-probe` 06:00 com condição).
- Se um serviço "sumiu": cheque journal/logs e endpoint correto antes de culpar config (OOM e queda silenciosa já aconteceram).

## 7. Checklist rápido (celular)

1. Tailnet conectado.
2. `opencode serve` acessível em `http://100.121.100.103:4599` (se for usar UI remota).
3. Coord MCP em `http://100.121.100.103:8765/mcp` respondendo handshake/tools.
4. Claim/identidade registrado (codinome, origem termux, contexto, modelo/MBTI se útil).
5. Confirmou health pelo endpoint certo (`/__gate/health` para nv-gate; `coord_health` para stack local).
6. Leu fila/board/workitems antes de pegar tarefa.
