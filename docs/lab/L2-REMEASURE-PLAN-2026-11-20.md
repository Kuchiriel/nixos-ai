# Plano de remedição L2 — 15 medições ck=v3 (20/11)

## Por que existe

113 registros por nível caíram na janela do bug `Task.project`
(`3f063d20`→`9f5678e8`, 19/11 03:23–10:58) e foram marcados `suspect`;
93 deles são L2. Mesmo os 12 com checker 100% ok são inválidos: o harness
lia 0 tarefas. Ver `docs/audit/AB-SUSPECT-SUMMARY-2026-11-20.md`.

## Gates medidos agora (sem executar medição)

`scripts/lab-l2-plan` (somente leitura) reportou **OK=5 FALHA=0**:

| gate | medição |
|---|---|
| controle do loop | `pause` |
| checkers de referência | 5/5 em L1, L2 e L3 (`prova_checkers.py`) |
| processos de dungeon | nenhum |
| residente sem cliente | `llm-swap.sh idle` rc=0 |
| `results.jsonl` | presente |
| índice de suspeitos | `results-suspect-index-20261120-083910.json` |

GPU no momento da medição: 847 MiB livres de 6141, com o 4B residente em
:8092 (3894 MiB) **sem cliente**. Não é janela livre para `lab restart`:
o residente precisa ser liberado/swap pelo próprio `llm-swap.sh` quando o
loop for armado. O `control=pause` e a ausência de processos são as provas
de que nada está medindo agora.

## Sequência exata (15 execuções, 3 braços × 5 amostras)

```bash
cd ~/projects/nixos-ai
scripts/lab-l2-plan              # revalida gates antes de qualquer coisa
lab doctor                      # reconfirma 5/5
lab level L2
lab restart                     # SOMENTE com janela GPU livre
for arm in api bonsai mtp; do
  for i in 1 2 3 4 5; do
    lab arm "$arm"               # 1 ciclo; esperar 1 novo registro ck=v3/L2
    # esperar até results.jsonl ganhar 1 linha com modelo=$arm, nivel=L2, ck=v3
    # timeout por amostra: LAB_TIMEOUT=900s
  done
done
lab pause                       # devolver GPU
```

## Critérios de aceite e abort

- Cada nova linha deve ter `ck=v3`, `nivel=L2`, `modelo` igual ao braço
  armado, `discovery_stats.returned>0` no log do ciclo e checker de
  referência 5/5.
- Duas linhas consecutivas com `motivo=infra` abortam a bateria: é problema
  de swap/VRAM, não do modelo.
- Se a voz do dono ocupar o residente (`llm-swap.sh idle` falhar), o loop
  adia sozinho; não forçar.
- Ao final, gerar resumo por braço (amostras, checker, patch_bytes, motivos),
  publicar no bus e marcar o antigo índice de suspeitos como substituído
  para L2 — sem apagar nada.

Este documento foi escrito sem reexecutar nenhuma medição.
