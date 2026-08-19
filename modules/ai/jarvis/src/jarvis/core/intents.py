"""Classificação determinística de intenção (TF-IDF + cosseno, puro NumPy).

Porta limpa do `semantic_router.py` do legado (Manjaro/AI_SYSTEM):
mantém as 4 categorias (SYSTEM/CODING/VISION/CHAT), os exemplos PT/EN
e as regras de proteção contra falsos positivos de VISION — sem a
dependência de scikit-learn e sem o fallback LLM (que retorna ao
roteamento quando necessário).

Intenção é determinística e barata: nenhum LLM envolvido.
"""

from __future__ import annotations

import math
import re
from typing import Final

INTENTS: Final[tuple[str, ...]] = ("SYSTEM", "CODING", "VISION", "CHAT")

_INTENT_EXAMPLES: Final[dict[str, list[str]]] = {
    "SYSTEM": [
        "cpu usage", "ram available", "disk space", "running processes",
        "system uptime", "network status", "port check", "system logs",
        "hardware health", "gpu status", "temperature",
        "mude voz", "alterar voz", "fale mais rápido", "listar vozes",
        "uso de cpu", "quanta memória", "espaço em disco", "uptime do sistema",
        "status da rede", "logs do sistema", "saúde do hardware",
        "configurações de som", "device hardware",
    ],
    "CODING": [
        "escreva um script", "crie uma função", "implemente o algoritmo",
        "corrija o erro no código", "refatore o sistema", "gere um código",
        "como programar", "exemplo de código", "write a function", "create a script",
        "diferença entre lista e array", "lógica de programação",
        "como funciona o loop", "ponteiros", "compilação",
        "analise a performance", "otimize este código", "gargalo de cpu",
        "protocolo de rede", "analise o protocolo", "packet structure",
        "opcode", "xtea", "encryption", "bug fix", "refactor code",
        "unit test", "fix syntax", "data structures",
    ],
    "VISION": [
        "tire print", "print screen", "captura tela", "screenshot",
        "analise a janela", "ocr screen", "analise o que estou vendo",
        "descreva esta imagem", "leia o que esta na tela", "veja a tela",
        "olhe para o meu terminal", "o que tem na imagem", "look at the screen",
        "reconhecimento de imagem", "visualize o erro",
    ],
    "CHAT": [
        "olá", "bom dia", "quem foi", "como funciona", "o que você acha",
        "explique o conceito", "capital da", "quantos", "qual a diferença",
        "conte uma história", "escreva um e-mail", "me dê conselhos",
        "fale sobre", "clima em", "quem é você", "tudo bem", "boa tarde",
        "significado da palavra", "como se pronuncia", "frase correta",
    ],
}

# Palavras técnicas que forçam CODING (Regra de Ouro do legado)
_TECHNICAL_MARKERS: Final[tuple[str, ...]] = (
    ".cpp", ".lua", ".h", ".py", ".sh", ".rive", "protocol", "packet",
    "opcode", "knowledge base", "base de conhecimento",
)

# Gatilhos de pergunta genérica (viram CHAT se a confiança for baixa)
_CHAT_TRIGGERS: Final[tuple[str, ...]] = ("quantos", "quem", "como", "o que", "qual", "diga", "resuma")

# Palavras que indicam pedido explícito de visão
_VISION_KEYWORDS: Final[tuple[str, ...]] = ("tela", "print", "screen", "veja", "olhe", "imagem", "janela")


def _tokenize(text: str) -> list[str]:
    """Tokeniza minúsculo, mantendo extensões de arquivo como um token."""
    text = text.lower()
    # preserva ".py", ".cpp", etc.
    text = re.sub(r"\.([a-z0-9]{1,5})\b", r" dot\1 ", text)
    return re.findall(r"[a-z0-9_]{2,}", text)


def _idf(corpus: list[list[str]], doc_freq: dict[str, int], n_docs: int) -> dict[str, float]:
    return {term: math.log((1 + n_docs) / (1 + df)) + 1.0 for term, df in doc_freq.items()}


