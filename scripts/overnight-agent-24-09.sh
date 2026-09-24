#!/usr/bin/env bash
# overnight-agent-24-09.sh — SEU overnight (não o do Muse): harvest Codacus
# (transcripts → ~/Books/codacus → RAG) + digest p/ RTX 4050 6GB + varredura
# OCR do resto do Drive → MORNING-REPORT-AGENT.md. Pacing pesado anti-429.
set -u
R=/tmp/overnight; BOOKS=/home/nixos/Books/codacus
mkdir -p "$R" "$BOOKS"
exec > >(tee -a "$R/agent.log") 2>&1
echo "=== overnight-agent start: $(date)"

# ── A1: lista videos do canal Codacus ────────────────────────────────
nix-shell -p yt-dlp --run "yt-dlp --flat-playlist -j --sleep-requests 4 \
  'https://www.youtube.com/channel/UCsRvxZErBo0ByyWUX_aVuvg/videos' \
  > $R/codacus-videos.jsonl" 2>&1 | tail -1
N=$(wc -l < "$R/codacus-videos.jsonl")
echo "videos encontrados: $N"

# ── A2: transcripts com pacing/retry ─────────────────────────────────
cat > "$R/fetch_one.py" <<'PY'
import json, re, subprocess, sys, time, os
from pathlib import Path
R = Path("/tmp/overnight"); BOOKS = Path("/home/nixos/Books/codacus")
vid = json.loads(sys.argv[1])
vid_id, title = vid.get("id"), (vid.get("title") or "sem-titulo")[:80]
slug = re.sub(r"[^a-zA-Z0-9]+", "-", title.lower()).strip("-")[:60]
out = BOOKS / f"{vid_id}-{slug}.txt"
if out.exists() and out.stat().st_size > 500:
    print(f"skip (já tem): {title[:50]}"); raise SystemExit
for tent in range(2):
    r = subprocess.run(["nix-shell", "-p", "yt-dlp", "--run",
        f"yt-dlp --write-auto-sub --skip-download --sub-langs 'en-orig,en,pt-BR' "
        f"--sleep-requests 5 --retries 2 -o '/tmp/ytag/%(id)s' "
        f"'https://www.youtube.com/watch?v={vid_id}'"],
        capture_output=True, text=True, timeout=300)
    vtt = None
    for cand in Path("/tmp/ytag").glob(f"{vid_id}*.vtt"):
        vtt = cand
    if vtt:
        raw = vtt.read_text(errors="ignore")
        txt = re.sub(r"<[^>]+>", "", raw)
        lines, prev = [], None
        for l in txt.splitlines():
            l = l.strip()
            if not l or "-->" in l or l.startswith(("WEBVTT","Kind:","Language:")):
                continue
            if l != prev: lines.append(l)
            prev = l
        body = f"TITLE: {title}\nURL: https://www.youtube.com/watch?v={vid_id}\n\n" + " ".join(lines)
        out.write_text(body)
        for old in Path("/tmp/ytag").glob(f"{vid_id}*"): old.unlink()
        print(f"OK: {title[:50]} ({len(body)} chars)")
        raise SystemExit
    wait = 20 * (tent + 1)
    print(f"retry {tent} em {wait}s: {title[:40]} ({r.stderr[-80:] if r.stderr else '?'})")
    time.sleep(wait)
print(f"FALHOU: {title[:50]}")
PY
mkdir -p /tmp/ytag
i=0
while IFS= read -r line; do
  i=$((i+1))
  python3 "$R/fetch_one.py" "$line" 2>/dev/null | tail -1
  sleep $((10 + RANDOM % 15))
done < "$R/codacus-videos.jsonl"
echo "harvest finalizado: $(ls "$BOOKS" | wc -l) transcripts em ~/Books/codacus"

# ── A3: DIGEST p/ teu hardware (linhas que importam) ─────────────────
{ echo "# Codacus Digest — p/ RTX 4050 6GB (lido dos transcripts)"
  echo
  for f in "$BOOKS"/*.txt; do
    t=$(head -1 "$f" | sed 's/TITLE: //')
    hits=$(grep -icE "1060|6 ?gig|6GB|VRAM|Qwen|llama\.cpp|token.?s|offload|MoE|i-?GPU|laptop" "$f" 2>/dev/null || echo 0)
    [ "${hits:-0}" -ge 2 ] || continue
    echo "## $t"
    grep -inE "1060|6 ?gig|6GB|VRAM|Qwen|llama\.cpp|token.?s|offload|MoE" "$f" 2>/dev/null \
      | head -6 | cut -c1-220
    echo
  done
} > "$R/CODECACUS-DIGEST.md" 2>/dev/null
echo "digest: $(grep -c '^## ' "$R/CODECACUS-DIGEST.md" 2>/dev/null || echo 0) vídeos relevantes"

# ── B: varredura OCR do resto do Drive (médico primeiro) ──────────────
cat > "$R/scan_one.py" <<'PY'
import fitz, pytesseract, re, io, sys
from PIL import Image
p = sys.argv[1]
try:
    doc = fitz.open(p)
except Exception as e:
    print("ERRO", str(e)[:60]); raise SystemExit
full = []
for pg in doc[:3]:
    t = pg.get_text().strip()
    if not t:
        pix = pg.get_pixmap(dpi=200)
        t = pytesseract.image_to_string(Image.open(io.BytesIO(pix.tobytes("png"))), lang="eng")
    full.append(re.sub(r"\s+", " ", t)[:500])
print(" || ".join(full)[:900])
PY
for f in "/home/nixos/Pessoal/Drive/Imagens/IMG-20260605-WA0006.jpg" \
         "/home/nixos/Pessoal/Drive/Imagens/IMG_20260626_135737323.jpg" \
         "/home/nixos/Pessoal/Drive/Imagens/IMG_20260626_135728001_BURST001.jpg"; do
  echo "--- $f"
  nix-shell -p tesseract --run "PYTHONPATH=/home/nixos/.local/jarvis-mcp-site /etc/profiles/per-user/nixos/bin/python3 -c \"
import fitz, pytesseract, re
from PIL import Image
im = Image.open('$f')
im.thumbnail((1600,1600))
import io
import pytesseract
print(pytesseract.image_to_string(im, lang='eng')[:400])\"" 2>&1 | grep -v deprecated | tail -2
done
{ echo "== Carro:"; ls "/home/nixos/Pessoal/Drive/Carro" 2>/dev/null | head -10
  echo "== Certificados:"; ls "/home/nixos/Pessoal/Drive/Certificados" 2>/dev/null | head -10
  echo "== Documentos de Outros (NÃO OCR — são de terceiros):"
  find "/home/nixos/Pessoal/Drive/Documentos de Outros" -type f 2>/dev/null | head -15
} > "$R/drive-resto.txt"

# ── C: MORNING REPORT ─────────────────────────────────────────────────
{
  echo "# Morning Report — AGENT (24→25/09)"
  echo "## Codacus: $(ls "$BOOKS" | wc -l) transcripts → ~/Books/codacus (RAG)"
  echo "## Digest: $R/CODECACUS-DIGEST.md (tópicos p/ 4050 6GB)"
  echo "## Azul B1 confirmada (titular: você). Amarela A2 vazia. 104/105 em branco."
  echo "## Scan espelhado = solicitação bloqueio C2C7/T1T12 (em tratamentos/)"
  echo "## Resto do Drive: $R/drive-resto.txt"
} > "$R/MORNING-REPORT-AGENT.md"
echo "=== DONE agent: $(date) — $R/MORNING-REPORT-AGENT.md"
