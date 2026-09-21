# CYCLE-8 REPORT (21/09)

Suite: **1431 passed, 0 falhas** / L8 WORLD OK / sem push.
1. Primeira divergência: ARGUMENTO do modelo (disk==arg 100%).
2. Corrupção: model-generation (F6/F7/F8/CPRO) + presentation
   (TR-F4/F13); protocol/tool/FS inocentados.
3. Classes: misto/repetido-ws, blanks, newline-final, CRLF (1/2).
4. ASCII ordinário: SIM (F1/F2/F3/F5/F10-17).
5. Whitespace: SÓ isolado (F4/F5 ✓; F6/F7/F8 ✗).
6. UTF-8: SIM isolado (F10/F11/F12).
7. Mutação exata mesmo sem reprodução: SIM (SR/M2/M6 6/6).
8. str_replace muda fidelidade: SIM (6/6 vs E1 0/3).
9. Payload menor: ajuda se trivializa bytes (H2/S9); não se tricky.
10. Presentation contamina: SIM (loop falha onde probe passa).
11. Outra representação: hex/base64 emitidos 2/2; sem decoder (não construir).
12. base64/hex desnecessários: structured-edit resolve sem codificar.
13. Reprodução exata NÃO é requirement legítimo do modelo quando
    primitiva determinística existe (TASK-DESIGN-LIMIT).
14. Modelo: operação + spans; harness: bytes + verificação.
15. Menor unsolved restante: E1-shape via write_file (by design — usar
    str_replace é a resposta arquitetural, não o fix do benchmark).
16. Referência externa: BLOCKED (NIM 6× timeout; sem resultado inventado).
