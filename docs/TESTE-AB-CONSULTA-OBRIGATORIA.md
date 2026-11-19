# Plano de Teste A/B — Consulta Obrigatória antes de Ação

Objetivo: medir se forçar a consulta de MCP (rehydrate/recall/rag_search/lessons)
antes de ações de decisão reduz retrabalho, erros repetidos e "bater cabeça".

## Hipótese

Grupo B (com guarda plugin ativo) terá:
- menos erros repetidos (mesmo erro duas vezes)
- menos ações de decisão sem consulta prévia
- mesmo ou menor tempo médio para resolver tarefas (menos retrabalho compensa o tempo da consulta)

## Design

| | Grupo A (controle) | Grupo B (tratamento) |
|---|---|---|
| Plugin consulta-obrigatoria | INATIVO (OPENCODE_NO_CONSULT_GUARD=1) | ATIVO |
| Regras injetadas no system prompt | Sim (memory.js) | Sim (memory.js + consulta-obrigatoria) |
| Ação de decisão sem consulta | Liberada | Barrada com erro claro |
| Bypass | N/A | OPENCODE_NO_CONSULT_GUARD=1 |

## Métricas a coletar (por sessão)

1. `acoes_decisao_total` — número de ações de decisão (bash destrutivo, edição, coord_post, spawn)
2. `acoes_sem_consulta` — ações de decisão sem consulta prévia (Grupo B: 0 por construção; Grupo A: medir)
3. `erros_repetidos` — mesma falha (mesmo stderr/código) ocorrendo 2+ vezes na sessão
4. `tempo_resolucao` — tempo da primeira tentativa até a resolução da tarefa
5. `consultas_mcp_por_sessao` — número de chamadas a jarvis_* de consulta
6. `bypass_usado` — número de vezes que OPENCODE_NO_CONSULT_GUARD=1 foi usado (sinal de atrito)

## Como implantar

### Passo 1: Ativar o plugin (Grupo B)

O plugin ja está linkado em ~/.config/opencode/plugins/consulta-obrigatoria.js.
Para ativar, reiniciar o opencode (ou `opencode reload`).

### Passo 2: Coletar baseline (Grupo A, 1 semana)

Rodar com o plugin INATIVO e coletar as métricas acima via:
- `scripts/agent-pains.sh` (captura erros de tool)
- `~/.local/share/opencode/opencode.db` (sessoes e mensagens)
- `scripts/oc-db.py` (fonte unica de atividade)

### Passo 3: Ativar o Grupo B (plugin ativo)

Mesma coleta de métricas, comparando com o baseline.

### Passo 4: Decisão

Se Grupo B tiver:
- `erros_repetidos` reduzido >= 30% E
- `falsos_positivos` (read-only barrado) == 0 E
- `tempo_resolucao` não aumentado > 15%

→ Manter o plugin ativo para todos.

→ Caso contrário, ajustar os padrões de bloqueio (STATE_CHANGE_RE / ACTION_MCP_RE).

## Teste unitário (já feito)

`scripts/test_consulta_obrigatoria.py` — 15 casos, 15 passam, 0 falsos positivos, 0 falsos negativos.
Valida a lógica de decisão isoladamente (sem depender do opencode rodando).

## Regras da casa (P0)

Antes de qualquer comando que já falhou: ler ai-mesh/docs/ARMADILHAS.md.
Erro novo: pare, meça, ache causa, corrija, prove, registre, só então continue.
Erro repetido = correção anterior estava errada.
