# PLANNING HORIZON (Ciclo 5 — gradiente de evidência existente)

P1 single write (1 step): 12/12 (crashhunt) + 1395 suite. ✅
P2 read→count→write (3 steps): B0 4/5, B3 3/3, F0 0/3 (variante D). 🔶
P3 L9 full (8 rows + regra + malformada + 2 arquivos): 0/12. ❌

Colapso entre P2 e P3: regra arbitrária + fidelidade byte-exata +
malformada + 2 artefatos. Não é "contexto longo" (turns 7-8, longe do
teto); é composição (aplicar regra + serializar + evidenciar) sob
variância. Horizonte verificado máximo: ~3 steps encadeados (P2).
L10 mínimo: P3 com 1.deliverable (sem malformada) — isolar a variável
malformada vs regra vs fidelidade antes de subir.
