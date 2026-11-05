#!/usr/bin/env python3
"""fix_refs.py — mechanical doc-ref repairs (all verified before write).
1. tests/test_test_isolation.py -> modules/ai/jarvis/tests/... (moved)
2. bare ../../HANDOFF|README (no .md) -> + .md (iff target exists)
3. canary dataset/maps/*.py -> dataset/maps/src/*.py (iff target exists)
4. docs/HANDOFF-2026-09-25.md -> docs/HANDOFF-2026-10-05.md (superseded)
Only writes files with >=1 verified replacement. Prints report.
"""
import re
from pathlib import Path

NIX = Path("/home/nixos/projects/nixos-ai")
CAN = Path("/home/nixos/projects/canary-official")
PROJ = Path("/home/nixos/projects")


def md_files(root):
    out = []
    for p in root.rglob("*.md"):
        if ".git" in p.parts or "node_modules" in p.parts:
            continue
        out.append(p)
    return out


def verified_replace(text, old, new):
    if old in text:
        return text.replace(old, new), text.count(old)
    return text, 0


report = []


def process(path, rules):
    try:
        t = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return
    orig, n_all = t, 0
    for old, new in rules:
        t, n = verified_replace(t, old, new)
        n_all += n
    if n_all and t != orig:
        path.write_text(t, encoding="utf-8")
        report.append((str(path), n_all))


# 1+2+4: nixos-ai
iso_old = "tests/test_test_isolation.py"
iso_new = "modules/ai/jarvis/tests/test_test_isolation.py"
for p in md_files(NIX):
    try:
        t = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    rules = []
    if iso_old in t:
        rules.append((iso_old, iso_new))
    # bare HANDOFF/README/BUFFY/AGENTS refs (../ chains, no extension)
    for m in set(re.findall(r"((?:\.\./)+)(HANDOFF|README|BUFFY|AGENTS)(?![\w.])", t)):
        prefix, name = m
        tgt = (p.parent / (prefix + name + ".md"))
        if tgt.is_file():
            rules.append((prefix + name, prefix + name + ".md"))
    if "docs/HANDOFF-2026-09-25.md" in t:
        rules.append(("docs/HANDOFF-2026-09-25.md",
                      "docs/HANDOFF-2026-10-05.md"))
    if rules:
        process(p, rules)

# 3: canary maps move (verify target under src/)
moved = ["gerar_mapa.py", "gerar_otbm.py", "validar_otbm.py",
         "visual_debug.py", "common.py"]
for p in md_files(CAN):
    try:
        t = p.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        continue
    rules = []
    for name in moved:
        old = f"dataset/maps/{name}"
        new = f"dataset/maps/src/{name}"
        if old in t and (CAN / new).is_file():
            rules.append((old, new))
    if rules:
        process(p, rules)

print(f"files rewritten: {len(report)}")
for path, n in report[:30]:
    print(f"  {n}x {path}")
