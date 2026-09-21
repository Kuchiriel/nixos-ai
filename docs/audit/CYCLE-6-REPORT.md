# CYCLE-6 REPORT (21/09)

Suite: **1431 passed, 0 falhas** (+1 empty-cmd) / L8 WORLD OK / sem push.
1. Regras explícitas: SIM (R1/R3/R4 3/3).
2. Serializar independently: SIM (T4/S9 3/3).
3. Evidence purity: SIM c/ instrução (3/3); NÃO em loop (0/3+).
4. Composição causa colapso: SIM (atômicas ✓ → T8/L9 ✗).
5. Recovery falha sem serialização: SIM (R8 0/3 world; ação ok).
6. Serialização falha sem recovery: NÃO (S9 3/3) — é composicional.
7. P2→P3: composição com observações + regra-em-loop + fidelidade.
8. Estado externalizado: NÃO ajuda (X10A/B 0/3).
9. Menor unsolved: R8-shape (bytes exatos pós-recovery).
10. Horizonte máximo: 3 steps determinísticos (H2 3/3).
11. Model-specific: atração numérica, read-first, repr-hábito, variância.
12. Representation: R2/R5 dip, NUMBER decorações (tool-design geral!).
13. Composition: regra-em-loop, fidelidade, recovery→write.
14. Harness: crash vazio-cmd FIXADO; IndexError tardio: SITE REAL AQUI
    (Popen([]) em run_shell) — irmãos guardados; monitorar.
15. Próximo: formato de observação menos contaminante (experimento!) e
    R8-shape como regression permanente (menor failing honesto).
