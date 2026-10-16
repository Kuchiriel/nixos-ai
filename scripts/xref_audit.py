#!/usr/bin/env python3
"""xref_audit.py — N<->N audit: docs <-> code references.
Extracts wikilinks [[x]], md links (p), bare code-path mentions from .md,
and doc mentions ([[...]], .md paths) from code. Resolves targets,
reports: dangling, orphans (docs unlinked, code unmentioned),
one-way vs two-way links.
"""
import json
import re
import sys
from pathlib import Path

ROOTS = {
    "canary": Path("/home/nixos/projects/canary-official"),
    "nixos": Path("/home/nixos/projects/nixos-ai"),
    "otclient": Path("/home/nixos/projects/otclient"),
}
SKIP = {".git", "node_modules", ".venv", "__pycache__", ".ragignore"}
CODE_EXT = {".py", ".lua", ".nix", ".sh", ".cpp", ".h", ".otui", ".ts"}

WIKI_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
MDLINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
CODEPATH_RE = re.compile(
    r"(?:^|[\s(`'\"])"
    r"((?:dataset|data-sandbox|data|docker|modules|home-manager|scripts|"
    # (11/10) longest-first + boundary: 'src/pch.hpp' capturava
    # 'src/pch.h' (falso dangling).
    r"docs|tools|tests|src|otclient|canary-official|nixos-ai)/"
    r"[A-Za-z0-9_.\-+/]+?\.(?:otui|cpp|json|xml|md|py|lua|nix|sh|h|ts))"
    r"(?![A-Za-z0-9_])"
)
DOCMENTION_RE = re.compile(
    r"(?:^|[\s(`'\"])"
    r"((?:docs|dataset|data-sandbox|modules)/[A-Za-z0-9_.\-+/]+?\.md)"
    r"|(\[\[[^\]]+\]\])"
)


def files(root, exts):
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(s in p.parts for s in SKIP):
            continue
        if p.suffix in exts:
            out.append(p)
    return out


def resolve_wiki(root, base_dir, link, name_index):
    """Obsidian semantics: doc-dir first, repo root, then filename-anywhere.
    (11/10) the first version joined repo-root only, so '../../HANDOFF.md'
    resolved OUTSIDE the repo and every bare '[[agent-harness]]' dangled.
    Returns Path or None."""
    link = link.strip()
    if "/" in link or link.startswith("."):
        for base in (base_dir, root):
            for c in (base / (link + ".md"), base / link,
                      base / (link + "/README.md")):
                if c.is_file():
                    return c
        return None
    seen, hits = set(), []
    for cand in (link, link + ".md"):
        for p in name_index.get(cand, []):
            if str(p) not in seen:
                seen.add(str(p))
                hits.append(p)
    if len(hits) == 1:
        return hits[0]
    return None  # 0 = dangling, >1 = ambiguous (also reported dangling)


MONO = Path("/home/nixos/projects")
MONO_DIRS = {p.name for p in MONO.iterdir() if p.is_dir()}


def resolve_rel(base_dir, target):
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return "external"
    # (11/10) fallback chain: base_dir FIRST (repo-local 'docs/x' beats
    # monorepo '~/projects/docs/x'), then monorepo-rooted cross links.
    # The first version joined MONO whenever the first segment matched
    # (docs/ exists in ~/projects!), breaking every repo-local docs/ ref.
    cands = [base_dir / target]
    first = target.split("/")[0]
    if first in MONO_DIRS:
        cands.append(MONO / target)
    for c in cands:
        t = c.resolve()
        for root in ROOTS.values():
            try:
                t.relative_to(root.resolve())
                if t.is_file():
                    return t
            except ValueError:
                continue
    return None


def key_of(path):
    """'repo/relpath' for a resolved path, else None (outside all roots)."""
    for rp, rt in ROOTS.items():
        try:
            return f"{rp}/{path.relative_to(rt.resolve())}"
        except ValueError:
            continue
    return None


