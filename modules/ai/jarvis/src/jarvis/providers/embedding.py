"""Embedding de texto longo: chunk + mean-pool.

Contexto: o servidor de embeddings roda com n_ctx pequeno (512 tokens,
medido neste box). Texto acima disso faz o llama-server devolver
500, e o chamador (remember/index) só vê exceção — memória some em
silêncio. Aqui o texto é partido em pedaços que cabem, cada pedaço é
embedado, e os vetores são combinados por mean-pooling com
normalização L2 (mesma semântica do modelo para texto longo).
"""

from __future__ import annotations

import math
from collections.abc import Callable

# O servidor de embeddings deste box tem max context de 512 TOKENS (medido
# 25/09: 4000 chars ~500 tokens passa, 7200 chars/902 tokens devolve 400
# "larger than max context size (512)"). 4000 chars ficava RASPAR o
# limite — e texto com mais chars/token (código, acentos, CJK) estourava.
# Medido com texto PT-BR (acentos + maiusculas tokenizam pior que ASCII):
# 2000 chars FALHA, 1600 OK. Ou seja ~3,1 chars/token nao vale: precisa
# de folga real. 1200 chars ≈ 375 tokens = 27% abaixo do teto de 512.
# Custa mais requests, e requests a mais e barato; perder a memoria e caro.
CHUNK_CHARS = 1200
OVERLAP_CHARS = 200


def split_for_embedding(text: str, chunk_chars: int = CHUNK_CHARS,
                        overlap_chars: int = OVERLAP_CHARS) -> list[str]:
    """Parte o texto em pedaços que cabem no n_ctx do servidor.

    Corta em fronteira de parágrafo quando possível (chunks semânticos
    geram embeddings melhores que cortar no meio da frase).
    """
    text = text.strip()
    if not text:
        return [""]
    if len(text) <= chunk_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if end < len(text):
            # tenta quebrar em parágrafo/frase dentro da janela
            for sep in ("\n\n", "\n", ". "):
                cut = text.rfind(sep, start + chunk_chars // 2, end)
                if cut > start:
                    end = cut + len(sep)
                    break
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def mean_pool(vectors: list[list[float]]) -> list[float]:
    """Média dos vetores normalizados (equivalente a concatenar e embedar,
    aproximado; vetor final também normalizado)."""
    if not vectors:
        return []
    dim = len(vectors[0])
    acc = [0.0] * dim
    for vec in vectors:
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        for i, v in enumerate(vec):
            acc[i] += v / norm
    total = math.sqrt(sum(v * v for v in acc)) or 1.0
    return [v / total for v in acc]


def embed_long(embed_one: Callable[[str], list[float]], text: str,
               chunk_chars: int = CHUNK_CHARS) -> list[float]:
    """Embeda texto curto direto; texto longo em chunks com mean-pooling."""
    chunks = split_for_embedding(text, chunk_chars)
    if len(chunks) == 1:
        return embed_one(chunks[0])
    return mean_pool([embed_one(c) for c in chunks])
