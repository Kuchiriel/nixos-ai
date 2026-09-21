# R8 EXACT-STATE BOUNDARY (Ciclo 7)

E1 exact-copy (sem recovery): 0/3. Padrões: decorações ("1 | ") vazam;
trailing-space some; tab vira ", "; newline final some; unicode ok-ish.
R3 decisão-recovery (escrever NOME): 3/3. R4 recovery+constante: 3/3.
B4 alternativa explícita: 3/3. R5 (R8 canônico): 0/3.
S9 JSON-ASCII 3/3 e H2 3/3 passam (bytes triviais); E1 com
unicode/trailing/tab/newline zera. Fidelidade degrada com
complexidade-de-byte, não com recovery.
BOUNDARY: byte-fidelity é o átomo quebrado (independente); recovery
funciona (9/9 R3/R4/B4). R5 = recovery(ok) + bytes(fail).
