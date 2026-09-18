"""Pre-RAG Document Sanitization Layer.

Insertion point: `HybridIndexer.index_file` (core/rag.py) — todo conteúdo
passa por `sanitize_document` ANTES do chunking/upsert. Sem sanitização,
PDF/EPUB/HTML iam crus (ou como lixo binário) para o Qdrant.

Pipeline (determinístico, sem LLM no caminho crítico):
    detect (ext + magic bytes) → extract → normalize → validate
    → OK (texto + provenance) | QUARANTINE (reason + manifest, sem indexar)

Reuso (nada duplicado):
  - extração epub/txt/pdf: `audiobook.extract_text` (lazy import; top-level
    do audiobook é só-stdlib, sem ciclo com rag).
  - jail de paths: `devtools._safe_path` (leitura).
  - state: `JARVIS_STATE_DIR` (mesma convenção do audiobook).

Capability matrix (ambiente real NixOS, sem pip global):
  .md/.txt/code/json/yaml : leitura direta (UTF-8, errors=replace)
  .html/.htm              : strip stdlib html.parser (nav/footer/script/
                            style/aside + divs cookie/consent/newsletter)
  .epub                   : audiobook (ebooklib+bs4, fallback zip stdlib)
  .pdf texto              : audiobook (PyMuPDF; libs presentes no env)
  .pdf scanned            : QUARANTINE (pytesseract ausente → OCR
                            indisponível; não alimenta lixo)
  outros/binários         : QUARANTINE (UNSUPPORTED_FORMAT)

Wikilinks (§6 da missão): NENHUM gerado — o repo não tem store de
terminologia (TERM EXISTS falha fechado). `link_terms` é hook
determinístico: só linka com glossário explícito fornecido.

Storage (convenção repo: STATE_DIR, sem data/ novo):
  $STATE/sanitize/manifests.jsonl   (toda sanitização, ok + quarentena)
  $STATE/sanitize/quarantine/<sha>.json (só quarentena: reason+provenance,
    SEM corpo — lixo não é preservado; raw nunca é movido/copiado)
  $STATE/sanitize/sources/{wikipedia,python,nixos}/ (aquisição seletiva)
Stages intermediários (raw/extracted/normalized) NÃO são persistidos:
pipeline streaming; reprodutibilidade via manifest (source sha + versões).
Desvio documentado da §13: evita duplicar GBs de livros; hashes +
versões dão a mesma garantia de idempotência (§15).
"""

from __future__ import annotations

import hashlib
import html as _html_mod
import json
import os
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any


SANITIZER_VERSION = "1.0.0"
NORMALIZER_VERSION = "1.0.0"

# Status possíveis (§18: taxonomia própria de docs; o classify_error do
# completion cobre o loop do agente, não documentos).
REASON_OK = "OK"
REASON_UNSUPPORTED = "UNSUPPORTED_FORMAT"
REASON_EXTRACTION = "EXTRACTION_FAILURE"
REASON_VALIDATION = "VALIDATION_FAILURE"
REASON_QUALITY = "QUALITY_FAILURE"
REASON_PATH = "PATH_ERROR"
REASON_TOO_LARGE = "FILE_TOO_LARGE"

# Gates explícitos e configuráveis (§10 — sem número mágico escondido).
MAX_INPUT_BYTES = 8 * 1024 * 1024   # acima → QUARANTINE (rag itera até 2MB; docs até 8MB)
MIN_OUTPUT_CHARS = 50               # abaixo, com input maior → FAIL (perda catastrófica)
MIN_OUTPUT_RATIO = 0.05             # output/input < 5% com input >1k → FAIL
MAX_PAGES_PDF = 200                 # teto anti-DoS (audiobook usa 50 p/ OCR; aqui texto)
STATE_DIR_ENV = "JARVIS_STATE_DIR"

# Formatos com extração suportada (ext → método).
SUPPORTED = {
    ".md", ".markdown", ".txt", ".html", ".htm", ".epub", ".pdf",
    ".json", ".jsonc", ".json5", ".yaml", ".yml", ".toml", ".ini",
    ".xml", ".csv",
}

