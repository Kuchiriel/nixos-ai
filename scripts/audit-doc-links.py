#!/usr/bin/env python3
"""Verifica APENAS links [[wiki]] e markdown relativos em docs/audit/.

Resolve como Obsidian: dir do doc → raiz do repo → nome em qualquer lugar.
READ-ONLY; sai com relatorio JSON. Nao conta paths absolutos como quebrados.
"""
from __future__ import annotations
import json, re, sys
from pathlib import Path

ROOT = Path("/home/nixos/projects/nixos-ai")
DOCS = ROOT / "docs" / "audit"
WIKI = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
MD = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
SKIP = {".git", "node_modules", "__pycache__"}


def resolve(base: Path, target: str) -> bool:
    t = target.strip()
    if t.startswith(("http://", "https://", "mailto:")):
        return True
    for p in (base / t, base / (t + ".md"), ROOT / t, ROOT / (t + ".md")):
        if p.is_file() or p.is_dir():
            return True
    # nome em qualquer lugar do repo (Obsidian bare links)
    hits = list(ROOT.rglob(t)) + list(ROOT.rglob(t + ".md"))
    return any(p.is_file() for p in hits[:3])


def main():
    broken = []
    checked = 0
    for f in sorted(DOCS.rglob("*.md")):
        if any(s in f.parts for s in SKIP):
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in WIKI.finditer(text):
            checked += 1
            if not resolve(f.parent, m.group(1)):
                broken.append({"file": str(f.relative_to(ROOT)),
                               "kind": "wiki", "target": m.group(1)})
        for m in MD.finditer(text):
            checked += 1
            if not resolve(f.parent, m.group(1)):
                broken.append({"file": str(f.relative_to(ROOT)),
                               "kind": "md", "target": m.group(1)})
    out = {"checked": checked, "broken": len(broken), "sample": broken[:25]}
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
