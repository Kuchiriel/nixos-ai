"""Busca lexical no corpus offline de sobrevivência (SQLite FTS5).

Por que existe (14/11/2026): a busca densa do `HybridSearch` é cara e frágil no
cenário que importa — sem internet, sem servidor de embedding, sem LLM. O
`offline_survival` respondia "Dulce de Leche" para "picada de cobra" (1/15 de
acerto) porque o corpus não tinha primeiros socorros e a query em PT não tinha
ponte para o texto em EN. Este módulo usa o MESMO índice FTS5 do celular
(`~/bin/offline`, 18.943 docs, 15/15 nas 15 perguntas de referência):
tokenizer porter unicode61, glossário PT→EN compartilhado, cobertura de termos
e bônus de intenção acionável.

O banco (`data/offline/corpus.db`, ~24 MB) é gerado a partir de:
  - 45 .md curados (NOMAD + Kiwix water)
  - FM 4-25.11 First Aid (US Army, domínio público) — 298 chunks
  - FM 90-3 Desert Operations (domínio público) — 879 chunks
  - FirstAidQA (CC BY 4.0, sintético — rotulado como tal)
  - NHS Medicines / Kiwix / Based.Cooking (export do Qdrant) — 12.231 chunks

Sem embedding, sem rede, determinístico. O `offline.py` prefere este módulo e
cai no `HybridSearch` só se o banco não existir.
"""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

TOKEN_RE = re.compile(r"[a-z0-9]+")

STOP = set("""
a an the and or of to in for on with at by from is are was were be been being
this that these those it its as if then than so not no nor but do does did
have has had can could should would may might must will shall about into over
under after before during while between out up down off again very more most
other some any each few both all own same too only just also
de da do das dos e ou o a os as um uma uns umas para por com sem em no na nos
nas ao aos que se um uma como onde quando porque qual quais seu sua seus suas
ele ela eles elas isso isto aquilo mais menos muito pouco ja nao sim
""".split())

ACTION_RE = re.compile(
    r"^(how (do|can|should|would) (you|i|we)|what (should|do) (you|i|we) do|"
    r"what should be the|what (is|are) the (immediate |first |key )?(action|steps|first aid)|"
    r"how to|what is the recommended|when should you|where should you)", re.I)
PREVENT_RE = re.compile(r"\b(prevent|prevention|avoid|risks?)\b", re.I)
FACT_RE = re.compile(r"^(can|is|are|does|why|what causes|how does|what are the risks)\b", re.I)
EPISTEMIC_RE = re.compile(
    r"^(how (do|can|would) (you|i|we) (know|tell|recognize|identify|differentiate|distinguish)|"
    r"what (are|is) the (signs|symptoms|difference|risks|causes)|"
    r"why\b|can\b|is\b|are\b|does\b)", re.I)

EN_PHRASES = ("first aid", "snake bite", "running water", "high blood pressure",
              "oral rehydration", "heat stroke", "heart attack", "food poisoning")

GLOSSARY_REL = "data/offline/glossary-pt-en.json"
_GLOSSARY: list[tuple[str, list[tuple[str, float]]]] | None = None


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def stem(tok: str) -> str:
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 4 and tok.endswith("es") and not tok.endswith("ses"):
        return tok[:-2]
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokens(text: str) -> list[str]:
    return [stem(t) for t in TOKEN_RE.findall(norm(text))
            if t not in STOP and len(t) > 1]


def load_glossary() -> list[tuple[str, list[tuple[str, float]]]]:
    """Glossário PT→EN (fonte única compartilhada com o celular)."""
    global _GLOSSARY
    if _GLOSSARY is not None:
        return _GLOSSARY
    rows: list[tuple[str, list[tuple[str, float]]]] = []
    bases = [Path.cwd(), *Path(__file__).resolve().parents]
    for base in bases:
        path = base / GLOSSARY_REL
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for entry in data.get("entries", []):
            pt = entry.get("pt", "")
            ens = [(str(en), float(w)) for en, w in entry.get("en", []) if en]
            if pt and ens:
                rows.append((norm(pt), ens))
        break
    rows.sort(key=lambda r: -len(r[0]))
    _GLOSSARY = rows
    return rows


def expand(query: str) -> tuple[dict[str, float], list[str], bool]:
    """Devolve (termo->peso, frases EN, houve_match_no_glossário)."""
    nq = " " + norm(query) + " "
    weights: dict[str, float] = {}
    for t in tokens(query):
        weights[t] = max(weights.get(t, 0.0), 1.0)
    phrase_set: set[str] = set()
    gloss_hit = False
    covered: list[tuple[int, int]] = []
    for pt, ens in load_glossary():
        m = re.search(r"(?<![a-z0-9])" + re.escape(pt) + r"(?![a-z0-9])", nq)
        if not m:
            continue
        s, e = m.span()
        if any(s < e2 and s2 < e for s2, e2 in covered):
            continue
        covered.append((s, e))
        gloss_hit = True
        for en, w in ens:
            for t in tokens(en):
                weights[t] = max(weights.get(t, 0.0), w)
            if " " in en:
                phrase_set.add(en)
    phrase_set.update(p for p in EN_PHRASES if " " + p + " " in nq)
    return weights, sorted(phrase_set), gloss_hit


