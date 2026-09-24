#!/usr/bin/env bash
# overnight-harness-24-09.sh — fila determinística da madrugada (complementa
# o overnight.py do Muse: L9/kb/DPO já cobertos lá; aqui: OCR pendências da
# perícia + relatório de disco + reindex RAG).
#
# ARQUITETURA (insight do dono 24/09): loop de LLM morre por DILUIÇÃO de
# contexto — por isso ESTE driver é bash/python determinístico, sem LLM
# contínuo; cada tarefa = processo fresco; estado = arquivos; veredito =
# MORNING-REPORT-2.md quando acordar. Parada: lista acabou (ou pkill -f
# overnight-harness).
set -u
R=/tmp/overnight
mkdir -p "$R"
LOG="$R/harness.log"
exec > >(tee -a "$LOG") 2>&1
echo "=== overnight-harness start: $(date)"

# ── T1: OCR 300dpi das pendências da perícia ──────────────────────────
cat > /tmp/overnight/ocr_task.py <<'PY'
import fitz, pytesseract, re, io, sys
from PIL import Image, ImageOps
p, tag = sys.argv[1], sys.argv[2]
doc = fitz.open(p)
full = []
for i, pg in enumerate(doc):
    txt = pg.get_text().strip()
    if not txt:
        pix = pg.get_pixmap(dpi=300)
        im = Image.open(io.BytesIO(pix.tobytes("png")))
        if "espelhado" in tag:
            im = ImageOps.mirror(im)
        txt = pytesseract.image_to_string(im, lang="eng")
    full.append(f"--pag{i+1}-- " + re.sub(r"\s+", " ", txt)[:600])
out = "\n".join(full)
open(f"/tmp/overnight/ocr-{tag}.txt", "w").write(out)
print(tag, "ok", len(out))
PY
for par in "Receitas Médica/Receita Amarela A2.pdf amarela-A2" \
           "Receitas Médica/Receita Azul B1.pdf azul-B1" \
           ; do
  set -- $par
  nix-shell -p tesseract --run "PYTHONPATH=/home/nixos/.local/jarvis-mcp-site /etc/profiles/per-user/nixos/bin/python3 /tmp/overnight/ocr_task.py '/home/nixos/Pessoal/Drive/Documentos/$1' $2" 2>&1 | tail -1
done
for par in "laudos-exames/2024-08-02-SEM-TEXTO-verificar.pdf semtexto-104" \
           "laudos-exames/2024-08-02-SEM-TEXTO-verificar-b.pdf semtexto-105" \
           "laudos-exames/2023-09-25-SCAN-ESPELHADO-reprocessar.pdf espelhado" \
           ; do
  set -- $par
  nix-shell -p tesseract --run "PYTHONPATH=/home/nixos/.local/jarvis-mcp-site /etc/profiles/per-user/nixos/bin/python3 /tmp/overnight/ocr_task.py '/home/nixos/Pessoal/INSS/$1' $2" 2>&1 | tail -1
done

# ── T2: relatório de disco (grandes blocos p/ limpeza — SÓ relatório) ──
{ echo "== top 15 dirs em ~/projects (du 1-nível):"
  du -h --max-depth=1 /home/nixos/projects 2>/dev/null | sort -rh | head -15
  echo "== trash/caches grandes:"
  du -sh /home/nixos/.cache /home/nixos/Trash /home/nixos/.local/share/Trash /nix/var/log 2>/dev/null
} > "$R/disk-report.txt" 2>&1
echo "disk-report escrito"

# ── T3: reindex RAG do que a noite produziu (OCR txts entram no INSS/) ──
cp "$R"/ocr-*.txt /home/nixos/Pessoal/INSS/laudos-exames/ 2>/dev/null
nix develop --command env JARVIS_EXTRA_READ_ROOTS=/home/nixos/Pessoal \
  python3 -c "from jarvis.core.rag import HybridIndexer; print('reindex:', HybridIndexer().index_directory('/home/nixos/Pessoal/INSS'))" 2>/dev/null | tail -1

# ── T4: MORNING REPORT ────────────────────────────────────────────────
{
  echo "# Morning Report 2 — overnight-harness (24→25/09)"
  echo
  echo "## OCR pendências perícia (resultados crus em laudos-exames/ocr-*.txt)"
  for f in "$R"/ocr-*.txt; do
    echo "### $(basename $f)"; echo '```'; head -c 800 "$f" 2>/dev/null; echo '```'
  done
  echo "## Disco (ver disk-report.txt completo)"
  head -20 "$R/disk-report.txt"
  echo
  echo "## Estado dos fixes do harness"
  echo "- tilde/approve-all/hard-never: commit 57a1e5b (HEAD) ✓"
  echo "- ROTEIRO-PERÍCIO.md v1: em ~/Pessoal/INSS/ (revisar c/ [PREENCHER])"
  echo "- overnight.py do Muse: ver MORNING-REPORT.md (irmão deste)"
} > "$R/MORNING-REPORT-2.md"
echo "=== DONE: $R/MORNING-REPORT-2.md ($(date))"
