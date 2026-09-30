# archive/ — nada aqui é apagado, e nada aqui é indexado no RAG

**Regra da casa (dono, 24/09):**
1. **NUNCA apagar.** Antes de mover qualquer coisa: *verificar* o que é.
   Não-versionado não é lixo (pode ser esquecimento de trabalho real);
   "duplicata" raramente é duplicata (pode ser o status de outro fork).
2. Destino é **sempre** um `archive/` correspondente (cria-se se não existir),
   com a data: `arquivo-assunto-AAAA-MM-DD/`.
3. Antes de arquivar: `rg "<nome-do-script>"` para confirmar 0 referência.
4. `.gitignore` + `.ragignore` deste repo listam o que é arquivo, para o
   índice do RAG não perder tempo com material arquivado.
5. **Veredito de arquivo** fica em commit ("arquivado X: Y referências,
   Z continua canônico") — arquivar sem registrar é entropia de novo.

Exemplos de arquivamento já feito:
- `bench-legacy-2026-09-25/`: 7 scripts de bench pré-`bench-llm.sh`
  (0 referências cada). Canônico continua `scripts/bench-llm.sh`.
