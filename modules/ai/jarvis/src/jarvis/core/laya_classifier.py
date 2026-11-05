"""
Laya classifier — decision model (ONNX, CPU) para roteamento de dificuldade.

Substitui o regex-only em classify_difficulty. Laya retorna distribuição
calibrada (choice) sobre opções tipadas em single forward pass (~150ms CPU,
load 3-5s cold). Checkpoint: inferenceprince/laya-onnx (English fp16, 421M
params, ModernBERT-large). Apache 2.0.

Limites (do README do build):
- English-only: colapsa em non-Latin scripts ficando confiante. Nosso texto
  é PT/EN misto — o regex fallback cobre PT; o Laya roda em cima do texto
  como está (Latin script aceita bem PT, mas confiança calibrada p/ EN).
- Não é zero-shot: accuracy vem de fine-tuning. Para routing (distinct
  categories) o smoke test reporta 77.8% choice / 87-100% em routing puro.
- choice < ~20 options (compartilham 192-token budget).

Fallback: se Laya indisponível (load fail, import error, timeout), o
caller cai no regex. Este módulo nunca lança — retorna None em erro.
"""

import json
import os
import threading
from pathlib import Path

# Paths do modelo (fonte única: models.nix `layaModelDir`; env LAYA_MODEL_DIR
# sobrescreve p/ teste A/B). Default = checkpoint FINE-TUNED (laya-ft, Kaggle
# T4 v7: 95.6% acc, hard 100%, +36.8% vs base) — o base (laya-onnx) fica como
# fallback manual: LAYA_MODEL_DIR=/home/nixos/models/laya-onnx.
_MODEL_DIR = Path(os.environ.get("LAYA_MODEL_DIR", "/home/nixos/models/laya-ft"))
_CONFIG_PATH = _MODEL_DIR / "rl_agent_config.json"
_TOKENIZER_PATH = _MODEL_DIR / "tokenizer" / "tokenizer.json"
_ONNX_PATH = _MODEL_DIR / "model.onnx"

# Singleton state (load lazy, thread-safe)
_session = None
_tokenizer = None
_config = None
_load_lock = threading.Lock()
_load_failed = False

# Token ids (preenchidos no load)
_CLS = None
_SEP = None
_MASK = None


def _try_load() -> bool:
    """Carrega tokenizer + ONNX session + config. True se pronto."""
    global _session, _tokenizer, _config, _CLS, _SEP, _MASK, _load_failed

    if _session is not None:
        return True
    if _load_failed:
        return False

    with _load_lock:
        if _session is not None:
            return True
        if _load_failed:
            return False
        try:
            import numpy as np  # noqa: F401
            import onnxruntime as ort
            from tokenizers import Tokenizer

            if not _ONNX_PATH.exists():
                _load_failed = True
                return False

            _config = json.loads(_CONFIG_PATH.read_text())
            _tokenizer = Tokenizer.from_file(str(_TOKENIZER_PATH))
            _session = ort.InferenceSession(
                str(_ONNX_PATH), providers=["CPUExecutionProvider"]
            )
            _CLS = _tokenizer.token_to_id("[CLS]")
            _SEP = _tokenizer.token_to_id("[SEP]")
            _MASK = _tokenizer.token_to_id("[MASK]")
            return True
        except Exception:
            _load_failed = True
            return False


def _tokenize(text: str) -> list[int]:
    return _tokenizer.encode(text, add_special_tokens=False).ids


def _temperature_for(qtype: str, option_count: int) -> float:
    if option_count <= 2:
        size = "2"
    elif option_count <= 5:
        size = "3-5"
    elif option_count <= 10:
        size = "6-10"
    else:
        size = "11+"
    key = f"{qtype}:{size}"
    # (26/10) O export do checkpoint FINE-TUNED (laya-ft) NÃO traz a tabela
    # granular `temperature_by_options` (só a lista `temperature`) → o
    # KeyError era engolido pelo except genérico e a Laya devolvia None
    # SEMPRE (classificador inerte). Fallback: temperature[0] do config.
    # O argmax é invariante à temperatura (softmax monotônico) → só as
    # probabilidades exibidas ficam mais achatadas.
    by_options = _config.get("temperature_by_options") or {}
    return by_options.get(key, _config["temperature"][0])


def classify_choice(state: str, question: str, options: dict[str, str]) -> dict[str, float] | None:
    """
    Classifica `state` contra `question` com opções tipadas.

    Args:
        state: texto a analisar (prompt do usuário)
        question: pergunta de decisão (ex: "Which tier should handle this?")
        options: {label: description} — label é a resposta, description o hint

    Returns:
        {label: probability} ordenado por prob desc, ou None em erro.
    """
    if not _try_load():
        return None

    try:
        import numpy as np

        token_ids = [_CLS] + _tokenize(f"choice question: {question}") + [_SEP]
        option_positions = []
        for label, description in options.items():
            option_positions.append(len(token_ids))
            token_ids.append(_MASK)
            token_ids += _tokenize(f" {label}: {description}")[:48]
        token_ids.append(_SEP)

        max_len = _config["max_len"]
        room = max_len - len(token_ids) - 1
        token_ids += _tokenize(state)[:room]
        token_ids.append(_SEP)

        option_count = len(option_positions)
        outputs = _session.run(
            None,
            {
                "input_ids": np.array([token_ids], dtype=np.int64),
                "attention_mask": np.ones((1, len(token_ids)), dtype=np.int64),
                "marker_pos": np.array([option_positions], dtype=np.int64),
                "marker_mask": np.ones((1, option_count), dtype=bool),
                "qtype": np.array([0], dtype=np.int64),  # 0=choice
            },
        )
        logits = outputs[0]
        temperature = _temperature_for("choice", option_count)
        scores = logits[0, :option_count] / temperature
        scores = scores - scores.max()
        probs = np.exp(scores)
        probs = probs / probs.sum()

        labels = list(options.keys())
        return {label: float(p) for label, p in zip(labels, probs)}
    except Exception:
        return None


def classify_difficulty_laya(prompt: str, context_len: int = 0) -> str | None:
    """
    Classifica dificuldade do prompt via Laya. Retorna "simple"|"moderate"|"hard"
    ou None se Laya indisponível/erro (caller deve cair no regex).

    Usa os mesmos 3 tiers do hybrid_route: simple→local leve, moderate→local
    médio, hard→cloud. Descrições calibradas p/ routing (distinct categories).
    """
    if not _try_load():
        return None

    options = {
        "simple": "greetings, greetings, short factual questions, simple lookups, yes/no, formatting, translation of a phrase",
        "moderate": "code explanation, multi-step instructions, moderate reasoning, drafting emails, summarizing text, standard analysis",
        "hard": "complex reasoning, architecture design, debugging multi-file systems, mathematics proofs, creative writing, long context synthesis, expert domain questions",
    }
    result = classify_choice(
        state=prompt[:2000],
        question="How difficult is this request for a small local language model?",
        options=options,
    )
    if result is None:
        return None
    winner = max(result, key=result.get)
    return winner if winner in ("simple", "moderate", "hard") else None
