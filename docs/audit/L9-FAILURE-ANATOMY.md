# L9 FAILURE ANATOMY (Ciclo 5 — 3 trajetórias + forense)

## T1 base-1/base-2 — attractor-fixation (PIVOT FAILURE)
| Turno | Decisão | Tool | Observação | Efeito mundo |
|---|---|---|---|---|
| 0 | explorar | list_directory | workspace: csv+manual | nenhum |
| 1-2 | ler regra | read_file ×2 | manual (QX etc.) | nenhum |
| 3 | **plano: CSV→JSON tool** | build_json_dataset | **ERROR: schema ausente** | nenhum |
| 4-5 | retry mesma tool | build_json_dataset ×2 | ERROR ×2 | nenhum |
| 6 | declara STUCK | — | honesto pós-fix | nenhum |
**Primeiro ponto recuperável: turno 4** (após 1º ERROR "schema não
encontrado", evidência clara + write_file disponível). Modelo repetiu
em vez de pivotar → PIVOT FAILURE, não planning (plano inicial era
razoável: a tool casa com "CSV→JSON") e não harness (ERROR explícito).

## T2 base-0 — desistência sem pivot (PIVOT FAILURE)
Mesmos turnos 0-3; turno 4+: mais reads + declara "cannot proceed".
Evidência observada corretamente, conclusão verbalmente precisa, mas
zero tentativa alternativa (write_file direto) → PIVOT FAILURE.

## T3 write-0/write-1 — sem attractor, ainda falha (MODEL)
Sem build_json_dataset no schema: write-0 escreveu 2× (dispositions
corretas!) mas evidence com números de linha + terminou emitindo JSON
como texto (fidelidade de evidência + acabamento). write-1: read-loop
+ str_replace em arquivo inexistente + 1 write → turnos esgotados
(PLANNING: nunca estabeleceu "escrever os 2 arquivos cedo").

## T4 forense — VERIFIED vácuo (HARNESS, FIXED)
build_json_dataset ok=True sem artefato → completion VERIFIED sem nada.
Fix: `{"ok":false}`→ERROR (tool-honesty), validado: zero vácuo pós-fix.

## T5 write-2/Gb-0 — crash tardio (HARNESS, OPEN)
`list index out of range`, turns=0 registrado, arquivos escritos antes.
Trabalho perdido. 3 sites `choices[0]` guardados; site real TBD.

## Classes (§PHASE 2)
- A Planning: write-1 (sem plano de escrita), T3-parcial.
- B Pivot: base-0/1/2 (evidência clara, sem troca de estratégia).
- C Harness: T4 (fixed), T5 (open).
