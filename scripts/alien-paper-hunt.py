#!/usr/bin/env python3
"""F143: caça LIMITADA de papers a partir de hipoteses/atoms do alien.

Tetos duros: <=6 papers, 2 ciclos, 30 min, nenhum treino, nenhum serviço.
Fluxo: arXiv -> dedup -> PDF -> texto -> RAG -> re-alien -> gate de novidade.
"""
import argparse, json, subprocess, time, urllib.parse, xml.etree.ElementTree as ET
from pathlib import Path

THEMES = (
    '(abs:"data constrained" OR abs:"repetition" AND abs:"scaling law") AND cat:cs.CL',
    '(abs:"data mixture" AND abs:"staged pretraining") AND cat:cs.CL',
    '(abs:"weight decay" AND abs:"overfitting") AND cat:cs.CL',
    '(all:"elastic depth" OR abs:"looped transformer") AND cat:cs.CL',
    '(abs:"halting" AND abs:"looped") AND cat:cs.CL',
    '(abs:"speculative decoding" AND abs:"looped") AND cat:cs.CL',
    '(abs:"byte-level" AND abs:"tokenization") AND cat:cs.CL',
    '(abs:"educational corpus" OR abs:"data curation") AND cat:cs.CL',
    '(abs:"residual normalization" OR abs:"massive activations") AND cat:cs.CL')
NS = {"a": "http://www.w3.org/2005/Atom"}
DIR = Path("/home/nixos/Books/papers/frontier-2026-11-27")

def arxiv(q, limit=2):
    url = ("https://export.arxiv.org/api/query?search_query=" +
           urllib.parse.quote(q, safe="") + f"&start=0&max_results={limit}"
           "&sortBy=submittedDate&sortOrder=descending")
    r = subprocess.run(["curl", "-sSL", "--max-time", "25", url],
                       capture_output=True, text=True, timeout=35)
    if r.returncode or not r.stdout.strip():
        return []
    try:
        root = ET.fromstring(r.stdout)
    except ET.ParseError:
        return []
    out = []
    for e in root.findall("a:entry", NS):
        aid = (e.findtext("a:id", "", NS) or "").rsplit("/", 1)[-1]
        out.append({"id": aid.split("v")[0],
                    "title": " ".join((e.findtext("a:title", "", NS) or "").split()),
                    "summary": " ".join((e.findtext("a:summary", "", NS) or "").split())[:800]})
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-papers", type=int, default=6)
    ap.add_argument("--cycles", type=int, default=2)
    a = ap.parse_args()
    t0 = time.perf_counter()
    DIR.mkdir(parents=True, exist_ok=True)
    known = {p.stem for p in Path("/home/nixos/Books/papers").rglob("*")
             if p.is_file() and (p.stem[:4].isdigit() or p.stem.startswith("arxiv"))}
    picked, cycles = [], 0
    for cycle in range(a.cycles):
        cycles = cycle + 1
        found = []
        for q in THEMES:
            for r in arxiv(q):
                if r["id"] in known or any(x["id"] == r["id"] for x in found): continue
                found.append(r)
                if len(found) >= 3: break
            if len(found) >= 3: break
        if not found:
            break
        for r in found:
            if len(picked) >= a.max_papers: break
            pdf = DIR / f"{r['id']}.pdf"
            if not pdf.is_file():
                subprocess.run(["curl", "-sSL", "--fail", "--max-time", "90", "-o", str(pdf),
                                f"https://arxiv.org/pdf/{r['id']}"],
                               capture_output=True, timeout=100)
            if pdf.is_file() and pdf.stat().st_size > 10000:
                full = r["summary"]
                try:
                    import fitz
                    doc = fitz.open(str(pdf))
                    full = "\n".join(page.get_text() for page in doc)[:200000]
                    doc.close()
                except Exception as e:
                    full += f"\n[fitz indisponivel: {type(e).__name__}]"
                (DIR / f"{r['id']}.txt").write_text(
                    f"# {r['title']}\n# arxiv:{r['id']}\n\n{full}\n", encoding="utf-8")
                picked.append({**r, "bytes": pdf.stat().st_size})
        if len(picked) >= a.max_papers or time.perf_counter()-t0 > 1500:
            break
    # indexar no RAG (se houver arquivos novos)
    indexed = 0
    if picked:
        try:
            from jarvis.core.rag import HybridIndexer
            hi = HybridIndexer()
            indexed = hi.index_directory(str(DIR), force=False, deadline_s=300)
        except Exception as e:
            indexed = f"erro: {type(e).__name__}: {str(e)[:120]}"
    res = {"event": "alien_paper_hunt", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "cycles": cycles, "papers": picked, "rag_indexed": indexed,
           "wall_seconds": round(time.perf_counter()-t0, 1),
           "next_gate": "re-alien com novidade externa; so promover se atom novo nao coberto",
           "note": "nenhum treino; tetos 6 papers/2 ciclos/30min"}
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"papers": len(picked), "indexed": indexed,
                      "seconds": res["wall_seconds"]}))

if __name__ == "__main__":
    main()
