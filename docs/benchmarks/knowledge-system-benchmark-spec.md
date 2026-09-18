# BENCHMARK SPEC — Knowledge System multidimensional (18/09)

> Especificação de benchmark pós-ingestão. Objetivo: provar que a ingestão
> tornou o sistema MENSURAVELMENTE mais capaz, e que isso é reexecutável.
> Não é script solto — categorias abaixo viram testes em
> `modules/ai/jarvis/tests/test_architecture_invariants.py` + futuros E2E.

## Princípio
Não medir "Qdrant funciona" nem "sanitize funciona". Medir:
`knowledge ingested → retrievable → interpretable → usable by model → improves answer → via real interfaces` e que isso se mantém sob mudança de modelo/config/documento/embedding/schema/código.

## Categorias (15 dimensões)

| ID | Categoria | Mede | Exemplo de query |
|---|---|---|---|
| A | Knowledge Retrieval | literal/semântico/estrutural/multi-hop | "nome exato da opção", "onde está definido", "quem chama X" |
| B | Grounding | resposta apoiada em fonte | "o que o doc diz sobre X" |
| C | Document Understanding | fato/trecho/conceito/argumento/síntese | "compare conceitos em 2 partes do livro" |
| D | Code/Config Knowledge | descoberta no próprio código | "onde está a fonte de verdade do context budget" |
| E | Self-Knowledge | componentes, dependências, onde mora | "onde está o sanitizer", "o que depende de X" |
| F | MCP Tool Use | consumer→MCP→retrieval→model | via OpenCode/CLI/harness |
| G | Agent Behavior | tool selection, sequência, uso de resultado | "encontre X" (exige descoberta) |
| H | Memory | episódica ≠ recall ≠ lessons ≠ doc | "o que foi decidido", "qual lesson surgiu" |
| I | Negative Knowledge | NO EVIDENCE (não inventar) | pergunta fora do corpus, premissa falsa |
| J | Temporal | current/historical/unknown | "versão atual de X" |
| K | Multi-Document | combinar 2+ fontes | pergunta que exige 2 docs |
| L | Performance | TTFT, retrieval, embedding, generation separados | — |
| M | Config Propagation — **IMPLEMENTADA**: `provider_registry.{CANONICAL_CONTEXT,MIN_PROFILE_CONTEXT}` como fonte única + `tests/test_context_drift.py` (derivação por site; fonte mutada falha enumerando consumidores; hardcodes novos detectados). Consolidação executada 18/09. | 1-mudança→todos-consumidores (mutation) | "mudar context budget reflete em todos?" |
| N | Failure Recovery | falha injetada → detectada/classificada/recuperada | Qdrant down, sanitizer reject, empty retrieval |
| O | Architecture Integrity | invariantes estruturais (fonte única, sanitizer-before-index) | já em test_architecture_invariants.py |

## Datasets / sources
- Livros reais: `~/Books/` (paper arXiv, survival book, docs, EPUB) — via sanitizer→index→retrieve.
- Código: `nixos-ai` ingerido (`code_index`).
- Memória: eventos episódicos (`memories`), lessons.
- Self-knowledge: código/config real (não conhecimento prévio do modelo).

## Metrics por resposta
- retrieval: relevance, precision, recall, provenance, source diversity, duplicates
- grounding: resposta == fonte? cita source?
- organization, completeness, concision, uncertainty
- tool use: tool certa, args, sequência, resultado usado, tool repetida/ignorada/inventada
- performance: TTFT, tool latency, retrieval latency, embedding latency, generation
- MCP: sucesso por consumer (OpenCode/CLI/harness), divergência CLI-vs-MCP

## Execution path (reutilizar infra existente, não scripts soltos)
- Invariantes estáticos: `test_architecture_invariants.py` (já criado, 9 testes) — roda no `nix flake check`.
- E2E real Qdrant: versionar `/tmp/e2e_bootstrap.py` + `/tmp/reindex_pilot.py` como `test_*_integration.py` (atualmente em /tmp = GAP P2).
- Baseline: registrar commit/config/model/embedding/benchmark-version/result em `docs/benchmarks/results/`.

## Regression rules
- Categoria M (config propagation) e O (integrity) SÃO permanentes — falha = dívida arquitetural.
- A/B/I/E: quando mudar modelo/ingestão, rerun e comparar por dimensão (não número único).
- NUNCA: benchmark que "passa" com tamanho de resposta como proxy de qualidade.

## Baseline (a registrar quando o pipeline do outro agente estabilizar)
```
benchmark_version, git_commit, config_hash, model, embedding, dataset_sha, results{by_category}, timestamp
```
derivável, versionado apenas quando agregar valor (§29).