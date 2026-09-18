"""Offline documentation acquisition layer (§12 da missão sanitize).

Escopo honesto: NADA baixa datasets enormes sozinho. Este módulo:
  1. descobre documentação que JÁ existe localmente (NixOS-first: não
     baixar o que o ambiente/store já expõe);
  2. valida specs de aquisição SELETIVA (url + sha256 + size cap) para
     download futuro explícito (Wikipedia ZIM, Python docs) — sem rede aqui;
  3. garante o layout de storage sob STATE/sanitize/sources/.

Layout (convenção repo: STATE_DIR; ver doc_sanitize._state_base):
  sources/wikipedia/  — ZIMs seletivos (specs, não downloads)
  sources/python/     — docs Python 3.13 (specs / espelhos locais)
  sources/nixos/      — descoberta local (nixos-option, man, store doc)
"""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STATE_DIR_ENV = "JARVIS_STATE_DIR"

# Teto anti-DoS p/ qualquer aquisição futura (§19: bounded).
MAX_ACQUIRE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB por artefato


def _state_base() -> Path:
    base = os.environ.get(STATE_DIR_ENV, "")
    p = Path(base) if base else Path.home() / ".local" / "state" / "jarvis"
    for sub in ("wikipedia", "python", "nixos"):
        (p / "sanitize" / "sources" / sub).mkdir(parents=True, exist_ok=True)
    return p


@dataclass
class AcquisitionSpec:
    """Aquisição seletiva: o QUE baixar, COMO verificar. Sem rede aqui."""
    name: str
    url: str
    sha256: str = ""          # vazio = ainda não fixado (pendente)
    max_bytes: int = MAX_ACQUIRE_BYTES
    dest_subdir: str = "wikipedia"  # wikipedia | python | nixos
    status: str = "pending"   # pending | available-local | fetched | failed

    def validate(self) -> list[str]:
        """Erros determinísticos da spec (sem rede)."""
        errs: list[str] = []
        if not self.name.strip():
            errs.append("nome vazio")
        if not (self.url.startswith("https://") or self.url.startswith("file://")):
            errs.append(f"url insegura/inesperada: {self.url}")
        if self.sha256 and (len(self.sha256) != 64 or not all(
                c in "0123456789abcdef" for c in self.sha256.lower())):
            errs.append("sha256 malformado (esperado 64 hex)")
        if self.max_bytes <= 0 or self.max_bytes > MAX_ACQUIRE_BYTES:
            errs.append(f"max_bytes fora de (0, {MAX_ACQUIRE_BYTES}]")
        if self.dest_subdir not in ("wikipedia", "python", "nixos"):
            errs.append(f"dest_subdir inválido: {self.dest_subdir}")
        return errs

    def dest_path(self, state: Path | None = None) -> Path:
        base = state or _state_base()
        fname = self.url.rstrip("/").rsplit("/", 1)[-1] or self.name
        # sanitiza nome (sem traversal): só basename, sem .. nem /
        fname = Path(fname).name.replace("..", "_")
        return base / "sanitize" / "sources" / self.dest_subdir / fname


def verify_local_file(path: str | Path, *, expected_sha256: str = "",
                       max_bytes: int = MAX_ACQUIRE_BYTES) -> dict[str, Any]:
    """Verifica artefato local: existe, tamanho, sha (se esperado)."""
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "error": f"ausente: {p}"}
    size = p.stat().st_size
    if size > max_bytes:
        return {"ok": False, "error": f"{size} > cap {max_bytes}"}
    out: dict[str, Any] = {"ok": True, "path": str(p), "bytes": size}
    if expected_sha256:
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        out["sha256"] = h.hexdigest()
        out["match"] = h.hexdigest().lower() == expected_sha256.lower()
        if not out["match"]:
            out["ok"] = False
            out["error"] = "sha256 divergente"
    return out


def discover_nixos_docs() -> dict[str, Any]:
    """Documentação NixOS já local: nixos-option, man pages, store docs.

    Não baixa nada. Retorna disponibilidade + caminhos verificados.
    """
    found: dict[str, Any] = {}
    nixos_option = shutil.which("nixos-option")
    found["nixos_option"] = {"available": bool(nixos_option), "path": nixos_option or ""}
    man_dirs = [d for d in ("/run/current-system/sw/share/man",
                            "/etc/profiles/per-user/nixos/share/man",
                            "/usr/share/man")
                if Path(d).is_dir()]
    found["man_dirs"] = man_dirs
    store_docs: list[str] = []
    for cand in ("/run/current-system/sw/share/doc",):
        p = Path(cand)
        if p.is_dir():
            try:
                store_docs.extend(sorted(str(x) for x in p.iterdir())[:50])
            except OSError:
                pass
    found["store_doc_dir"] = store_docs
    # manual NixOS: procura html/pdf do manual no store (sem baixar)
    manual: list[str] = []
    try:
        import subprocess
        r = subprocess.run(
            ["find", "/nix/store", "-maxdepth", "2", "-name", "*nixos-manual*",
             "-o", "-maxdepth", "2", "-name", "*manual.html*"],
            capture_output=True, text=True, timeout=30)
        manual = sorted(set(r.stdout.split()))[:20]
    except Exception:
        pass
    found["store_manuals"] = manual
    found["ok"] = True
    return found


def default_specs() -> list[AcquisitionSpec]:
    """Specs seletivas padrão (pendentes — download é ato explícito futuro)."""
    return [
        AcquisitionSpec(
            name="python-3.13-docs-html",
            url="https://docs.python.org/3.13/archives/python-3.13-docs-html.tar.bz2",
            dest_subdir="python"),
        AcquisitionSpec(
            name="wikipedia-seletiva",
            url="https://download.kiwix.org/zim/wikipedia/",
            dest_subdir="wikipedia"),
    ]
