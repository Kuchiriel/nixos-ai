# EXACT MUTATION (Ciclo 8 — SR/M2/M6, n=2)

SR (world→there): f.txt exato 2/2. M2 (troca 1 linha): exato 2/2.
M6 (trailing-ws preservado): exato 2/2 ("keep   \nchanged\nend\n").
str_replace old/new exato = BYTE-FIEL (6/6) onde write_file
full-repro falha (0/3 E1). Evidência: modelo CAPAZ de mutação exata
quando o contrato reduz regeneração (spans pequenos). Reprodução
total (M1-shape) vs mutação (M2-shape): mutação vence. Sem repair
automático; sem conclusão de superioridade universal (M3/M4 não
testados — P2).
