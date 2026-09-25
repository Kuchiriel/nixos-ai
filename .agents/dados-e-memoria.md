# Dados e memória (CARREGUE SÓ SE O GATILHO CASAR)

Gatilhos: RAG, memória, vault, qdrant, collection, embedding, recall,
space, cifrado, backup.

## Coleções de produção (nunca apagar/renomear)
`code_index`, `memories`, `books`, `vault` + `pessoal_*`, `moe_*`,
`qwen4b_*`. `memories` é a memória viva do agente.

## Limpeza de dado
`core.safe_archive.archive_then_delete()`: copiar → ler de volta →
conferir contagem e hash → remover. `safe` só é True com `verified` e
`removed == requested`. `dry_run=True` por padrão. IDs explícitos.

## Armadilhas já pagas (não repita)
- **Manifest mentindo**: `rag.py` gravava o manifest *antes* de indexar;
  arquivo em quarentena ficava marcado e nunca mais era retryado.
- **Vault fora das read roots**: o agente era cego para a própria memória.
  `devtools._safe_path` agora tem o vault como read-root (leitura só).
- **Embeddings 512 tokens**: acima disso o servidor devolve 400/500.
  `providers/embedding.py` faz chunk (1200 chars) + mean-pool L2.
- **Testes sujando Qdrant**: `conftest` cria coleção única por execução
  (padrão Testcontainers: unique names em vez de cleanup).
- **Cifragem é opt-in**: `JARVIS_VAULT_ENC=1` + chave por space. O vault
  principal fica em **texto puro** por design.
- **Código no ar ≠ commitado**: sessão longa mantém o `.py` antigo.

## Modelo de memória (mercado 2026, verificado)
RAG = busca difusa sobre corpus **que você não escreveu** → vetor.
Memória escrita pelo agente → **filesystem/markdown** (endereçamento
exato, mutação in-place, ordem preservada). Não misture os dois índices.
Etapas: Storage → Reflection → Experience. Falta Reflection/Experience;
`core/consolidate.py` faz merge/supersede/heat em modo **read-only**.

## Referência
`vault/memoria-padrao-vs-nosso-2026-09-25.md`, `docs/PROMPT-AGENTE-EXTERNO.md`
