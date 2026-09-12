#!/usr/bin/env python3
"""world.py — verificadores objetivos de estado do mundo (benchmark-side).

NÃO é tool do modelo: o harness consulta independentemente, de modo
que "modelo disse que fez" nunca vire success.
"""
from __future__ import annotations

import os


def file_exists(path: str) -> bool:
    return os.path.isfile(path)


def file_content(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def dir_has_n_files(path: str, n: int) -> bool:
    try:
        return (os.path.isdir(path)
                and sum(1 for _ in os.listdir(path)) == n)
    except OSError:
        return False


def check_file(path: str, exact: str | None = None,
               contains: list[str] | None = None) -> dict:
    """Arquivo existe (+ conteúdo exato/contém)."""
    c = file_content(path)
    if c is None:
        return {"ok": False, "reason": "arquivo inexistente"}
    if exact is not None and c.strip() != exact.strip():
        return {"ok": False, "reason": "conteúdo difere do esperado"}
    for needle in contains or []:
        if needle not in c:
            return {"ok": False, "reason": f"falta {needle!r}"}
    return {"ok": True}


def check_dir(path: str, n: int) -> dict:
    if not os.path.isdir(path):
        return {"ok": False, "reason": "diretório inexistente"}
    got = sum(1 for _ in os.listdir(path))
    if got != n:
        return {"ok": False, "reason": f"tem {got} itens, esperado {n}"}
    return {"ok": True}


LAB_STATE_URL = "http://localhost:8931/state"
LAB_RESET_URL = "http://localhost:8931/reset"


def lab_reset() -> None:
    import urllib.request
    try:
        urllib.request.urlopen(LAB_RESET_URL, timeout=5).read()
    except Exception:
        pass


def lab_state() -> dict:
    import json
    import urllib.request
    try:
        with urllib.request.urlopen(LAB_STATE_URL, timeout=5) as r:
            return json.load(r)
    except Exception as e:
        return {"error": str(e)[:100]}


def check_dom(url: str, must_contain: list[str] | None = None,
              must_absent: list[str] | None = None,
              reset_after: bool = True) -> dict:
    """Estado SERVIDOR da página lab (independente do browser do modelo).

    O DOM é local por sessão: verificar via browser próprio NUNCA veria
    o clique do modelo. O servidor lab registra clicks/fills; o check
    lê /state e reseta p/ a próxima run.
    """
    st = lab_state()
    if "error" in st:
        return {"ok": False, "reason": st["error"]}
    blob = json.dumps(st, ensure_ascii=False)
    if reset_after:
        lab_reset()
    for needle in must_contain or []:
        if needle not in blob:
            return {"ok": False, "reason": f"estado sem {needle!r}: {blob[:120]}"}
    for needle in must_absent or []:
        if needle in blob:
            return {"ok": False, "reason": f"estado ainda tem {needle!r}"}
    return {"ok": True}