class IntentClassifier:
    """TF-IDF + similaridade de cosseno sobre exemplos, com regras de proteção."""

    def __init__(self) -> None:
        examples: list[str] = []
        self._example_to_intent: list[str] = []
        for intent, exs in _INTENT_EXAMPLES.items():
            examples.extend(exs)
            self._example_to_intent.extend([intent] * len(exs))

        self._corpus: list[list[str]] = [_tokenize(ex) for ex in examples]
        self._n_docs = len(self._corpus)
        df: dict[str, int] = {}
        for doc in self._corpus:
            for term in set(doc):
                df[term] = df.get(term, 0) + 1
        self._idf = _idf(self._corpus, df, self._n_docs)
        self._tfidf = [self._tfidf_vector(doc) for doc in self._corpus]
        self._doc_norms = [self._norm(v) for v in self._tfidf]

    def _tfidf_vector(self, tokens: list[str]) -> dict[str, float]:
        tf: dict[str, float] = {}
        for term in tokens:
            tf[term] = tf.get(term, 0.0) + 1.0
        total = len(tokens) or 1
        return {term: (count / total) * self._idf.get(term, 1.0) for term, count in tf.items()}

    @staticmethod
    def _norm(vec: dict[str, float]) -> float:
        return math.sqrt(sum(v * v for v in vec.values())) or 1.0

    def _cosine(self, query: dict[str, float], doc: dict[str, float], doc_norm: float) -> float:
        q_norm = self._norm(query)
        if q_norm == 0:
            return 0.0
        dot = sum(query.get(term, 0.0) * weight for term, weight in doc.items())
        return dot / (q_norm * doc_norm)

    def classify(self, text: str, min_confidence: float = 0.20) -> str:
        """Retorna a intenção. Sempre determinístico; nunca chama LLM."""
        low = text.lower()

        # Regra de Ouro: termos técnicos ⇒ CODING (bloqueia falsos VISION)
        if any(marker in low for marker in _TECHNICAL_MARKERS):
            return "CODING"

        # Visão explícita só com palavras de imagem
        if any(kw in low for kw in _VISION_KEYWORDS):
            # se tem palavra técnica, CODING vence
            if any(marker in low for marker in _TECHNICAL_MARKERS):
                return "CODING"
            # verifica se a intenção mais forte realmente é VISION
            intent, conf = self._best_match(low)
            if intent == "VISION" and conf >= min_confidence:
                return "VISION"

        intent, conf = self._best_match(low)

        # Pergunta genérica com confiança baixa ⇒ CHAT (nunca VISION acidental)
        if any(low.startswith(t) for t in _CHAT_TRIGGERS) and conf < 0.5:
            return "CHAT"

        return intent if conf >= min_confidence else "CHAT"

    def _best_match(self, low_text: str) -> tuple[str, float]:
        query = self._tfidf_vector(_tokenize(low_text))
        best_intent, best_score = "CHAT", 0.0
        for vec, norm, intent in zip(self._tfidf, self._doc_norms, self._example_to_intent):
            score = self._cosine(query, vec, norm)
            if score > best_score:
                best_score, best_intent = score, intent
        return best_intent, best_score

    def scores(self, text: str) -> dict[str, float]:
        """Similaridade média por intenção (para diagnóstico/benchmark)."""
        low = text.lower()
        query = self._tfidf_vector(_tokenize(low))
        totals: dict[str, float] = {i: 0.0 for i in INTENTS}
        counts: dict[str, int] = {i: 0 for i in INTENTS}
        for vec, norm, intent in zip(self._tfidf, self._doc_norms, self._example_to_intent):
            totals[intent] += self._cosine(query, vec, norm)
            counts[intent] += 1
        return {i: (totals[i] / counts[i] if counts[i] else 0.0) for i in INTENTS}


_classifier: IntentClassifier | None = None


def classify_intent(text: str, min_confidence: float = 0.20) -> str:
    global _classifier
    if _classifier is None:
        _classifier = IntentClassifier()
    return _classifier.classify(text, min_confidence)
