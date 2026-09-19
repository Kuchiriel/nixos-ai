# Roadmap de Retrieval — prioridades com evidência local

Criado 18/09 (pós-benchmark v2, 10/10 janela MCP). Cada item é ancorado em um
diagnóstico real desta sessão + prática consolidada na literatura (Anthropic
Contextual Retrieval, playbooks de chunking 2026, RRF/reranking). Ordenado por
impacto/esforço **nesta stack** (llama.cpp nomic-embed 768, Qdrant 1.17.1
dense+BM25+RRF, reranker :8082).

## A. Expansão de vizinhos (parent window) — PRÓXIMO, esforço baixo

**Evidência local**: chunk do call-site `LoopDetector` (harness.py:1950) contém
o comentário que explica o mecanismo, mas o *contexto da função* está no chunk
seguinte; para books, o capítulo do Caibalion se perde entre chunks.
**Proposta**: no upsert, armazenar `chunk_index` (já existe no payload) e, no
retrieval, expandir cada hit com vizinhos ±1 do mesmo `document_id`
(scroll/filter barato). O LLM recebe hit+contexto com citação do chunk exato.
**Custo**: ~1 query Qdrant filtrada por hit; zero reingestão.

## B. Enriquecimento contextual pós-OCR — esforço médio, alto ganho p/ corpus

**Evidência local**: Village Technology Handbook foi para quarentena por
colapso de headers repetidos; os livros metalworking (0 chars) são scans sem
camada de texto. São 2+ fontes grandes fora do corpus.
**Proposta** (Anthropic Contextual Retrieval, adaptado): antes do chunking,
prepend 1-2 frases geradas por LLM local situando o chunk no documento
("Seção 4.3 do Village Technology Handbook — pozos de água..."). Marcar no
payload `enrichment: "llm-generated"` — o mission §20 exige distinção
explícita de conteúdo LLM vs fonte.

## C. python-3.14-docs — desbloquear FILE_TOO_LARGE

**Evidência local**: quarentena honesta (>8MB). O sanitizer tem limite único
global. **Proposta**: split de arquivo grande em passadas de extração
(por capítulo/seção do índice) mantendo `document_id` único — o limite de
tamanho é sobre extração, não sobre identidade. Reingestão posterior via
lote docs do manifest.

## D. Evaluation contínua das interfaces reais (MCP/OpenCode)

**Evidência local**: o benchmark valida `HybridSearch` direto; o caminho
real do agente é MCP stdio. Já provamos MCP E2E manualmente (§16); falta
transformá-lo em teste automático (stdio → tools → asserts) rodável na suíte.
**Ganho**: regressão de interface detectada antes do runtime (como o bug do
`hasattr(r,'text')` — que a suíte não pegou).

## E. Late chunking — NÃO VIÁVEL nesta stack (registrado p/ não re-examinar)

Requer embeddings token-level do jina-v3; nomic-embed via llama.cpp expõe
apenas pooled 768. Se trocar o modelo de embedding, reavaliar (e aí o
benchmark v2 passa a valer como contratemplo de compat).

## F. Rerank condicional por latência

Reranker existe (:8082) e resolve nickyeo no benchmark, mas o handler MCP
chama `use_rerank=True` sempre (timeout 120s!). **Proposta**: rerank só
quando top-1 dispersão de score for baixa (sinal de empate semântico), ou
timeout agressivo (~2s) com fallback para RRF. Medir TTFT pós-mudança.

## Disciplina de medição

Toda mudança de retrieval passa pelo `scripts/acceptance_bench.py` (v2) —
matriz on/off quando o default estiver em jogo, needles por path-OU-conteúdo,
janela 5 (MCP) como critério primário. Não otimizar por narrativa.
