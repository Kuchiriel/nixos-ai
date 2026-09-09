"""Completion policy — DONE baseado em evidência, nunca em afirmação.

Regra P0: o Agent não pode declarar conclusão quando:
- o último resultado de tool é erro (trailing-error);
- arquivos que ele disse ter escrito não existem;
- .py escrito não compila (AST);
- nada executou com sucesso (zero ground truth).

Veredito: VERIFIED | UNVERIFIED | STUCK | FAILED + evidence/missing.
Sem NLP de intenção: só fatos estruturais do run (mensagens + árvore).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CompletionVerdict:
    status: str  # VERIFIED | UNVERIFIED | STUCK | FAILED
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


_CREATION_VERBS = re.compile(
    r"(criad[oa]|criou|foi criado|escrit[oa]|escrevi|salv[oa]|salvei|"
    r"created|wrote|written|saved|adicionad[oa]|adicionei)",
    re.IGNORECASE,
)
_PATH_LIKE = re.compile(r"[`\"']?([\w\-./]+\.(?:py|md|nix|txt|json|sh|toml))[,.`\"']?")


_DENIAL_WORDS = (r"não existe|não há|não encontrado|not found|no such file|"
                 r"ausente|missing")
_PATH_EXT = r"[\w\-./]+\.(?:py|md|nix|txt|json|sh|toml)"
_DENIAL = re.compile(
    rf"(?:{_DENIAL_WORDS})\b.{{0,40}}?[`\"']?({_PATH_EXT})"
    rf"|`?[`\"']?({_PATH_EXT})[`\"']?.{{0,40}}?(?:{_DENIAL_WORDS})",
    re.IGNORECASE,
)


def _denied_but_observed(messages: list[dict]) -> list[str]:
    """Nega na resposta o que a observação continha (ex.: N2 real).

    'servico.nix não existe' quando o ls listou servico.nix = falsa
    conclusão semântica detectável estruturalmente (containment).
    """
    observed = "\n".join(
        m.get("content", "") for m in messages if m.get("role") == "tool")
    if not observed:
        return []
    out = []
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            for mm in _DENIAL.finditer(m["content"]):
                p = mm.group(1) or mm.group(2)
                if p in observed and p not in out:
                    out.append(p)
            break
    return out


def _claimed_artifacts(messages: list[dict]) -> list[str]:
    """Arquivos que o texto final afirma ter criado/escrito."""
    out = []
    for m in reversed(messages):
        if m.get("role") == "assistant" and m.get("content"):
            text = m["content"]
            if _CREATION_VERBS.search(text):
                for mm in _PATH_LIKE.finditer(text):
                    p = mm.group(1)
                    if p not in out:
                        out.append(p)
            break
    return out


def _written_paths(messages: list[dict]) -> list[str]:
    """Paths passados a write_file/str_replace (intenção de escrita)."""
    out = []
    for m in messages:
        for tc in m.get("tool_calls") or []:
            fn = (tc.get("function") or {})
            if fn.get("name") in ("write_file", "str_replace"):
                try:
                    import json
                    a = fn.get("arguments", {})
                    a = json.loads(a) if isinstance(a, str) else a
                    if isinstance(a, dict) and a.get("path"):
                        out.append(str(a["path"]))
                except Exception:
                    pass
    return out


def _last_tool_error(messages: list[dict]) -> str | None:
    """Conteúdo do último resultado de tool, se for erro."""
    for m in reversed(messages):
        if m.get("role") == "tool":
            c = (m.get("content") or "").strip()
            if c.upper().startswith("ERROR"):
                return c[:200]
            return None
    return None


def _any_tool_success(messages: list[dict]) -> bool:
    for m in messages:
        if m.get("role") == "tool":
            c = (m.get("content") or "").strip()
            if c and not c.upper().startswith("ERROR"):
                return True
    return False


def check_completion(messages: list[dict],
                     project_root: str | None = None) -> CompletionVerdict:
    """Veredito estrutural de conclusão."""
    ev: list[str] = []
    miss: list[str] = []
    if project_root is None:
        # Raiz canônica (task-ctx > env > walk-up): live mostra CWD, mas
        # o Agent opera sob use_project_root — sem isso, artefatos "somem"
        # e tudo vira UNVERIFIED (observado em teste com tmp_path).
        try:
            from jarvis.core.paths import find_repo_root
            root = find_repo_root()
        except Exception:
            root = Path(".")
    else:
        root = Path(project_root)
    ok = True

    if not _any_tool_success(messages):
        return CompletionVerdict("UNVERIFIED", [],
                                 ["nenhuma tool com sucesso (zero ground truth)"])

    trailing = _last_tool_error(messages)
    if trailing is not None:
        ok = False
        miss.append(f"último resultado é erro: {trailing[:120]}")

    for p in _written_paths(messages):
        fp = (root / p) if not Path(p).is_absolute() else Path(p)
        if not fp.exists():
            ok = False
            miss.append(f"arquivo escrito não existe: {p}")
            continue
        ev.append(f"arquivo existe: {p}")
        if fp.suffix == ".py":
            try:
                ast.parse(fp.read_text(encoding="utf-8"))
                ev.append(f"{p} compila (AST)")
            except (SyntaxError, OSError) as e:
                ok = False
                miss.append(f"{p} não compila: {e}")

    # Afirmação de criação sem chamada de escrita: "criei X" sem nenhum
    # write_file/str_replace no run = falsa conclusão clássica (observado:
    # C2 afirmou dobra.py sem chamar write). Só vale quando o run usou
    # tools (runs puramente textuais não têm como provar nada estrutural).
    _used_tools = any(m.get("tool_calls") for m in messages)
    if _used_tools:
        _created = _claimed_artifacts(messages)
        _made = set(_written_paths(messages))
        for c in _created:
            if c not in _made:
                ok = False
                miss.append(f"afirma artefato sem escrita: {c}")
        for d in _denied_but_observed(messages):
            ok = False
            miss.append(f"nega evidência observada: {d}")

    if ok:
        ev.append("sem erro final; artefatos verificados")
        return CompletionVerdict("VERIFIED", ev, [])
    return CompletionVerdict("UNVERIFIED", ev, miss)


def classify_error(output: str) -> str:
    """Classificação grosseira p/ política de retry (harness, não modelo)."""
    o = (output or "").lower()
    if "timed out" in o or "timeout" in o or "temporar" in o:
        return "transient"
    if "denied" in o or "not allowed" in o or "approval" in o:
        return "policy"
    if "not found" in o or "no such file" in o:
        return "missing"
    if "invalid" in o or "malformed" in o or "unknown tool" in o:
        return "bad-request"
    if o.startswith("error"):
        return "failed"
    return "ok"
