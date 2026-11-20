# Tendência de precisão do auto-improve (20/11)

## Critério

Ampliar `MAX_REMOTE` de 1 para 2 só com **10 wakes desde a correção** e
**5 enqueues novos** do gerador, com precisão `executados/enqueues >= 0,8`.

## Medição

Snapshot: `~/.local/state/auto-improve-precision.jsonl` (6 linhas, wakes 5→10):

| wakes desde o fix | enqueues novos | executados | precisão | decisão |
|---:|---:|---:|---|---|
| 5 | 0 | 0 | null | KEEP |
| 6 | 0 | 0 | null | KEEP |
| 7 | 0 | 0 | null | KEEP |
| 8 | 0 | 0 | null | KEEP |
| 9 | 0 | 0 | null | KEEP |
| 10 | 0 | 0 | null | KEEP |

`--audit` confirma 10/10 wakes, 0/5 enqueues, precisão `null`, decisão
`KEEP_MAX_REMOTE_1`. A fila permaneceu cheia com tarefas enfileiradas
manualmente/dos sensores, então o gerador nunca precisou enfileirar — não
há evidência para medir precisão, e **não há evidência para ampliar**.

## Decisão

**Manter `MAX_REMOTE=1`.** O limite não foi alterado. A correção anterior
eliminou os 2 falsos positivos conhecidos (vago e stale), mas sem novos
enqueues não é possível afirmar melhora de precisão.

## Correções feitas nesta análise

- Idempotência do snapshot passou a comparar epoch em segundos: `--audit` e
  `--snapshot` leem o DB em instantes diferentes e os milissegundos variavam.
- Gate passou a exigir também `ENQUEUE_TARGET=5`, exposto no JSON do `--audit`.

ai-mesh: `58146bd`, `2801ccb`.
