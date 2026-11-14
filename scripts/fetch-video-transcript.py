#!/usr/bin/env python3
"""fetch-video-transcript.py — baixa a transcrição de um vídeo do YouTube, sem travar.

POR QUE (14/11, sweep-2026-11): o yt-dlp bate no 429 do endpoint de legendas
do YouTube com frequência (medido no vídeo pnZh5PAF3VE: "Unable to download
video subtitles for 'pt': HTTP Error 429"), e a casa já tinha um vídeo
transcrito (~/Books/videos/tek-IY9BRWc ✓) sem ter a ferramenta. Aqui o
caminho érobustO em DUAS etapas, porque elas batem em endpoints diferentes:

  1. METADADOS pelo yt-dlp (--skip-download --write-info-json --no-write-subs)
     → título, canal, duração, descrição, chapters e as URLs de legenda.
  2. LEGENDAS direto no endpoint timedtext, usando a URL que veio no
     metadado, com uma lista de user-agents e um retry. A URL do timedtext
     NÃO é a mesma que o yt-dlp usa no passo das legendas, e por isso ela
     passa quando o yt-dlp leva 429.

Saída (a convenção que a casa já usa em ~/Books/videos/<id>/ ✓):
  <id>.info.json      metadados do yt-dlp
  <id>.<lang>.json3   legenda crua (json3)
  <id>.<lang>.txt     transcrição em texto puro (uma linha por segmento)
  <id>.txt            a melhor transcrição disponível (a primeira lang pedida)
  <id>.DIGEST.md      só com --digest: o roteiro com os tópicos e os horários

USO
    python3 scripts/fetch-video-transcript.py https://youtu.be/pnZh5PAF3VE
    python3 scripts/fetch-video-transcript.py pnZh5PAF3VE --langs pt,en --digest
    python3 scripts/fetch-video-transcript.py <url> --out-dir ~/Books/videos --timeout 60

EXEMPLO
    $ python3 scripts/fetch-video-transcript.py https://youtu.be/pnZh5PAF3VE --langs pt,en
    metadados: pnZh5PAF3VE.info.json (1.2 MB)
    legenda en-orig: 694663 chars
    transcricao: pnZh5PAF3VE.txt (42944 chars)
    pronto: ~/Books/videos/pnZh5PAF3VE/
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

UAS = [
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def video_id(url_or_id: str) -> str:
    s = url_or_id.strip()
    if "://" in s:
        s = s.split("?")[0].rstrip("/").split("/")[-1]
    return s


def fetch_meta(vid: str, out_dir: Path, timeout: int) -> Path:
    """Metadados pelo yt-dlp (sem legendas: é o passo que toma 429)."""
    meta = out_dir / f"{vid}.info.json"
    cmd = ["yt-dlp", "--skip-download", "--write-info-json", "--no-write-subs",
           "--socket-timeout", str(timeout), "--retries", "2",
           "--extractor-args", "youtube:player_client=default",
           "-o", str(out_dir / f"{vid}.%(ext)s"),
           f"https://youtu.be/{vid}"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout * 4)
    if not meta.is_file():
        log(f"  metadados FALHARAM: {(r.stderr or r.stdout).strip().splitlines()[-1:]}")
        raise SystemExit(2)
    log(f"  metadados: {meta.name} ({meta.stat().st_size} bytes)")
    return meta


def fetch_caption(url: str, timeout: int, tries: int = 3) -> str:
    """Baixa a legenda direto no timedtext, com UA e retry (o 429 é do endpoint do yt-dlp)."""
    last = ""
    for attempt in range(tries):
        for ua in UAS:
            try:
                r = subprocess.run(
                    ["curl", "-sS", "--compressed", "-A", ua, "--max-time", str(timeout), url],
                    capture_output=True, text=True, timeout=timeout + 10)
            except subprocess.TimeoutExpired:
                last = "timeout"
                continue
            body = r.stdout or ""
            if len(body) > 200 and "<transcript" in body or (len(body) > 200 and '"events"' in body):
                return body
            last = f"{len(body)} chars"
        if attempt + 1 < tries:
            time.sleep(2 + attempt * 2)
    return ""


def json3_to_text(body: str) -> tuple[str, list[tuple[float, str]]]:
    try:
        d = json.loads(body)
    except Exception:
        return "", []
    segs: list[tuple[float, str]] = []
    for ev in d.get("events") or []:
        line = "".join(t.get("utf8", "") for t in (ev.get("segs") or [])).replace("\n", " ")
        if line.strip():
            segs.append((ev.get("tStartMs", 0) / 1000.0, line))
    return " ".join(t for _, t in segs), segs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out-dir", default=os.path.expanduser("~/Books/videos"))
    ap.add_argument("--langs", default="pt,en")
    ap.add_argument("--timeout", type=int, default=45)
    ap.add_argument("--digest", action="store_true",
                    help="escreve <id>.DIGEST.md com o roteiro e os horários")
    args = ap.parse_args()

    vid = video_id(args.url)
    out_dir = Path(args.out_dir).expanduser() / vid
    out_dir.mkdir(parents=True, exist_ok=True)
    log(f"video: {vid} -> {out_dir}")

    meta_path = fetch_meta(vid, out_dir, args.timeout)
    meta = json.loads(meta_path.read_text())
    auto = meta.get("automatic_captions") or {}
    manual = meta.get("subtitles") or {}

    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    # o "-orig" é a track original (sem tradução); tenta antes a pedida
    ordem: list[str] = []
    for lang in langs:
        for cand in (lang, f"{lang}-orig"):
            if cand not in ordem:
                ordem.append(cand)

    best_text = ""
    best_lang = ""
    for lang in ordem:
        tracks = (manual.get(lang) or []) + (auto.get(lang) or [])
        for t in tracks:
            url = t.get("url")
            if not url:
                continue
            body = fetch_caption(url, args.timeout)
            if not body:
                continue
            (out_dir / f"{vid}.{lang}.json3").write_text(body)
            text, segs = json3_to_text(body)
            if not text:
                continue
            (out_dir / f"{vid}.{lang}.txt").write_text(text)
            log(f"  legenda {lang}: {len(text)} chars")
            if not best_text:
                best_text, best_lang = text, lang
                (out_dir / f"{vid}.txt").write_text(text)
                (out_dir / f"{vid}.segs.json").write_text(
                    json.dumps([{"t": round(t, 2), "text": s} for t, s in segs],
                               ensure_ascii=False, indent=1))
            break

    if not best_text:
        log("  NENHUMA legenda obtida (429 do YouTube ou video sem legenda)")
        log(f"  o metadados ficou em {meta_path} (titulo, canal, descricao, chapters)")
        return 3

    # o meta.json no formato da casa (o yt-dlp cru tem outros campos)
    house_meta = {
        "title": meta.get("title"),
        "channel": meta.get("channel") or meta.get("uploader"),
        "uploader": meta.get("uploader"),
        "upload_date": meta.get("upload_date"),
        "duration": meta.get("duration"),
        "view_count": meta.get("view_count"),
        "description": meta.get("description"),
        "language": best_lang,
        "source": args.url,
        "chapters": meta.get("chapters") or [],
        "keywords": meta.get("keywords") or [],
    }
    (out_dir / "meta.json").write_text(json.dumps(house_meta, ensure_ascii=False, indent=1))

    if args.digest:
        segs = json.loads((out_dir / f"{vid}.segs.json").read_text())
        lines = [f"# {meta.get('title')}", "",
                 f"Canal: {house_meta['channel']} | data: {house_meta['upload_date']} | "
                 f"duracao: {house_meta['duration']}s | views: {house_meta['view_count']}",
                 f"Transcricao: `{vid}.{best_lang}.txt` ({len(best_text)} chars)", "",
                 "## Roteiro por horario", ""]
        step = 300
        for i in range(0, len(segs), 5):
            chunk = segs[i:i + 5]
            t = chunk[0]["t"]
            lines.append(f"**{int(t // 60):02d}:{int(t % 60):02d}** "
                         + " ".join(c["text"] for c in chunk))
        (out_dir / f"{vid}.DIGEST.md").write_text("\n\n".join(lines))
        log(f"  digest: {vid}.DIGEST.md")

    log(f"  pronto: {out_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
