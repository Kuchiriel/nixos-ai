"""Testes P2.8 decompose_question + P2.9 (multi-hop/curiosidade estruturada).
24/10 — roadmap inteligência. Heurística PURA: sem rede, sem Qdrant.
"""
import sys
sys.path.insert(0, "/home/nixos/projects/nixos-ai/modules/ai/jarvis/src")
from jarvis.core.metacognition import get_metacognition


def test_decompose_simples_unitario():
    """Pergunta simples → lista unitária (nunca quebra o que funciona)."""
    m = get_metacognition()
    for t in ["Jarvis onde eu moro", "qual meu nome", "oi", ""]:
        r = m.decompose_question(t)
        if not t:
            assert r == [], f"vazio → {r!r}"
        else:
            assert r == [t], f"{t!r} deveria ser unitária: {r!r}"


def test_decompose_composta_dois_aspectos():
    """2 âncoras separadas por ' e ' → 2 sub-perguntas."""
    m = get_metacognition()
    r = m.decompose_question("Jarvis onde eu moro e qual meu nome")
    assert len(r) == 2, r
    assert any("moro" in q for q in r)
    assert any("nome" in q for q in r)


def test_decompose_composta_por_virgula():
    ""","" separa aspectos também."""
    m = get_metacognition()
    r = m.decompose_question("Jarvis, o que eu gosto de comer, qual meu trabalho")
    assert len(r) == 2, r
    assert any("comer" in q for q in r)
    assert any("trabalho" in q in q or "trabalho" in q for q in r)


def test_decompose_e_incidental_nao_quebra():
    """' e ' sem segunda âncora (conjunção incidental) → unitária."""
    m = get_metacognition()
    r = m.decompose_question("Jarvis como funciona o bolo e a massa")
    assert r == ["Jarvis como funciona o bolo e a massa"], r


def test_decompose_cap_tres():
    """Mais de 3 aspectos → cap 3 (latência de voz)."""
    m = get_metacognition()
    r = m.decompose_question(
        "Jarvis onde eu moro, qual meu nome, quando meu aniversário, "
        "o que eu gosto de comer, qual meu trabalho")
    assert len(r) <= 3, r
