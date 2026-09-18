"""Pre-RAG sanitization layer (core/doc_sanitize.py) + wiring no index_file.

Unitários puros (mocks onde há serviço); integração com HybridIndexer
mockado (store+LLM); negativos e adversariais com arquivos reais.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _mod():
    import jarvis.core.doc_sanitize as D
    return D


# ---------------------------------------------------------------------------
# detect_format
# ---------------------------------------------------------------------------

def test_detect_by_extension(tmp_path):
    D = _mod()
    f = tmp_path / "a.md"
    f.write_text("# t")
    assert _mod().detect_format(f)[0] == ".md"


def test_detect_pdf_by_magic_despite_extension(tmp_path):
    D = _mod()
    f = tmp_path / "fake.txt"
    f.write_bytes(b"%PDF-1.4 fake")
    fmt, method = D.detect_format(f)
    assert fmt == ".pdf" and method == "magic"


def test_detect_epub_by_zip_manifest(tmp_path):
    D = _mod()
    import zipfile
    f = tmp_path / "b.bin"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("META-INF/container.xml", "<x/>")
        zf.writestr("c.xhtml", "<p>oi</p>")
    assert D.detect_format(f)[0] == ".epub"


def test_detect_plain_zip_is_unsupported_family(tmp_path):
    D = _mod()
    import zipfile
    f = tmp_path / "c.zip"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("a.txt", "x")
    assert D.detect_format(f)[0] == ".zip"


# ---------------------------------------------------------------------------
# normalize / validate
# ---------------------------------------------------------------------------

def test_normalize_preserves_md_code():
    D = _mod()
    raw = "# T\n\n```python\nx  =  1\n```\n\n\np  com  espaços"
    out, notes = D.normalize_text(raw, ".md")
    assert out == "# T\n\n```python\nx  =  1\n```\n\np com espaços"
    assert "md-code-preservado" in notes


def test_dedupe_repeated_blocks():
    D = _mod()
    raw = "A\n\nB\n\nB\n\nB\n\nB\n\nC"
    out, removed = D._dedupe_repeated_blocks(raw)
    assert removed == 2  # 3ª e 4ª ocorrências caem, 2 ficam
    assert out.count("B") == 2


def test_validate_empty_valid_vs_failed():
    D = _mod()
    f, w = D.validate_normalized("", ".md", 10)
    assert not f and "fonte-vazia-valida" in w
    f, _ = D.validate_normalized("", ".md", 5000)
    assert f  # extração falhou, não é vazio válido


def test_validate_catastrophic_loss():
    D = _mod()
    f, _ = D.validate_normalized("x" * 10, ".pdf", 5000)
    assert any("perda-catastrofica" in x or "output-curto" in x for x in f)


def test_validate_code_fence_warning_not_fail():
    D = _mod()
    f, w = D.validate_normalized("# t\n\n```python\nx=1\n" + "y" * 100, ".md", 200)
    assert not f
    assert "code-fence-desbalanceado" in w


def test_link_terms_closed_world():
    D = _mod()
    out, n = D.link_terms("falo de kernel e nix", None)
    assert n == 0 and "[[" not in out  # sem glossário: zero links
    out, n = D.link_terms("falo de kernel e nix", {"kernel": "linux", "nix": "nixos"})
    assert n >= 2 and "[[linux|kernel]]" in out


# ---------------------------------------------------------------------------
# sanitize_document
# ---------------------------------------------------------------------------

def test_sanitize_md_ok_and_manifest(tmp_path, monkeypatch):
    D = _mod()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    f = tmp_path / "doc.md"
    f.write_text("# Título\n\nTexto real aqui.\n")
    doc = D.sanitize_document(f)
    assert doc.status == "ok" and "Título" in doc.text
    assert doc.provenance["format"] == ".md"
    assert len(doc.provenance["source_sha256"]) == 64
    man = list((tmp_path / "state" / "sanitize").glob("manifests.jsonl"))
    assert man and "sanitizer_version" in man[0].read_text()


def test_sanitize_html_drops_noise(tmp_path, monkeypatch):
    D = _mod()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    f = tmp_path / "p.html"
    f.write_text(
        "<html><head><title>T</title></head><body>"
        "<nav>menu menu</nav>"
        "<script>alert(1)</script>"
        "<div class='cookie-consent'>aceite cookies</div>"
        "<article><h1>Conteúdo real aqui mesmo</h1><p>Parágrafo útil aqui.</p></article>"
        "<footer>rodapé</footer></body></html>")
    doc = D.sanitize_document(f)
    assert doc.status == "ok"
    assert "Conteúdo real" in doc.text and "Parágrafo útil" in doc.text
    assert "aceite cookies" not in doc.text
    assert "alert(1)" not in doc.text
    assert "menu menu" not in doc.text


def test_sanitize_unsupported_zip_quarantined(tmp_path, monkeypatch):
    D = _mod()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    import zipfile
    f = tmp_path / "a.zip"
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("x.txt", "y" * 200)
    doc = D.sanitize_document(f)
    assert doc.status == "quarantine" and doc.reason == "UNSUPPORTED_FORMAT"
    q = list((tmp_path / "state" / "sanitize" / "quarantine").glob("*.json"))
    assert q and "UNSUPPORTED_FORMAT" in q[0].read_text()


def test_sanitize_epub_minimal_zip(tmp_path, monkeypatch):
    D = _mod()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    import zipfile
    f = tmp_path / "b.epub"
    body = ("<?xml version='1.0'?><html xmlns='http://www.w3.org/1999/xhtml'>"
            "<head><title>T</title></head><body><h1>Cap Um</h1><p>"
            + "texto do livro aqui. " * 20 + "</p></body></html>")
    opf = ("<?xml version='1.0'?><package xmlns='http://www.idpf.org/2007/opf' "
           "version='3.0'><metadata xmlns:dc='http://purl.org/dc/elements/1.1/'>"
           "<dc:title>T</dc:title></metadata><manifest>"
           "<item id='c' href='c.xhtml' media-type='application/xhtml+xml'/>"
           "</manifest><spine><itemref idref='c'/></spine></package>")
    container = ("<?xml version='1.0'?><container xmlns='urn:oasis:names:tc:opendocument:xmlns:container' "
                 "version='1.0'><rootfiles><rootfile full-path='OEBPS/c.opf' "
                 "media-type='application/oebps-package+xml'/></rootfiles></container>")
    with zipfile.ZipFile(f, "w") as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OEBPS/c.opf", opf)
        zf.writestr("OEBPS/c.xhtml", body)
    doc = D.sanitize_document(f)
    assert doc.status == "ok" and "Cap Um" in doc.text


def test_sanitize_pdf_text_layer(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    D = _mod()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    f = tmp_path / "p.pdf"
    doc_ = fitz.open()
    page = doc_.new_page()
    page.insert_text((72, 72), "Relatório trimestral de testes reais aqui.")
    doc_.save(f)
    doc_.close()
    doc = D.sanitize_document(f)
    assert doc.status == "ok" and "trimestral" in doc.text


def test_sanitize_pdf_scanned_quarantined(tmp_path, monkeypatch):
    """PDF sem text layer + sem OCR (pytesseract ausente) → quarentena,
    nunca lixo vazio no índice."""
    fitz = pytest.importorskip("fitz")
    D = _mod()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    f = tmp_path / "scan.pdf"
    doc_ = fitz.open()
    for _ in range(3):
        doc_.new_page()  # páginas em branco = sem texto
    doc_.save(f)
    doc_.close()
    assert f.stat().st_size >= 50
    doc = D.sanitize_document(f)
    assert doc.status == "quarantine"
    assert doc.reason in ("EXTRACTION_FAILURE", "QUALITY_FAILURE")


def test_sanitize_path_traversal_blocked(tmp_path, monkeypatch):
    D = _mod()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    doc = D.sanitize_document("/etc/passwd")
    assert doc.status == "quarantine" and doc.reason == "PATH_ERROR"


def test_sanitize_missing_file(tmp_path, monkeypatch):
    D = _mod()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    doc = D.sanitize_document(tmp_path / "nope.md")
    assert doc.status == "quarantine"


def test_sanitize_idempotent(tmp_path, monkeypatch):
    D = _mod()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    f = tmp_path / "d.md"
    f.write_text("# a\n\nb\n")
    d1 = D.sanitize_document(f, write_manifest=False)
    d2 = D.sanitize_document(f, write_manifest=False)
    assert d1.text == d2.text
    assert (d1.provenance["source_sha256"]
            == d2.provenance["source_sha256"])


# ---------------------------------------------------------------------------
# wiring: HybridIndexer.index_file
# ---------------------------------------------------------------------------

class _FakeStore:
    def __init__(self):
        self.points = []

    def ensure_collection(self, name, dim=None):
        pass

    def upsert(self, name, points):
        self.points.extend(points)


class _FakeLLM:
    def embed(self, text):
        return [0.1, 0.2, 0.3]


def _indexer(monkeypatch):
    monkeypatch.setattr("jarvis.core.rag.QdrantStore", lambda cfg: _FakeStore())
    monkeypatch.setattr("jarvis.core.rag.LLMClient", lambda cfg: _FakeLLM())
    from jarvis.core.rag import HybridIndexer
    from jarvis.core.config import Config
    idx = HybridIndexer(Config())
    idx._store = _FakeStore()
    idx._llm = _FakeLLM()
    return idx


def test_index_file_sanitizes_html(tmp_path, monkeypatch):
    idx = _indexer(monkeypatch)
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    f = tmp_path / "p.html"
    f.write_text("<html><body><nav>menu</nav><p>Guia real de instalação aqui.</p></body></html>")
    payload = idx.index_file(str(f), force=True)
    assert payload is not None
    stored = " ".join(p["payload"]["content"] for p in idx._store.points)
    assert "Guia real" in stored and "menu" not in stored


def test_index_file_quarantines_garbage_pdf(tmp_path, monkeypatch):
    """PDF scanned → quarentena → NADA no Qdrant (fronteira §16)."""
    fitz = pytest.importorskip("fitz")
    idx = _indexer(monkeypatch)
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    f = tmp_path / "scan.pdf"
    doc_ = fitz.open()
    for _ in range(3):
        doc_.new_page()
    doc_.save(f)
    doc_.close()
    assert f.stat().st_size >= 50
    assert idx.index_file(str(f), force=True) is None
    assert idx._store.points == []
    qdir = tmp_path / "state" / "sanitize" / "quarantine"
    assert list(qdir.glob("*.json"))


def test_index_directory_mixed_quarantine(tmp_path, monkeypatch):
    """Diretório misto: bom indexa, ruim quarentena (harness-level)."""
    idx = _indexer(monkeypatch)
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    (tmp_path / "bom.md").write_text("# Bom\n\nConteúdo bom de verdade aqui.\n")
    import zipfile
    with zipfile.ZipFile(tmp_path / "ruim.zip", "w") as zf:
        zf.writestr("x", "y" * 200)
    n = idx.index_directory(tmp_path)
    assert n == 1
    assert any("Bom" in p["payload"]["content"] for p in idx._store.points)


# ---------------------------------------------------------------------------
# doc_sources (aquisição offline seletiva, sem rede)
# ---------------------------------------------------------------------------

def test_acquisition_spec_validation():
    from jarvis.core.doc_sources import AcquisitionSpec
    good = AcquisitionSpec(name="x", url="https://ex.com/a.zim",
                           sha256="a" * 64, dest_subdir="wikipedia")
    assert good.validate() == []
    bad = AcquisitionSpec(name="", url="http://inseguro/x",
                          sha256="zzz", max_bytes=10**13, dest_subdir="y")
    errs = bad.validate()
    assert len(errs) == 5  # nome, url, sha, cap, subdir


def test_acquisition_dest_no_traversal(tmp_path, monkeypatch):
    from jarvis.core.doc_sources import AcquisitionSpec
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    s = AcquisitionSpec(name="x", url="https://ex.com/../../evil.zim")
    d = s.dest_path()
    assert d.name == "evil.zim" and ".." not in str(d)
    assert "sources" in d.parts


def test_verify_local_file_sha(tmp_path):
    from jarvis.core.doc_sources import verify_local_file
    f = tmp_path / "a.bin"
    f.write_bytes(b"abc")
    import hashlib
    sha = hashlib.sha256(b"abc").hexdigest()
    assert verify_local_file(f, expected_sha256=sha)["match"] is True
    assert verify_local_file(f, expected_sha256="0" * 64)["ok"] is False
    assert verify_local_file(tmp_path / "nope")["ok"] is False


def test_discover_nixos_docs_no_network():
    from jarvis.core.doc_sources import discover_nixos_docs
    d = discover_nixos_docs()
    assert d["ok"] is True
    assert "nixos_option" in d and "man_dirs" in d and "store_manuals" in d


def test_storage_layout_created(tmp_path, monkeypatch):
    from jarvis.core.doc_sources import _state_base
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    base = _state_base()
    for sub in ("wikipedia", "python", "nixos"):
        assert (base / "sanitize" / "sources" / sub).is_dir()
