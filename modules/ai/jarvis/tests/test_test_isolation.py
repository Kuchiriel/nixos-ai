"""Invariante: testes NUNCA referenciam coleções de produção do Qdrant.

Motivação (18/09 20:15): test_parity_with_synthetic_index usava
cfg.qdrant_collection_code como coleção de fixture e o delete_collection do
finally apagou o code_index de PRODUÇÃO (1263 pontos destruídos).

Regra: arquivos de teste não devem conter o token `qdrant_collection_code`
como nome de coleção — fixtures usam nomes exclusivos (jarvis_test_*) e,
quando precisam apontar o pipeline para elas, derivam uma config:
dataclasses.replace(cfg, qdrant_collection_code="jarvis_test_xxx").
"""
from __future__ import annotations

import re
from pathlib import Path

TESTS = Path(__file__).resolve().parent
SELF = Path(__file__).name

_PRODUCTION_LITERALS = re.compile(r'"(code_index|memories|books)"')


def test_tests_never_use_production_collection_names() -> None:
    offenders: list[str] = []
    for py in sorted(TESTS.glob("*.py")):
        if py.name == SELF:
            continue
        text = py.read_text(errors="ignore")
        if "qdrant_collection_code" not in text:
            continue
        # Tolerado apenas quando deriva a config p/ fixture (replace para
        # nome jarvis_test_*), nunca como nome de coleção em si.
        for lineno, line in enumerate(text.splitlines(), 1):
            if "qdrant_collection_code" not in line:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue  # comentário é inerte
            if "jarvis_test_" in stripped:
                continue  # fixture explícita na própria linha
            if "replace(" in stripped and not _PRODUCTION_LITERALS.search(stripped):
                continue  # derivação de config p/ fixture (valor em jarvis_test_*)
            offenders.append(f"{py.name}:{lineno}: {stripped[:100]}")
    assert not offenders, (
        "testes referenciando coleção de produção (risco de DELETE no "
        "code_index/memories/books real — ver incidente 18/09):\n"
        + "\n".join(offenders)
    )
