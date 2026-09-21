# CHECKSUM (Ciclo 7 — S6D)

Comprimento esperado (37) + shell `wc -c`: não melhorou (0/3, igual R5).
Modelo não usou o número p/ corrigir (falha anterior, na geração).
Checksum como VALIDADOR funciona (checker); como GUIA não foi testado
(modelo nunca chegou a comparar). Não virou oráculo (37 não revela
conteúdo — ok). Conclusão: checksum não compensa átomo quebrado;
útil só pós-geração-correta (que já é verificada pelo checker).
