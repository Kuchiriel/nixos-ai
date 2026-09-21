# CAPABILITY GRADUATION (Ciclo 4 — modelo machine-checkable)

Uma capability NÃO gradua porque um teste passou uma vez. Estados:

- DISCOVERED: hipótese + 1 run observado (n=1 registra, não decide).
- REPRODUCIBLE: n≥3 mesma condição reproduz (variância anotada por classe).
- VERIFIED: world_check externo passa; sem stale (`stale_artifact:*`
  limpo); sem gaming (PHASE 10: placeholders, hardcode, stale, bypass).
- REGRESSION-PROTECTED: teste automatizado permanente (unit no sandbox
  ou host-integration marcado).
- MODEL-ROBUST: sobrevive a ≥2 variantes (wording/valores/paths).
- GRADUATED: contrato + verificação determinística + teste + taxonomia
  + atribuição documentados. Só aqui vira garantia arquitetural.

n justificado: n=3 separa ruído de padrão (EXP-E 3/3 sistemático vs
variância); n=5 p/ claims causais fortes (R1); n=1 nunca decide (H1).

| Capability | Estado | Evidência |
|---|---|---|
| RAG causal use | GRADUATED | R1 5/5 + 2 variantes; `benchmarks/kb_regression.py` |
| Lesson value-free | GRADUATED | B3 3/3 + R2 ranking; lint + teste |
| Tool restriction | GRADUATED | E2-only 9/9; `tool_surface` + teste |
| Outage≠empty | GRADUATED | emit + teste; VectorStoreError propaga |
| Stale≠success | GRADUATED | flag + 2 testes |
| Provider-empty STUCK | GRADUATED | guard + teste |
| Lesson lint transform | VERIFIED (mecânico) / PARTIAL (comportamental) | strip digits ok + teste; limpo 1/3 |
| Disclosure progressiva | REPRODUCIBLE | E6 n=1-3; threshold exato P2 |
| Grounding self-knowledge | VERIFIED | Gb 2/3; Ga 0/3 (limite mapeado) |
| Substrate auto-select | PARTIAL | probes E2 9/9; agente git 0/6 (probe→exec gap) |
| Context-loss persistence | VERIFIED | B0 0/3, B2/B3 3/3, UB 3/3 (PERSIST) |
| L9 multi-step | UNVERIFIED (capability) | 0/9; attractor+no-pivot+fidelidade; checker+runner permanentes |
| Long-horizon (Z) | UNVERIFIED | sem experimento |
| Cross-doc synthesis (S) | UNVERIFIED | sem experimento |
