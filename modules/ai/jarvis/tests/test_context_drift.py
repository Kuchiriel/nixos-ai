"""Tripwire de drift do context budget (benchmark spec, categoria M).

Responde à pergunta da missão: "se eu mudar uma fonte de verdade amanhã,
como o sistema sabe?"

Hoje (consolidação PENDENTE — ver docs/benchmarks/knowledge-system-
benchmark-spec.md e docs/architecture/KNOWLEDGE_SYSTEM_ARCHITECTURE_AUDIT.md)
o context budget tem fallbacks hardcoded em consumidores. Estes testes NÃO
refatoram nada (evita colisão com o consolidator em curso); eles garantem que:

  1. mudança na FONTE (provider_registry.ModelCaps.context / bonsai-8b)
     quebra o build LOUD, enumerando os consumidores que exigem revisão;
  2. o censo de fallbacks conhecidos é explícito — fallback alterado sem
     derivação do registry quebra o teste;
  3. novos hardcodes de contexto em arquivos fora do censo são detectados.

Limitação honesta: o censo (2) cobre os SITES registrados; novas linhas de
contexto dentro de arquivos já aprovados não são detectadas — a consolidação
(derivar do registry) elimina essa classe inteira de drift.

Caminho de escape: quando a consolidação acontecer, os testes continuam
passando — derive do registry em vez de editar este arquivo.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

# --- Fonte de verdade -------------------------------------------------------
REGISTRY = SRC / "jarvis" / "core" / "provider_registry.py"

# Valor canônico vigente. Se a fonte mudar, o teste 1 FALLA de propósito:
# revise os consumidores (ou derive-os) e então atualize este valor —
# a mudança nunca pode passar silenciosamente.
EXPECTED_CANONICAL = 32768

# --- Censo de fallbacks hardcoded (dívida registrada, não oculta) -----------
# relpath (a partir de src/) → (descrição, regex do literal, valor registrado)
FALLBACK_SITES: dict[str, tuple[str, str, int]] = {
    "jarvis/providers/llm.py": (
        "n_ctx fallback (backend info ausente)",
        r"info\.n_ctx if info else (\d+)",
        32768,
    ),
    "jarvis/cli/dev.py": (
        "context_size default de perfil",
        r'profile\.get\("context_size",\s*(\d+)\)',
        8192,
    ),
    "jarvis/core/context_budget.py": (
        "ContextSnapshot.tokens_budget default",
        r"tokens_budget: int = (\d+)",
        8192,
    ),
    "nightwatch/harness.py": (
        "fallback server-unavailable (documentado no notify)",
        r"budget = (\d+)\n",
        8192,
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
        f"  - {path} ({desc})" for path, (desc, _, _) in FALLBACK_SITES.items()
    )


# ---------------------------------------------------------------------------
# 1. A fonte é a fonte — mudança nela quebra o build enumerando dependentes
# ---------------------------------------------------------------------------

def test_registry_is_context_source_of_truth() -> None:
    src = REGISTRY.read_text()
    m_default = re.search(r"class ModelCaps[\s\S]*?context: int = (\d+)", src)
    m_bonsai = re.search(r'"bonsai-8b": ModelCaps\(context=(\d+)', src)
    assert m_default and m_bonsai, (
        "provider_registry não parseável — fonte de verdade do context "
        "budget movida/renomeada? Atualize este teste e o benchmark spec (M)."
    )
    deps = _dependency_list()
    msg = (
        "FONTE DO CONTEXT BUDGET MUDOU ({old} → {new}).\n"
        "Consumidores hardcoded que exigem revisão/derivação:\n{deps}\n"
        "É ISTO que responde 'como o sistema sabe': a mudança não passou "
        "silenciosamente. Derive os consumidores do registry e atualize "
        "EXPECTED_CANONICAL."
    )
    assert int(m_default.group(1)) == EXPECTED_CANONICAL, msg.format(
        old=EXPECTED_CANONICAL, new=m_default.group(1), deps=deps)
    assert int(m_bonsai.group(1)) == EXPECTED_CANONICAL, msg.format(
        old=EXPECTED_CANONICAL, new=m_bonsai.group(1), deps=deps)


# ---------------------------------------------------------------------------
# 2. Censo de fallbacks: alteração sem derivação quebra o teste
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relpath", sorted(FALLBACK_SITES))
def test_known_fallbacks_match_census(relpath: str) -> None:
    desc, pattern, recorded = FALLBACK_SITES[relpath]
    src = (SRC / relpath).read_text()
    m = re.search(pattern, src)
    if m is None:
        # Literal sumiu: ou foi consolidado (deve derivar da fonte) ou mudou
        # de forma. Falha se não houver evidência de derivação do registry.
        derives = "provider_registry" in src or "canonical_context" in src
        assert derives, (
            f"{relpath}: fallback '{desc}' desapareceu sem derivação do "
            "registry — ou a consolidação aconteceu (derive explicitamente "
            "e atualize o censo) ou o literal mudou de forma."
        )
        return
    assert int(m.group(1)) == recorded, (
        f"{relpath}: '{desc}' mudou {recorded} → {m.group(1)} sem derivação "
        "do registry — verifique a propagação da fonte antes de aceitar "
        "(benchmark spec, categoria M)."
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
        "novos hardcodes de contexto fora do censo — derive do registry "
        "(provider_registry.ModelCaps.context) ou, se legítimo, registre no "
        "censo de test_context_drift.py:\n" + "\n".join(offenders)
    )