def snippet_text(body: str, weights: dict[str, float]) -> str:
    """Frase do corpo com mais termos da query (+ bônus de verbo de ação)."""
    body = re.sub(r"\s+", " ", body or "")
    sentences = re.split(r"(?<=[.!?])\s+", body)
    best, best_score = "", -1e9
    for s in sentences:
        ns = set(tokens(s))
        h = sum(1 for t in weights if t in ns)
        if not h:
            continue
        score = h * 2.0
        if re.search(r"\b(use|apply|give|take|run|cover|drink|avoid|call|seek|wash|"
                     r"clean|boil|keep|do not|don't|should|must|start|stop)\b", s, re.I):
            score += 1.5
        if score > best_score:
            best, best_score = s, score
    if not best:
        best = body[:240]
    best = re.sub(r"^.*?##\s*Uso\s*", "", best).strip()
    return best.strip()[:260]


def domain_terms(db_path: str | None = None) -> set[str]:
    terms: set[str] = set()
    for _pt, ens in load_glossary():
        for en, _w in ens:
            terms.update(tokens(en))
    if db_path:
        try:
            con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            try:
                for (title,) in con.execute("SELECT title FROM docs WHERE kind='curado'"):
                    terms.update(tokens(title))
            finally:
                con.close()
        except sqlite3.Error:
            pass
    return terms


def _hit(term: str, tks: set[str]) -> bool:
    return term in tks


def search(query: str, db_path: str, k: int = 5) -> list[dict]:
    """Busca FTS5 + rerank determinístico. Lista vazia = sem fonte confiável."""
    weights, phrases, gloss_hit = expand(query)
    if not weights:
        return []
    if not gloss_hit and not (set(tokens(query)) & domain_terms(db_path)):
        return []
    terms = list(weights)
    terms.extend(f'"{p}"' for p in phrases)
    fts = " OR ".join(dict.fromkeys(terms))
    sql = """SELECT title, body, source, license, kind,
                    -bm25(docs, 8.0, 1.0) * CAST(weight AS REAL) AS score
             FROM docs WHERE docs MATCH ? %s
             ORDER BY score DESC LIMIT %d"""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = con.execute(sql % ("", 120), (fts,)).fetchall()
        # garante que docs curados não sejam soterrados pelos milhares de Q/A
        rows += con.execute(sql % ("AND kind='curado'", 10), (fts,)).fetchall()
    finally:
        con.close()
    seen: set[tuple[str, str]] = set()
    out = []
    for title, body, source, lic, kind, score in rows:
        if (title, source) in seen:
            continue
        seen.add((title, source))
        text = f"{title}\n{body}"
        tks = set(tokens(text))
        hits = sum(1 for t in weights if _hit(t, tks))
        if not hits:
            continue
        cov = hits / len(weights)
        score = float(score) * (0.65 + 0.35 * cov)
        nt = " " + norm(text) + " "
        for p in phrases:
            if f" {p} " in nt:
                score += 2.5
        if kind == "firstaidqa":
            if ACTION_RE.search(title) and not EPISTEMIC_RE.search(title):
                score += 0.5 if PREVENT_RE.search(title) else 2.2
            elif FACT_RE.search(title) or EPISTEMIC_RE.search(title):
                score -= 0.8
        elif kind == "curado":
            score *= 1.15
        out.append({"score": score, "title": title, "source": source,
                    "license": lic, "kind": kind, "body": body})
    out.sort(key=lambda r: -r["score"])
    out = out[:k]
    for row in out:
        row["snippet"] = snippet_text(row.pop("body"), weights)
    return out


def corpus_path() -> str | None:
    """Caminho do corpus.db (cwd ou ancestrais do módulo), se existir."""
    for base in [Path.cwd(), *Path(__file__).resolve().parents]:
        path = base / "data/offline/corpus.db"
        if path.is_file():
            return str(path)
    return None


def count_docs(db_path: str) -> int:
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM meta WHERE key='total'").fetchone()
            return int(row[0]) if row else 0
        finally:
            con.close()
    except (sqlite3.Error, ValueError):
        return 0


KIND_LABEL = {
    "curado": "curado",
    "firstaidqa": "FirstAidQA · sintetico",
    "fm90": "FM 90-3",
    "fm4": "FM 4-25.11 · dominio publico",
    "nhs": "NHS Medicines",
    "kiwix": "Kiwix/Survival",
    "cooking": "Based.Cooking",
}

# piso de confiança do BM25 (mesmo do celular): abaixo disso, sem fonte
MIN_SCORE = 0.45
