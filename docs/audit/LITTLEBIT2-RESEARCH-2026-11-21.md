# LittleBit-2 (Samsung) — pesquisa e teste no nosso stack (21/11)

## Fonte primária

- Blog Samsung Research: `https://research.samsung.com/blog/LittleBit-2-Maximizing-the-Spectral-Energy-Gain-in-Sub-1-Bit-LLMs-via-Latent-Geometry-Alignment`
- Repo oficial: `https://github.com/SamsungLabs/LittleBit` (ICML 2026; flag `--use_itq`)
- Paper anterior LittleBit (NeurIPS 2025): fatoração de baixo rank + binarização + escalas FP16.

## O que o paper realmente muda

LittleBit-2 **não muda arquitetura de inferência**. Muda a inicialização antes
do QAT: aplica rotação ortogonal interna aos fatores latentes da SVD e depois
Joint-ITQ (alterna `B=sign(ZR)` com `R=SVD(BᵀZ)`) para alinhar os fatores ao
hipercubo binário. Isso reduz a distorção λ = 1 − (L1/L2)² e a oscilação de
sinais no treino (~3,8× menos no início), com custo único de ~3 s por camada.
Resultados relatados: Llama-3 8B a 1,0 bpp, PPL 16,30 → 11,53; 0,1 bpp
ainda funcional (23,74). Velocidade de inferência herdada do LittleBit: kernel
11,6× e decoding 2,46× (82,6 → 203,2 tok/s) em Llama-2 7B 0,1 bpp.

## O que é aplicável aqui (e o que não é)

**Não aplicável agora:** não fazemos QAT nem treino de pesos; rodamos modelos
locais via llama.cpp (`:8092`, `:8084`) com GGUF. Não existe pipeline
`main.py`/`--use_itq` no nosso stack, e reproduzir os números exigiria CUDA,
`transformers==4.51.x`, dataset C4/Wiki e dias de treino.

**Transferível:** o primitivo de geometria (Joint-ITQ) pode ser aplicado a
embeddings antes de binarização. Nosso Qdrant tem binarização nativa
(`quantization_config.binary`), documentada em `qdrant.tech`.

## Testes executados (somente leitura em produção)

1. `scripts/littlebit2-itq-probe.py` — geometria:

| dataset | λ SVD | λ rotação aleatória | λ Joint-ITQ |
|---|---:|---:|---:|
| sintético power-law γ=0,4, rank 32 | 0,3682 | 0,3539 | **0,3009** |
| 600 embeddings reais de `code_index` | 0,3719 | 0,3652 | 0,3615 |

O sintético reproduz o patamar do paper (~0,30). Nos embeddings reais o ganho
é pequeno: eles já são quase isotrópicos.

2. `scripts/itq-binary-rag-ab.py` — binarização nativa do Qdrant em duas
coleções isoladas (`jarvis_test_itq_plain` / `jarvis_test_itq_rot`, 900 pontos,
100 queries, ground truth = vizinho denso):

| modo | recall@8 sem rescore | recall@8 com rescore |
|---|---:|---:|
| binário, vetores originais | 0,87 | 1,00 |
| binário, vetores rotacionados por ITQ | 0,90 | 1,00 |
| denso (controle) | 1,00 | 1,00 |

Rotação e query usaram a **mesma** R (erro de ortogonalidade 0,0).
`code_index` medido em 275.724 pontos antes e depois — nenhuma escrita.

## Decisão

**Não adotar ITQ no RAG agora.** Com o `rescore` padrão do Qdrant não há ganho
de recall; sem rescore o ganho é de 0,03 em 100 queries, dentro do ruído para
20–100 amostras, ao custo de aplicar uma matriz 768×768 a todo upsert e query.

**Reavaliar se:** (a) começarmos QAT de modelos locais — nesse caso usar
diretamente `--use_itq` do repo oficial; ou (b) o índice for tão grande que
`rescore` precise ser desligado por latência — aí repetir o A/B com ≥1000
queries e medir latência/memória, não só recall.

Dois bugs do harness corrigidos na origem: criação das duas coleções (a
segunda apagava a primeira) e rotação apenas dos documentos, não das queries.

Limitação honesta: these são embeddings de documentos, não pesos de LLM; o
teste não mede PPL nem velocidade de decoding.
