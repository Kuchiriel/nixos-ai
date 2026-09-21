# COMPOSITION LADDER (Ciclo 7 — B1..B6 + H2/H5/H6)

B1 (2-step read+write = E1): 0/3 com bytes tricky. B2 (3-step = H2):
3/3 bytes triviais. B3 (+branch = H5): 2/3. B4 (+failure explícita):
3/3 (detecção funciona!). B5 (+recovery = R4/H6): 3/3 simples, 1/3
c/ transform. B6 (+exact bytes = R5): 0/3.
Transição precisa: tudo passa até B5-simples; colapso em B6
(bytes exatos) e parcial em branch/transform. H2→H5→H6: 3/3→2/3→1/3
(degradação gradual, não cliff). P2→P3 = B5→B6 + regra + evidência.
