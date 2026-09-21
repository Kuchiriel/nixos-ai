# L9-SPEC — knowledge-persistent multi-step execution (Ciclo 4)

L8 congelado como regressão. L9 testa capability emergente dos Ciclos
1-3 (não "L8 mais difícil"): usar conhecimento descoberto + lidar com
complicação + artefato persistente verificado.

## Objetivo
Dado um workspace com `inventory.csv` + `manual.txt` (regra arbitrária,
ausente dos pesos), produzir `report.json` + `summary.txt` corretos.

## Mundo inicial (gerado por fixture, único por run)
- `inventory.csv`: 8 linhas `id,code,status` (6 válidas: 3 ok, 3 broken
  c/ prefixos mistos; 1 malformada (campo faltando); 1 broken QX).
- `manual.txt`: regra — broken c/ code `QX*` → `quarantined`; outro
  broken → `repaired`; ok → `ok`; malformada → `skipped` + reason.
- `report.json`: [{id, disposition, evidence}] — evidence = linha CSV
  exata (anti-fabricação). `summary.txt`: `ok=N repaired=N
  quarantined=N skipped=N` + linha `observed-from-files` (fatos lidos)
  vs `inferred` (a regra aplicada).

## Tools permitidas
Agent schema padrão (+execute_shell). Jail: /tmp/l9-run-{i} + leitura
do workspace. ESCRITA NO REPO PROIBIDA (R6).

## Complicação controlada
Linha malformada: sem ela o task é trivial; com ela o agente precisa
classificar `skipped` sem quebrar o run nem inventar campos.

## World checker (`l9_check.py`, determinístico)
Recomputa dispositions da regra + CSV; compara evidence byte-a-byte;
valida counts; falha em placeholder/hardcode (evidence ≠ linha real),
stale (dir único + rmtree), arquivo ausente.

## Shortcuts proibidos
Ler resposta do prompt (regra só em manual.txt); copiar exemplo;
fabricar evidence; pular malformada sem `skipped`.

## Sucesso
`l9_check.py` exit 0. Falhas taxonomizadas: wrong-tool, no-read,
rule-miss, malformed-mishandled, fabricated-evidence, incomplete,
stale, timeout.

## Status
Spec v1. Runner `/tmp/l9/run_l9.py`. n=3 inicial.
