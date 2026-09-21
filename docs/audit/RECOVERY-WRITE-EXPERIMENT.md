# RECOVERY→WRITE (Ciclo 7 — R3/R4/B4/R5, n=3)

R3 (qual arquivo existe → escrever NOME): 3/3, turns ~4.
R4 (recovery → escrever "FOUND"): 3/3, turns 6.
B4 (alternativa explícita): 3/3, turns 7.
R5 (recovery → bytes exatos): 0/3 (rec=True nos 3; wrote falha).
Separação (PHASE 12): recovery_success 9/9 (R3/R4/B4) + 3/3 (R5 rec);
byte_fidelity 0/6 (E1+R5); world = AND dos dois. Pivot≠recovery≠world:
pivot (troca) 3/3 em R5, recovery (alternativa achada) 3/3, world 0/3.
Runner: /tmp/c7/run_c7.py. Status: VERIFIED.
