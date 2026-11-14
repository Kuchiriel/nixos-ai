#!/usr/bin/env python3
"""watch-updates.py — avisa a casa quando algo novo aparece nas fontes que importam.

POR QUE (14/11, sweep-2026-11): o pedido do dono foi monitorar as fontes
das coisas que a casa usa (YouTube, RSS, Hacker News, Reddit) e avisar
quando sai novidade relevante. O video que ele mandou (The Next New Thing,
13/11, "top GitHub repos") mostrou o formato: um canal que每周 mostra o
que apareceu na semana. Aqui e o mesmo formato, so que filtrado pelo que
a casa usa de verdade.

O QUE ELE FAZ
  1. le um catálogo de fontes (JSON): canal do YouTube, feed RSS, busca do
     Hacker News, releases do GitHub;
  2. baixa o que é novo desde a última volta (cursor em arquivo de estado);
  3. filtra por palavra-chave (o que interessa a casa) e descarta o que é
     só anúncio;
  4. publica no bus da casa (kind=msg) o que é realmente novo, e grava o
     cursor para não repetir.

POR QUE O BUS E O CANAL: ele é cross-machine, auditável e quem chega
depois lê o histórico (o dono mandou postar no issue do bus). A entrega
local (acordar o agente) é outra coisa: aqui o aviso é para a casa, não
para um agente específico.

USO
    python3 scripts/watch-updates.py --dry-run
    python3 scripts/watch-updates.py --post-bus
    python3 scripts/watch-updates.py --catalog meu.json --dry-run

FORMATO DO CATALOGO (JSON)
    [
      {"kind": "youtube", "id": "UC...-id", "name": "The Next New Thing",
       "keywords": ["nixos", "llama", "opencode", "mcp"]},
      {"kind": "rss", "url": "https://...", "name": "blog",
       "keywords": ["nixos"]},
      {"kind": "hn", "query": "nixos OR llama.cpp", "name": "Hacker News"},
      {"kind": "github", "repo": "anthropics/skills", "name": "Anthropic skills"}
    ]

EXEMPLO
    $ python3 scripts/watch-updates.py --dry-run
    [youtube] The Next New Thing: 1 novo (filtrado: 1)
      - "Open source Grok Bot, copy any YouTube video" (13/11)
    nada novo no bus (dry-run)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = Path(os.environ.get("JARVIS_UPDATE_STATE",
                             Path.home() / ".local/state/jarvis/updates-state.json"))
CATALOG_DEFAULT = Path(__file__).resolve().parent / "watch-updates-sources.json"
UA = "Mozilla/5.0 (X11; Linux x86_64) jarvis-watch-updates/1.0"


def log(m: str) -> None:
    print(m, flush=True)


def fetch(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def strip_tags(html: str) -> str:
    html = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", html, flags=re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", html).strip()


def parse_feed(xml: str) -> list[dict]:
    """RSS/Atom: titulo, link, data."""
    out = []
    for item in re.findall(r"<(?:item|entry)\b.*?</(?:item|entry)>", xml, re.S | re.I):
        t = re.search(r"<title[^>]*>(.*?)</title>", item, re.S | re.I)
        l = re.search(r"<link[^>]*>(.*?)</link>", item, re.S | re.I)
        if not l:
            l = re.search(r'<link[^>]*href="([^"]+)"', item, re.I)
        d = re.search(r"<(?:pubDate|updated|published)[^>]*>(.*?)</", item, re.S | re.I)
        out.append({"title": strip_tags(t.group(1)) if t else "",
                    "link": strip_tags(l.group(1)) if l else "",
                    "date": strip_tags(d.group(1)) if d else ""})
    return out


def youtube_channel(cid: str) -> list[dict]:
    xml = fetch(f"https://www.youtube.com/feeds/videos.xml?channel_id={urllib.parse.quote(cid)}")
    return parse_feed(xml)


def hn_search(query: str) -> list[dict]:
    url = ("https://hn.algolia.com/api/v1/search_by_date?query=" +
           urllib.parse.quote(query) + "&tags=story&hitsPerPage=20")
    d = json.loads(fetch(url))
    return [{"title": h.get("title") or "", "link": h.get("url") or
             f"https://news.ycombinator.com/item?id={h.get('objectID')}",
             "date": h.get("created_at") or "",
             "points": h.get("points") or 0} for h in d.get("hits", [])]


def github_releases(repo: str) -> list[dict]:
    d = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases?per_page=10"))
    return [{"title": f"{repo}: {r.get('tag_name')} — {r.get('name') or ''}".strip(),
             "link": r.get("html_url") or "", "date": r.get("published_at") or ""}
            for r in d if r.get("published_at")]


def collect(src: dict) -> list[dict]:
    kind = src.get("kind")
    try:
        if kind == "youtube":
            return youtube_channel(src["id"])
        if kind == "rss":
            return parse_feed(fetch(src["url"]))
        if kind == "hn":
            return hn_search(src.get("query", ""))
        if kind == "github":
            return github_releases(src["repo"])
    except Exception as exc:  # noqa: BLE001
        log(f"  [falhou] {src.get('name')}: {exc}")
    return []


def interesting(item: dict, keys: list[str]) -> bool:
    if not keys:
        return True
    blob = f"{item.get('title', '')} {item.get('link', '')}".lower()
    return any(k.lower() in blob for k in keys)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", default=str(CATALOG_DEFAULT))
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--post-bus", action="store_true",
                    help="publica no bus (padrao: so mostra)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    args.dry_run = args.dry_run or not args.post_bus

    cat_path = Path(args.catalog)
    if not cat_path.is_file():
        log(f"catalogo nao encontrado: {cat_path}")
        return 1
    sources = json.loads(cat_path.read_text())

    state_path = Path(args.state)
    state = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text())
        except Exception:
            state = {}

    novos: list[tuple[dict, dict]] = []
    for src in sources:
        items = collect(src)
        key = src.get("id") or src.get("url") or src.get("repo") or src.get("query")
        seen = set(state.get(key, []))
        fresh = [i for i in items if i.get("link") not in seen]
        picked = [i for i in fresh if interesting(i, src.get("keywords") or [])]
        log(f"[{src.get('kind')}] {src.get('name')}: {len(fresh)} novo(s), "
            f"{len(picked)} relevante(s)")
        for i in picked[:5]:
            log(f"   - {i.get('title', '')[:100]}")
        novos.extend((src, i) for i in picked[:5])
        # o cursor guarda TUDO que ja vi (filtrado ou nao), para nao repetir
        state[key] = list(seen | {i.get("link") for i in items if i.get("link")})[-400:]

    if not novos:
        log("nada novo")
    elif args.post_bus:
        sys.path.insert(0, str(ROOT / "modules/ai/jarvis/src"))
        try:
            from jarvis.core.coord import post
            for src, item in novos:
                note = (f"{src.get('name')}: {item.get('title', '')}\n"
                        f"{item.get('link', '')}\n"
                        f"(monitor de novidades da casa; filtro: "
                        f"{', '.join(src.get('keywords') or []) or 'sem filtro'})")
                out = post(kind="msg", agent=os.environ.get("JARVIS_AGENT_NAME", "jarvis-watch-updates"),
                           lane="nixos-ai/watch-updates", to="", note=note,
                           intent="novidade nas fontes que a casa usa")
                log(f"  bus: {out}")
        except Exception as exc:  # noqa: BLE001
            log(f"  falha ao postar no bus: {exc}")
            return 2
    else:
        log("dry-run: nada publicado no bus")

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    log(f"estado: {state_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
