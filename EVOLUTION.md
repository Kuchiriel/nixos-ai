# EVOLUTION — melhoria contínua do ecossistema de IA

> Backlog explícito de capacidade (não defeito). O nightwatch lê itens com `**Status**: TODO` via `discover_evolucao`.
> Regra: cada item precisa de alvo concreto (`**Arquivos**`), critério verificável e escopo pequeno.

## P2 — Capacidade e iteração

### P2-1: Expor razão de fila vazia com origem das fontes de descoberta
- **Status**: TODO
- **Arquivos**: modules/ai/jarvis/src/nightwatch/harness.py
- **Tipo**: capability
- **Critério**: quando a run termina sem tasks, registrar no resultado/progresso quais fontes retornaram 0 (scripted/llm/missao/evolucao) e quantos itens foram descartados por falta de alvo ou dedupe, para distinguir "nada a melhorar" de "descoberta cega".
- **Teste**: `python3 -m py_compile modules/ai/jarvis/src/nightwatch/harness.py` e simulação/unit da contagem em execução de descoberta.

### P2-2: Ingerir docs/pains recentes como candidatos priorizados
- **Status**: TODO
- **Arquivos**: modules/ai/jarvis/src/nightwatch/categories/__init__.py
- **Tipo**: capability
- **Critério**: novo discoverer lê `docs/pains/pains.jsonl` (assinaturas recentes/deduplicadas) e gera tasks acionáveis quando houver arquivo/alvo identificável, sem duplicar assinaturas já resolvidas no mesmo dia.
- **Teste**: teste com arquivo pains temporário e `python3 -m py_compile modules/ai/jarvis/src/nightwatch/categories/__init__.py`.

### P2-3: Rodada noturna bounded com relatório de progresso mensurável
- **Status**: TODO
- **Arquivos**: modules/services/nightwatch-timer.nix, docs/operations/SCHEDULE.md
- **Tipo**: capability
- **Critério**: timer/serviço com janela e limites de recurso documentados, emitindo resumo (tasks tentadas/concluídas/bloqueadas, commits, motivo de parada) em log/journal e artefato de estado, sem contenda com uso ativo de GPU.
- **Teste**: `nix eval` do módulo e checagem de consistência entre config declarativa e documentação.
