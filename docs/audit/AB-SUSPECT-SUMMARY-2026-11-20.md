# A/B suspeitos — janela Task.project (19/11)

## Escopo e origem

Índice: `~/logs/ab_loop/marked/results-suspect-index-20261120-083910.json`.
Cópia marcada: `~/logs/ab_loop/marked/results.suspect-20261120-083910.jsonl`.
Original `~/logs/ab_loop/results.jsonl` intacto (sha `a8bbaf32…`).
Janela: `3f063d20` (03:23:42-03) até `9f5678e8` (10:58:11-03), 19/11.
Critério: registros com `nivel` e `ts` dentro da janela — **113 de 1119**
(10,1%). Todos têm `ck=v3`; isso não os torna válidos, porque o harness lia
0 tarefas (`Task.project` sem sufixo).

## Distribuição medida

| modelo | n | L1 | L2 | L3 | checker 100% ok | qualquer falha | infra |
|---|---:|---:|---:|---:|---:|---:|---:|
| api | 10 | 4 | 4 | 2 | 6 | 4 | 0 |
| bonsai | 53 | 4 | 45 | 4 | 4 | 47 (1 infra) | 1 |
| mtp | 50 | 4 | 44 | 2 | 2 | 42 (2 infra) | 4 |
| **total** | **113** | **12** | **93** | **8** | **12** | **97** | **5** |

Motivos (`motivo`): `checker` 103, `infra` 5, `review` 5.
`rc`: 109 com `rc=0`, 4 sem `rc` (todos `infra`).

## O que não vale mais

Nenhum dos 113 pode sustentar conclusão de acurácia: o verificador pode até
ter passado (12 registros), mas sem tarefas carregadas o resultado não mede o
modelo. Os 5 `infra` são ainda piores: falha de transporte/swap, não medição.
Os números antigos devem ser tratados como **suspeitos**, não como zero nem
como falha do modelo.

## Proposta de nova medição ck=v3 (sem reexecutar agora)

Gate do laboratório: checker de referência precisa passar 5/5 nos 3 níveis.
Plano mínimo para reconstruir a matriz com evidência válida:

1. **P1 — L2 (93 suspeitos, 3 células modelo×nível):** 5 amostras por célula
   (`api`, `bonsai`, `mtp`) = **15 execuções**. É onde estão 82% dos registros
   e de onde vêm as conclusões de chunking/dungeon.
2. **P2 — L1 e L3 (20 suspeitos, 6 células):** 5 amostras por célula =
   **30 execuções**, para fechar a matriz.
3. **Infra primeiro:** estabilizar `swap`/VRAM e repetir os 4 registros sem
   `rc` antes de qualquer medição; o registro `bonsai/L2` com `motivo=infra`
   e `rc=0` deve ser descartado por coerência (checker rodou mas a origem
   falhou).
4. Critério de aceite: `ck=v3`, `discovery_stats.returned>0` registrado no log,
   checker de referência 5/5 e pelo menos 5 amostras por célula. Resultados
   novos entram em `results.jsonl` com `nivel` correto; os antigos ficam
   apenas no índice de suspeitos.

Nada foi reexecutado nesta análise; ela é somente leitura sobre o índice e o
arquivo de resultados.