def main():
    docs = {}   # key: relpath repo/name -> {out_links: set, file}
    code = {}
    for repo, root in ROOTS.items():
        for p in files(root, {".md"}):
            try:
                t = p.read_text(errors="ignore")
            except OSError:
                continue
            key = f"{repo}/{p.relative_to(root)}"
            outs = set()
            for m in WIKI_RE.finditer(t):
                outs.add(("wiki", m.group(1), None))
            for m in MDLINK_RE.finditer(t):
                outs.add(("mdlink", m.group(1), None))
            for m in CODEPATH_RE.finditer(t):
                outs.add(("path", m.group(1), None))
            docs[key] = {"file": str(p), "outs": sorted(outs)}
        for p in files(root, CODE_EXT):
            try:
                t = p.read_text(errors="ignore")
            except OSError:
                continue
            key = f"{repo}/{p.relative_to(root)}"
            outs = set()
            for m in DOCMENTION_RE.finditer(t):
                outs.add(m.group(1) or m.group(2))
            # only keep files that mention docs
            if outs:
                code[key] = {"file": str(p), "outs": sorted(outs)}
    # backlink index: which docs are TARGETED by wikilink/path
    targeted = {}
    dangling = []
    # filename index for bare Obsidian links ([[agent-harness]])
    name_index = {}
    for key2, d2 in docs.items():
        p2 = Path(d2["file"])
        name_index.setdefault(p2.name, []).append(p2)
        name_index.setdefault(p2.stem, []).append(p2)
    for key, d in docs.items():
        repo = key.split("/")[0]
        root = ROOTS[repo]
        base_dir = Path(d["file"]).parent
        for kind, link, _ in d["outs"]:
            tgt = None
            if kind == "wiki":
                r = resolve_wiki(root, base_dir, link, name_index)
                if r is None:
                    dangling.append((key, link))
                else:
                    tgt = key_of(r)
            elif kind == "mdlink":
                r = resolve_rel(Path(d["file"]).parent, link)
                if r is None:
                    dangling.append((key, link))
                elif r != "external":
                    for rp, rt in ROOTS.items():
                        try:
                            tgt = f"{rp}/{r.relative_to(rt.resolve())}"
                            break
                        except ValueError:
                            continue
            elif kind == "path":
                hit = None
                for rp, rt in ROOTS.items():
                    if (rt / link).is_file():
                        hit = f"{rp}/{link}"
                        break
                if hit is None and link.split("/")[0] in MONO_DIRS:
                    if (MONO / link).is_file():
                        hit = link  # rooted monorepo path
                if hit is None:
                    dangling.append((key, link))
                else:
                    tgt = hit
            if tgt:
                targeted.setdefault(tgt, set()).add(key)
    doc_keys = set(docs)
    orphans = sorted(k for k in doc_keys if k not in targeted)
    # two-way: doc A links doc B and B links A (by key)
    two_way = set()
    linkmap = {}
    for key, d in docs.items():
        ts = set()
        for kind, link, _ in d["outs"]:
            repo = key.split("/")[0]
            root = ROOTS[repo]
            if kind == "wiki":
                r = resolve_wiki(root, Path(d["file"]).parent,
                                 link, name_index)
                if r:
                    t2 = key_of(r)
                    if t2:
                        ts.add(t2)
        linkmap[key] = ts
    for a, ts in linkmap.items():
        for b in ts:
            if b in linkmap and a in linkmap[b]:
                two_way.add(tuple(sorted((a, b))))
    rep = {
        "n_docs": len(docs),
        "n_code_with_doc_refs": len(code),
        "n_dangling": len(dangling),
        "dangling": sorted(set(dangling)),
        "n_orphan_docs": len(orphans),
        "orphan_docs": orphans,
        "n_two_way_pairs": len(two_way),
        "two_way_pairs": sorted(two_way),
        "code_with_doc_refs": sorted(code),
    }
    json.dump(rep, open("/tmp/opencode/xref_report.json", "w"),
              ensure_ascii=False, indent=1)
    print(f"docs={len(docs)} code_w_refs={len(code)} "
          f"dangling={len(dangling)} orphans={len(orphans)} "
          f"two_way={len(two_way)}")


if __name__ == "__main__":
    main()