# Boilerplate determinístico (HTML): tags descartadas + classes/ids.
_DROP_TAGS = frozenset({"nav", "footer", "aside", "script", "style",
                        "noscript", "template", "form"})
_BOILER_RE = re.compile(
    r"cookie|consent|newsletter|popup|modal|banner|subscribe|advert|"
    r"breadcrumb|sidebar|widget|toolbar|paywall", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    """Strip HTML stdlib: texto corrido, sem executar nada.

    Pilha por tag: conteúdo de nav/footer/script/style/aside e de tags
    com classe/id de boilerplate (cookie/consent/...) é descartado;
    o resto passa. Comentários nunca entram.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._stack: list[bool] = []  # True = descartar este nível

    def _dropped(self) -> bool:
        return any(self._stack)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        drop = tag in _DROP_TAGS
        if not drop:
            for _, val in attrs:
                if val and _BOILER_RE.search(val):
                    drop = True
                    break
        self._stack.append(drop)
        if not self._dropped() and tag in (
                "p", "br", "div", "section", "article", "li",
                "h1", "h2", "h3", "h4", "h5", "h6", "tr", "pre", "title"):
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if not self._dropped():
            self._parts.append(data)

    def handle_comment(self, data: str) -> None:
        return  # comentários nunca entram

    def text(self) -> str:
        return "".join(self._parts)


def _state_base(state_dir: str | Path | None = None) -> Path:
    base = os.environ.get(STATE_DIR_ENV, "")
    p = Path(state_dir or base) if (state_dir or base) else (
        Path.home() / ".local" / "state" / "jarvis")
    (p / "sanitize" / "quarantine").mkdir(parents=True, exist_ok=True)
    (p / "sanitize" / "sources" / "wikipedia").mkdir(parents=True, exist_ok=True)
    (p / "sanitize" / "sources" / "python").mkdir(parents=True, exist_ok=True)
    (p / "sanitize" / "sources" / "nixos").mkdir(parents=True, exist_ok=True)
    return p


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def detect_format(path: str | Path) -> tuple[str, str]:
    """(formato, método). Magic bytes precedem extensão duvidosa."""
    p = Path(path)
    ext = p.suffix.lower()
    try:
        with open(p, "rb") as f:
            magic = f.read(16)
    except OSError:
        return ext or "?", "missing"
    if magic.startswith(b"%PDF"):
        return ".pdf", "magic"
    if magic.startswith(b"PK\x03\x04"):
        # zip: epub ou outro — checa manifest pelo nome interno sem extrair
        import zipfile
        try:
            with zipfile.ZipFile(p) as zf:
                names = zf.namelist()
                if any("META-INF/container.xml" in n or n.endswith(".opf")
                       for n in names):
                    return ".epub", "magic"
                return ".zip", "magic"
        except Exception:
            return ext or ".zip", "magic-fallback"
    if magic.lstrip()[:5].lower() == b"<html" or magic.lstrip()[:14].lower() == b"<!doctype html":
        return ".html", "magic"
    return ext or "?", "extension"


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _strip_html(raw: str) -> tuple[str, list[str]]:
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        pass
    return parser.text(), ["html-strip-stdlib"]


def extract(path: str | Path) -> tuple[str, str, list[str], bool]:
    """Extrai texto bruto. Retorna (texto, método, avisos, ocr_usado).

    Reusa audiobook.extract_text p/ epub/txt/pdf (ebooklib/bs4/fitz com
    fallbacks; OCR retorna "" sem pytesseract — tratado como ausência).
    """
    p = Path(path)
    fmt, _ = detect_format(p)
    notes: list[str] = []
    if fmt in (".md", ".markdown", ".txt", ".json", ".jsonc", ".json5",
               ".yaml", ".yml", ".toml", ".ini", ".xml", ".csv"):
        return _read_text_file(p), "direct-read", notes, False
    if fmt in (".html", ".htm"):
        text, notes = _strip_html(_read_text_file(p))
        return text, "html-strip-stdlib", notes, False
    if fmt in (".epub", ".pdf", ".txt"):
        try:
            from jarvis.core.audiobook import extract_text as _ab_extract
        except Exception as e:
            return "", "audiobook-unavailable", [f"import: {e}"], False
        try:
            text = _ab_extract(p)
        except Exception as e:
            return "", "audiobook-error", [f"{type(e).__name__}: {e}"], False
        if fmt == ".pdf" and not text.strip():
            notes.append("pdf-sem-text-layer-ocr-indisponivel")
        return text, "audiobook", notes, False
    return "", "unsupported", [f"formato {fmt} sem extrator"], False


def _dedupe_repeated_blocks(text: str) -> tuple[str, int]:
    """Colapsa blocos de parágrafos repetidos em sequência (>2x → 1x).

    Preserva 2 ocorrências (ex.: refrão intencional); remove a partir da 3ª.
    Retorna (texto, blocos_removidos).
    """
    paras = text.split("\n\n")
    out: list[str] = []
    removed = 0
    run_key: str | None = None
    run_len = 0
    for para in paras:
        key = para.strip()
        if key and key == run_key:
            run_len += 1
            if run_len >= 3:
                removed += 1
                continue
        else:
            run_key = key if key else None
            run_len = 1
        out.append(para)
    return "\n\n".join(out), removed


def normalize_text(text: str, fmt: str) -> tuple[str, list[str]]:
    """Normalização determinística p/ RAG. Preserva estrutura (md)."""
    notes: list[str] = []
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    # colapsa 3+ quebras em 2 (parágrafo); espaços múltiplos em 1 (fora code)
    if fmt in (".md", ".markdown"):
        parts = t.split("```")
        for i in range(0, len(parts), 2):
            parts[i] = re.sub(r"[ \t]+", " ", parts[i])
            parts[i] = re.sub(r"\n{3,}", "\n\n", parts[i])
        t = "```".join(parts)
        notes.append("md-code-preservado")
    else:
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
    t, n = _dedupe_repeated_blocks(t)
    if n:
        notes.append(f"blocos-repetidos-colapsados:{n}")
    # linhas vazias puras no início/fim
    t = t.strip("\n")
    return t, notes


def validate_normalized(text: str, fmt: str, input_chars: int) -> tuple[list[str], list[str]]:
    """Validação code-owned. Retorna (failures, warnings).

    FAIL bloqueia indexação (quarentena). WARNING registra e indexa.
    """
    failures: list[str] = []
    warnings: list[str] = []
    stripped = text.strip()
    # vazio válido vs extração falha (§9)
    if not stripped:
        if input_chars < MIN_OUTPUT_CHARS:
            warnings.append("fonte-vazia-valida")
        else:
            failures.append(f"output-vazio-com-input-{input_chars}")
        return failures, warnings
    if len(stripped) < MIN_OUTPUT_CHARS and input_chars >= MIN_OUTPUT_CHARS:
        failures.append(f"output-curto-{len(stripped)}-de-{input_chars}")
    if input_chars > 1000 and len(stripped) / max(1, input_chars) < MIN_OUTPUT_RATIO:
        failures.append(
            f"perda-catastrofica-ratio-{len(stripped) / max(1, input_chars):.3f}")
    try:
        stripped.encode("utf-8")
    except UnicodeError:
        failures.append("utf8-invalido")
    # estrutura md: fences balanceados, tabelas com separador
    if fmt in (".md", ".markdown"):
        if stripped.count("```") % 2:
            warnings.append("code-fence-desbalanceado")
        pipe_lines = [l for l in stripped.splitlines()
                      if l.count("|") >= 2]
        if pipe_lines and not any(re.match(r"^\s*\|?[\s:|-]+\|?\s*$", l)
                                  for l in stripped.splitlines()):
            warnings.append("tabela-sem-separador")
    return failures, warnings


def link_terms(text: str, glossary: dict[str, str] | None = None) -> tuple[str, int]:
    """Hook determinístico de Wikilinks (§6).

    Sem glossário → ZERO links (repositório não tem store de terminologia;
    desconhecido permanece desconhecido). Com glossário explícito
    {termo: destino}, linka ocorrências exatas `[[destino|termo]]`.
    Nunca inventa: só o que está no mapa.
    """
    if not glossary:
        return text, 0
    n = 0
    for term in sorted(glossary, key=len, reverse=True):
        if term in text:
            text = text.replace(term, f"[[{glossary[term]}|{term}]]")
            n += text.count(term)  # contagem aproximada pós-replace
    return text, n


@dataclass
class SanitizedDoc:
    """Resultado canônico da sanitização."""
    status: str  # "ok" | "quarantine"
    reason: str = REASON_OK
    text: str = ""
    provenance: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    manifest_path: str = ""


def _write_manifest(state: Path, record: dict[str, Any], quarantine: bool) -> str:
    line = json.dumps(record, ensure_ascii=False, default=str)
    manifests = state / "sanitize" / "manifests.jsonl"
    with open(manifests, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    if quarantine:
        qp = state / "sanitize" / "quarantine" / f"{record['source_sha256'][:16]}.json"
        with open(qp, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in record.items() if k != "warnings"},
                      f, ensure_ascii=False, indent=1)
        return str(qp)
    return ""


def sanitize_text(raw: str, *, fmt: str = ".md", min_chars: int | None = None) -> SanitizedDoc:
    """Sanitiza conteúdo de memória (mesma normalização/validação do pipeline de disco).

    Barreira para caminhos que NÃO vêm de arquivo: index_file(content=...),
    extract_text do audiobook, MCP content strings. Mesmo normalize+validate,
    mesmo contrato de quarentena. Proveniência marca origem 'in-memory'.
    """
    if not isinstance(raw, str):
        return SanitizedDoc(status="quarantine", reason=REASON_UNSUPPORTED,
                            failures=["conteúdo não é string"])
    if len(raw) > MAX_INPUT_BYTES:  # mesmo teto do caminho de disco
        return SanitizedDoc(status="quarantine",
                            reason=REASON_TOO_LARGE,
                            failures=[f"{len(raw)} chars > {MAX_INPUT_BYTES}"])
    text, notes = normalize_text(raw, fmt)
    floor = MIN_OUTPUT_CHARS if min_chars is None else min_chars
    failures, warnings = validate_normalized(text, fmt, len(raw) or 1)
    # origem in-memory: sem fonte em disco, piso absoluto de 1 char não-vazio
    # (o piso proporcional do validate_normalized assume extração de arquivo)
    if not text.strip():
        failures = failures + ["in-memory: conteúdo vazio"]
    elif floor > 0 and len(text.strip()) < floor:
        failures = failures + [f"in-memory: {len(text.strip())} chars < piso {floor}"]
    return SanitizedDoc(status="ok" if not failures else "quarantine",
                        reason=REASON_OK if not failures else REASON_QUALITY,
                        text=text,
                        warnings=warnings + notes,
                        failures=failures,
                        provenance={"source": "in-memory", "fmt": fmt,
                                    "extractor": "direct-read",
                                    "sanitizer_version": SANITIZER_VERSION})


def sanitize_document(path: str | Path, *, state_dir: str | Path | None = None,
                      write_manifest: bool = True,
                      glossary: dict[str, str] | None = None) -> SanitizedDoc:
    """Pipeline completo: detect → extract → normalize → validate.

    Nunca move/copia o raw. Quarentena = registro, não bloqueio de leitura.
    Idempotente: mesmo source + mesmas versões → mesmo resultado.
    """
    from jarvis.core.devtools import _safe_path
    state = _state_base(state_dir)
    try:
        target = _safe_path(str(path))
    except ValueError as e:
        return SanitizedDoc(status="quarantine", reason=REASON_PATH,
                            failures=[str(e)],
                            provenance={"source": str(path)})
    if not target.is_file():
        return SanitizedDoc(status="quarantine", reason=REASON_PATH,
                            failures=[f"não é arquivo: {target}"],
                            provenance={"source": str(target)})
    try:
        size = target.stat().st_size
        mtime = target.stat().st_mtime
    except OSError as e:
        return SanitizedDoc(status="quarantine", reason=REASON_PATH,
                            failures=[str(e)],
                            provenance={"source": str(target)})
    if size > MAX_INPUT_BYTES:
        doc = SanitizedDoc(status="quarantine", reason=REASON_TOO_LARGE,
                           failures=[f"{size} bytes > {MAX_INPUT_BYTES}"],
                           provenance=_prov(target, size, mtime, "?", "skipped"))
        if write_manifest:
            doc.manifest_path = _manifest(state, doc, target, size, mtime)
        return doc
    fmt, method = detect_format(target)
    prov_extra: dict[str, Any] = {"detect_method": method}
    if fmt not in SUPPORTED:
        doc = SanitizedDoc(status="quarantine", reason=REASON_UNSUPPORTED,
                           failures=[f"formato {fmt} sem extrator"],
                           provenance=_prov(target, size, mtime, fmt, "none", prov_extra))
        if write_manifest:
            doc.manifest_path = _manifest(state, doc, target, size, mtime)
        return doc
    raw, extractor, notes, ocr = extract(target)
    prov_extra.update({"extractor_detail": notes})
    if not raw.strip():
        # vazio válido (arquivo minúsculo) vs extração falha
        if size < MIN_OUTPUT_CHARS:
            doc = SanitizedDoc(status="ok", reason=REASON_OK, text="",
                               warnings=["fonte-vazia-valida"],
                               provenance=_prov(target, size, mtime, fmt, extractor, prov_extra))
        else:
            doc = SanitizedDoc(status="quarantine", reason=REASON_EXTRACTION,
                               failures=["extração retornou vazio p/ "
                                         f"{size} bytes"] + notes,
                               provenance=_prov(target, size, mtime, fmt, extractor, prov_extra))
        if write_manifest:
            doc.manifest_path = _manifest(state, doc, target, size, mtime)
        return doc
    text, norm_notes = normalize_text(raw, fmt)
    failures, warnings = validate_normalized(text, fmt, len(raw))
    text, nlinks = link_terms(text, glossary)
    if nlinks:
        warnings.append(f"wikilinks:{nlinks}")
    prov_extra.update({"normalizer_notes": norm_notes, "ocr_used": ocr})
    if failures:
        doc = SanitizedDoc(status="quarantine", reason=REASON_QUALITY,
                           failures=failures, warnings=warnings + notes,
                           provenance=_prov(target, size, mtime, fmt, extractor, prov_extra))
    else:
        doc = SanitizedDoc(status="ok", reason=REASON_OK, text=text,
                           warnings=warnings + notes,
                           provenance=_prov(target, size, mtime, fmt, extractor, prov_extra))
    if write_manifest:
        doc.manifest_path = _manifest(state, doc, target, size, mtime)
    return doc


def _prov(target: Path, size: int, mtime: float, fmt: str, extractor: str,
          extra: dict[str, Any] | None = None) -> dict[str, Any]:
    prov: dict[str, Any] = {
        "source": str(target),
        "source_sha256": _sha256_file(target),
        "source_bytes": size,
        "source_mtime": mtime,
        "format": fmt,
        "extractor": extractor,
        "sanitizer_version": SANITIZER_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
    }
    if extra:
        prov.update(extra)
    return prov


def _manifest(state: Path, doc: SanitizedDoc, target: Path,
              size: int, mtime: float) -> str:
    record = {
        "source": str(target),
        "source_sha256": doc.provenance.get("source_sha256", ""),
        "source_bytes": size,
        "source_mtime": mtime,
        "format": doc.provenance.get("format", "?"),
        "extractor": doc.provenance.get("extractor", "?"),
        "ocr_used": doc.provenance.get("ocr_used", False),
        "sanitizer_version": SANITIZER_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "status": doc.status,
        "reason": doc.reason,
        "warnings": doc.warnings,
        "failures": doc.failures,
        "output_sha256": hashlib.sha256(
            doc.text.encode("utf-8")).hexdigest() if doc.text else "",
        "output_chars": len(doc.text),
    }
    return _write_manifest(state, record, doc.status == "quarantine")
