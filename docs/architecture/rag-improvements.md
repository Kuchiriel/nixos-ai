# RAG — Melhorias pesquisadas (2026)

> Compilado durante a Fase 4 como insumo para a próxima iteração. O objetivo
> não é "espelhar o legado" a qualquer custo, mas evoluir o RAG do JARVIS com
> o que há de melhor para **RAG de código, local-first, CPU/GPU modesta**.

## O que já está implementado (Fase 4)

- **Busca híbrida nativa do Qdrant**: prefetch dense + sparse (BM25) com fusão
  **RRF** ponderada no dense (`weights: [5.0, 1.0]`) — espelho do comportamento
  dense-dominante do legado V4.0.5.
- **Field boosting** (filename sovereignty, palavra em filename/path, extensão
  alvo) — equivalente ao "hybrid + field boosting" dos benchmarks.
- **`modifier: idf`** no sparse vector do Qdrant (≈ BM25 real, frequência × IDF)
  — adicionado na iteração pós-pesquisa.
- Migração one-shot do índice NumPy legado + teste de paridade (overlap ≥ 0.8).

## Referências (pesquisa 08/2026)

1. **Hybrid Search for RAG (denser.ai, jun/2026)** — benchmarks WANDS: BM25
   0.6983, dense 0.6953, híbrido RRF 0.7068, **híbrido + field boosting 0.7497**.
   Dois estágios híbrido + reranker neural → Recall@5 0.816 em documentos
   financeiros. RRF k=60 é o default robusto; ponderado só com eval.
2. **RAG Chunking Strategies 2026 (digitalapplied.com, mai/2026)** — chunking
   errado custa até **9% de recall** (Weaviate). Default pragmático: **recursive
   512–1024 tokens**. **Overlap contestado** (arXiv 2601.14123, jan/2026): sem
   benefício medível, só custo — tratar como tunable. Context cliff ~2500 tokens.
   Semantic chunking é ~14× mais lento; late/contextual chunking são os upgrades
   de alto valor (Anthropic: −67% falhas top-20 com reranking).
3. **The Complete Guide to Hybrid Search (2026)** — 3 estágios: dual retrieval →
   RRF → **cross-encoder reranker** (top-50–200 → top-3–5).

## Melhorias propostas (próximas iterações, em ordem de impacto/custo)

| # | Melhoria | Custo | Ganho esperado | Fase |
|---|---|---|---|---|
| 1 | **Chunking por símbolo/função** (índice por função/classe em vez de arquivo inteiro; facts já existem) | Médio | Recall p/ perguntas de código; chunks legíveis ("human readability rule") | Fase 4.x |
| 2 | **Reranker cross-encoder local** (ex: bge-reranker ou modelo pequeno GGUF via llama.cpp) nos top-50 → top-5 | Alto | Maior precisão no final (benchmark: Recall@5 0.816) | Fase 4.x |
| 3 | **Late/contextual chunking** (embedar doc inteiro, depois dividir; contexto do arquivo nos chunks) | Médio | Menos perda de contexto entre chunks | Fase 4.x |
| 4 | **Pesos RRF tunados com eval** (split train/val das queries; hoje 5:1 heurístico) | Baixo | +NDCG se o dense realmente dominar no corpus de código | Fase 4.x |
| 5 | **BM25 com k1/b ajustados p/ código** (termos curtos; k1 menor p/ identificadores) | Baixo | Precisão em símbolos/identificadores | Fase 4.x |

## Notas específicas de código (RAG de código)

- **Identificadores exatos** (nomes de função, símbolos, caminhos) → BM25/sparse
  é crítico; embeddings sozinhos falham neles. O sparse + `modifier: idf` já cobre.
- **Paridade com o legado** é um teste de regressão do lab; no host, o fluxo é
  `jarvis index` (Qdrant nasce limpo) — não reutilizar a migração one-shot.
- O chunk ideal para código tende a ser a **função/classe** (o legado embebia o
  arquivo inteiro, diluindo símbolos pequenos). `get_symbol_block` do V4.0.5 já
  extrai o bloco — base para o chunking por símbolo.

---
**Ver também:** [[../../HANDOFF]] | [[../../AGENTS.md]] | [[../../README]]
