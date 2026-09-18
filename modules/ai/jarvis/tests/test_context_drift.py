"""Tripwire de drift do context budget (benchmark spec, categoria M).

PÓS-CONSOLIDAÇÃO: os consumidores derivam de
jarvis.core.provider_registry.{CANONICAL_CONTEXT, MIN_PROFILE_CONTEXT}.
A pergunta da missão — "se eu mudar uma fonte de verdade amanhã, como o
sistema sabe?" — tem duas respostas verificadas aqui:

  1. DERIVAÇÃO: consumidores referenciam as constantes do registry (não
     literais) — mudar o valor na fonte é a ÚNICA forma de mudar o budget
     (test_consumers_derive_from_source, test_registry_binds_constant_not_literal).
  2. DETECÇÃO: se a fonte mudar de VALOR, o teste falha enumerando os
     consumidores (custos de VRAM/latência não derivam automaticamente) —
     a mudança nunca passa em silêncio (test_registry_source_value).

Novos hardcodes de contexto fora do censo continuam detectados
(test_no_new_context_hardcodes_outside_census).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
REGISTRY = SRC / "jarvis" / "core" / "provider_registry.py"

# Valores vigentes. Se a FONTE mudar, test_registry_source_value FALLA de
# propósito: revise consumidores/VRAM e atualize aqui — nunca silêncio.
EXPECTED_CANONICAL = 32768
EXPECTED_MIN_PROFILE = 8192

# --- Censo dos sites derivados ----------------------------------------------
# relpath → (descrição, regex do site, constante esperada no grupo 1).
# Regex casa a forma derivada OU literal legado: constante = OK,
# número = regressão (mensagem aponta a derivação correta).
DERIVED_SITES: dict[str, tuple[str, str, str]] = {
    "jarvis/providers/llm.py": (
        "n_ctx fallback (backend info ausente)",
        r"info\.n_ctx if info else (CANONICAL_CONTEXT|\d+)",
        "CANONICAL_CONTEXT",
    ),
    "jarvis/cli/dev.py": (
        "context_size default de perfil",
        r'profile\.get\("context_size",\s*(MIN_PROFILE_CONTEXT|\d+)\)',
        "MIN_PROFILE_CONTEXT",
    ),
    "jarvis/core/context_budget.py": (
        "ContextSnapshot.tokens_budget default",
        r"tokens_budget: int = (CANONICAL_CONTEXT|\d+)",
        "CANONICAL_CONTEXT",
    ),
    "nightwatch/harness.py": (
        "fallback server-unavailable (documentado no notify)",
        r"budget = (MIN_PROFILE_CONTEXT|\d+)\b",
        "MIN_PROFILE_CONTEXT",
    ),
    "jarvis/core/hwprofile.py": (
        "ctx_target default na síntese de perfil de hardware",
        r"ctx_target or (CANONICAL_CONTEXT|\d+)",
        "CANONICAL_CONTEXT",
    ),
}

# Arquivos com hardcodes de contexto legítimos/registrados.
# hwdetect/hwprofile: ctx_max e caps derivados de VRAM; registry: a fonte.
APPROVED_CONTEXT_FILES = {
    "jarvis/core/provider_registry.py",
    "jarvis/providers/llm.py",
    "jarvis/cli/dev.py",
    "jarvis/core/context_budget.py",
    "jarvis/core/hwdetect.py",
    "jarvis/core/hwprofile.py",
    "nightwatch/harness.py",
    "nightwatch/context_budget.py",
}

_CONTEXT_LITERAL = re.compile(r"\b(4096|8192|16384|32768|65536|131072)\b")
# \bctx (sem \b à direita) captura ctx_max/ctx_target; hidden=NNN não casa.
_CONTEXT_LINE = re.compile(r"\b(ctx|context|budget)", re.IGNORECASE)


def _dependency_list() -> str:
    return "\n".join(
        f"  - {path} ({desc})" for path, (desc, _, _) in DERIVED_SITES.items()
    )


# ---------------------------------------------------------------------------
# 1. PROPAGAÇÃO: consumidores derivam da fonte (não de literais)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relpath", sorted(DERIVED_SITES))
def test_consumers_derive_from_source(relpath: str) -> None:
    desc, pattern, expected_const = DERIVED_SITES[relpath]
    m = re.search(pattern, (SRC / relpath).read_text())
    assert m is not None, (
        f"{relpath}: site '{desc}' não encontrado — layout mudou? "
        "Atualize o censo de test_context_drift.py.")
    assert m.group(1) == expected_const, (
        f"{relpath}: '{desc}' está como {m.group(1)!r} em vez de derivar "
        f"de provider_registry.{expected_const} — regressão a literal "
        "quebra a propagação da fonte de verdade (benchmark spec, cat. M)."
    )


def test_registry_binds_constant_not_literal() -> None:
    """A fonte interna não pode regredir a literal: ModelCaps.context e o
    modelo de referência devem usar CANONICAL_CONTEXT."""
    src = REGISTRY.read_text()
    assert "context: int = CANONICAL_CONTEXT" in src, (
        "provider_registry: ModelCaps.context regrediu a literal — a fonte "
        "deve ser CANONICAL_CONTEXT.")
    assert re.search(
        r'"bonsai-8b": ModelCaps\(context=CANONICAL_CONTEXT', src), (
        "provider_registry: bonsai-8b regrediu a literal de contexto.")


# ---------------------------------------------------------------------------
# 2. DETECÇÃO: mudança de VALOR na fonte quebra o build enumerando dependentes
# ---------------------------------------------------------------------------

def test_registry_source_value() -> None:
    m = re.search(r"^CANONICAL_CONTEXT = (\d+)", REGISTRY.read_text(), re.M)
    assert m, "CANONICAL_CONTEXT não encontrada no registry (fonte movida?)"
    assert int(m.group(1)) == EXPECTED_CANONICAL, (
        f"FONTE DO CONTEXT BUDGET MUDOU ({EXPECTED_CANONICAL} → "
        f"{m.group(1)}).\nConsumidores que exigem revisão (custos de "
        f"VRAM/latência não derivam sozinhos):\n{_dependency_list()}\n"
        "A mudança NÃO passou em silêncio. Após revisar, atualize "
        "EXPECTED_CANONICAL."
    )


def test_min_profile_value() -> None:
    m = re.search(r"^MIN_PROFILE_CONTEXT = (\d+)", REGISTRY.read_text(), re.M)
    assert m, "MIN_PROFILE_CONTEXT não encontrada no registry"
    assert int(m.group(1)) == EXPECTED_MIN_PROFILE, (
        f"PISO DE PERFIL MUDOU ({EXPECTED_MIN_PROFILE} → {m.group(1)}).\n"
        f"Consumidores:\n{_dependency_list()}"
    )


# ---------------------------------------------------------------------------
# 3. Novos hardcodes de contexto fora do censo são detectados
# ---------------------------------------------------------------------------

def test_no_new_context_hardcodes_outside_census() -> None:
    offenders: list[str] = []
    for py in sorted(SRC.rglob("*.py")):
        rel = py.relative_to(SRC).as_posix()
        if rel in APPROVED_CONTEXT_FILES:
            continue
        text = py.read_text(errors="ignore")
        for lineno, line in enumerate(text.splitlines(), 1):
            if _CONTEXT_LINE.search(line) and _CONTEXT_LITERAL.search(line):
                offenders.append(f"{rel}:{lineno}: {line.strip()[:100]}")
    assert not offenders, (
        "novos hardcodes de contexto fora do censo — derive de "
        "provider_registry (CANONICAL_CONTEXT/MIN_PROFILE_CONTEXT) ou, se "
        "legítimo, registre no censo de test_context_drift.py:\n"
        + "\n".join(offenders)
    )
