"""Testes da detecção de emoção (core/emotion.py) — porta do legado."""

import json

from jarvis.core import emotion


def test_detect_urgent() -> None:
    assert emotion.detect_emotion("preciso disso urgente, rápido agora") == "urgent"
    assert emotion.detect_emotion("this is critical, do it now") == "urgent"


def test_detect_frustrated() -> None:
    assert emotion.detect_emotion("isso não funciona, está quebrado de novo") == "frustrated"
    assert emotion.detect_emotion("it's broken, not working again") == "frustrated"


def test_detect_concerned() -> None:
    assert emotion.detect_emotion("preciso de ajuda, não sei como faço") == "concerned"
    assert emotion.detect_emotion("i need help, don't know how") == "concerned"


def test_detect_positive() -> None:
    assert emotion.detect_emotion("obrigado, ótimo trabalho, perfeito!") == "positive"
    assert emotion.detect_emotion("thanks, that's great, excellent!") == "positive"


def test_detect_neutral() -> None:
    assert emotion.detect_emotion("qual a previsão do tempo amanhã?") == "neutral"


def test_priority_urgent_over_positive() -> None:
    """Ordem de prioridade do legado: urgent > frustrated > concerned > positive."""
    assert emotion.detect_emotion("obrigado mas isso é urgente agora") == "urgent"
    assert emotion.detect_emotion("não funciona, mas obrigado pela ajuda") == "frustrated"
    assert emotion.detect_emotion("preciso de ajuda, obrigado") == "concerned"


def test_profiles_have_speed_and_tone() -> None:
    for name, prof in emotion.EMOTION_PROFILES.items():
        assert "speed" in prof
        assert "tone" in prof
        assert "emoji" in prof
        assert isinstance(prof["speed"], float)


def test_speed_for_maps_emotion() -> None:
    assert emotion.speed_for("isso é urgente, rápido") == 1.2
    assert emotion.speed_for("obrigado, perfeito!") == 1.1
    assert emotion.speed_for("texto neutro qualquer") == 1.0


def test_state_ttl_resets_to_neutral(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(emotion, "_state_path", lambda: tmp_path / "emotion.json")
    # estado gravado agora → válido
    emotion.update_state("preciso de ajuda")
    assert emotion.get_state()["tone"] == "supportive"
    # estado antigo (6 min) → reset neutral
    old = tmp_path / "emotion.json"
    data = json.loads(old.read_text())
    data["timestamp"] = "2000-01-01T00:00:00+00:00"
    old.write_text(json.dumps(data))
    assert emotion.get_state()["tone"] == "professional"


def test_update_state_persists(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(emotion, "_state_path", lambda: tmp_path / "emotion.json")
    prof = emotion.update_state("não funciona de novo")
    assert prof["tone"] == "empathetic"
    data = json.loads((tmp_path / "emotion.json").read_text())
    assert data["emotion"] == "frustrated"


def test_main_emotion_detects() -> None:
    assert emotion.main_emotion(["isso", "é", "urgente"]) == 0


def test_main_emotion_shows_state() -> None:
    assert emotion.main_emotion([]) == 0
