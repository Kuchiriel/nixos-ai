# SERIALIZATION (Ciclo 6 — T4/S9, n=3)

A direct-copy JSON exato: 3/3 (parse válido). S9 agente (records→JSON):
3/3. Independente de recovery: OK. Em composição (L9/T8): Python-repr
`[{'id':..}]` → gate barra → STUCK. Classificação: SERIALIZATION OK
atômica; em loop o modelo regride p/ repr (hábito de geração) =
COMPOSITION-LIMITED (não reasoning failure: semântica correta, sintaxe
errada — dispositions certas em write-0!). Sem auto-repair (decisão
Ciclo 5 mantida: serializar é do modelo).
