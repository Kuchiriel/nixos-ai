"""ContextAssembler único — Fase 3 (ADR-005).

Um MECANISMO de montagem, seções por adapter: o REPL precisa de repo_map,
o one-shot não — a diferença legítima vive na LISTA de seções, nunca em
código de montagem duplicado.

Fase 3: builders puros das seções compartilhadas (byte-idênticos ao que
agent.py montava inline) + Assembler com provenance (quais seções entraram —
observabilidade antes de controle). agent.py (base canônica) consome;
dev.py adere na F8 (thin).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# -- builders puros (seções compartilhadas) --------------------------------

def environment_block(for_container: bool = False) -> str:
    """Bloco ENVIRONMENT — byte-idêntico ao inline de Agent.run.

    F-pesquisa (26/09): data/hora/timezone INJETADAS estaticamente (prática
    consolidada dos harnesses: 1 linha sempre correta > 1 turn pedindo
    `date` que o modelo pode pular — e elimina a regra do AGENTS.md que
    mandava o modelo rodar date/timedatectl).

    for_container (29/09, N-cell): trials rodam tools no CONTAINER mas o
    processo é do host — CWD do host no prompt virava exploração de
    `/home/nixos/...` dentro do container (DeepSeek vagou no host e zerou).
    No sandbox, declara o mundo verdadeiro (/app) e nega o host.
    """
    if for_container:
        try:
            from datetime import datetime
            _now = datetime.now().astimezone()
            _ts = (_now.strftime("%Y-%m-%d %H:%M %Z")
                   + f" ({_now.astimezone().tzname()})")
        except Exception:
            _ts = "unknown"
        return (
            "\n\nENVIRONMENT:\n"
            "- Sandbox: Harbor container (isolated)\n"
            "- CWD: /app\n"
            "- Host paths (e.g. /home/...) DO NOT EXIST here — "
            "never use them\n"
            f"- Now: {_ts}"
        )
    try:
        import platform
        import os
        from datetime import datetime
        _now = datetime.now().astimezone()
        return (
            "\n\nENVIRONMENT:\n"
            f"- OS: {platform.system()} {platform.release()}\n"
            f"- Python: {platform.python_version()}\n"
            f"- CWD: {os.getcwd()}\n"
            f"- User: {os.environ.get('USER', 'unknown')}\n"
            f"- Now: {_now.strftime('%Y-%m-%d %H:%M %Z')} "
            f"({_now.astimezone().tzname()})"
        )
    except Exception:
        return ""


def user_profile_block() -> str:
    """Bloco USER PREFERENCES — byte-idêntico ao inline de Agent.run."""
    try:
        from jarvis.core.user_profile import UserProfile, build_context_block
        profile = UserProfile()
        profile.load()
        block = build_context_block(profile)
        if block:
            return f"\n\nUSER PREFERENCES:\n{block}"
        return ""
    except Exception:
        return ""


def persona_section(persona: Any) -> str:
    """Render PERSONA ATIVA — o GATE (explícita vs implícita) fica no caller."""
    if persona and getattr(persona, "system_prompt_additions", None):
        return (f"\n\nPERSONA ATIVA: {persona.name} ({persona.role})\n"
                f"{persona.system_prompt_additions}")
    return ""


def lessons_block(memory: Any, prompt: str,
                  emit: Callable[..., None] | None = None) -> str:
    """Bloco AVOID (past errors) — lessons qualificadas pelo PROMPT.

    emit: callback de telemetria p/ outage distinguível de 'sem lessons'.
    """
    if not memory:
        return ""
    try:
        lessons = memory.lessons(prompt, top_k=3)
        if lessons:
            return f"\n\nAVOID (past errors):{lessons}"
        return ""
    except Exception as e:  # noqa: BLE001
        if emit is not None:
            try:
                emit("lessons_unavailable", detail={
                    "error": type(e).__name__, "msg": str(e)[:160]})
            except Exception:
                pass
        return ""


# -- assembler ---------------------------------------------------------------

@dataclass
class Section:
    """Uma seção nomeada do contexto (builder puro + predicado)."""

    name: str
    build: Callable[[], str]
    provenance: dict[str, Any] = field(default_factory=dict)


class ContextAssembler:
    """Monta o system prompt por seções, registrando provenance.

    Uso:
        asm = ContextAssembler()
        asm.add("identity", lambda: "You are JARVIS, ...")
        asm.add("environment", environment_block)
        system, prov = asm.assemble()
    """

    def __init__(self) -> None:
        self._sections: list[Section] = []

    def add(self, name: str, build: Callable[[], str],
            **provenance: Any) -> ContextAssembler:
        self._sections.append(Section(name, build, dict(provenance)))
        return self

    def assemble(self) -> tuple[str, dict[str, Any]]:
        parts: list[str] = []
        included: list[str] = []
        for sec in self._sections:
            try:
                text = sec.build() or ""
            except Exception:
                text = ""
            if text:
                parts.append(text)
                included.append(sec.name)
        return "".join(parts), {"sections": included,
                                "count": len(included)}
