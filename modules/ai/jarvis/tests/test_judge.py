"""LLM-judge: unidade com client fake; integração real vai no relatório."""

from __future__ import annotations

import json


class _FakeJudge:
    def __init__(self, payload):
        self._payload = payload

    def chat_full(self, messages, **kw):
        from jarvis.providers.llm_backend import ChatResponse
        return ChatResponse(content=json.dumps(self._payload))


def test_judge_parses_verdict():
    from jarvis.core.judge import judge_grounding
    v = judge_grounding(
        "O arquivo tem 3 linhas.",
        ["a\nb\nc"],
        llm_client=_FakeJudge({
            "supported": ["arquivo tem 3 linhas"],
            "contradicted": [], "unverifiable": []}))
    assert v.faithful is True
    assert v.supported == ["arquivo tem 3 linhas"]


def test_judge_detects_contradiction():
    from jarvis.core.judge import judge_grounding
    v = judge_grounding(
        "Não há arquivos .nix.",
        ["app.py\nservico.nix"],
        llm_client=_FakeJudge({
            "supported": [], "contradicted": ["nega servico.nix"],
            "unverifiable": []}))
    assert v.faithful is False


def test_judge_empty_is_unverifiable():
    from jarvis.core.judge import judge_grounding
    v = judge_grounding("", [], llm_client=_FakeJudge({}))
    assert v.faithful is True
    assert v.unverifiable != []
