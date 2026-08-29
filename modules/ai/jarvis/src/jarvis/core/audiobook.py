"""Audiobook Reader — leitura de livros com TTS local (Kokoro).

Porta do audiobook.rive do legado (Manjaro): scan de diretório → leitura
de .epub/.txt → chunking por parágrafos → Kokoro TTS → WAV sequencial.

Progresso é salvo em `~/.local/state/jarvis/audiobook.json` (bookmark por
livro: arquivo + chunk index). Persistente entre sessões — declarativo,
não depende de banco de dados.

Fluxo:
  scan  → lista livros em ~/Books/ (ou diretório configurável)
  read  → inicia leitura de um livro (chunking + TTS)
  pause → pausa a leitura (salva bookmark)
  resume→ retoma do último bookmark
  stop  → para e reseta bookmark
  next  → pula para próximo chunk
  prev  → volta para chunk anterior
  status→ mostra estado atual (livro, chunk, progresso)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

BOOKS_DIR_DEFAULT = os.environ.get("JARVIS_BOOKS_DIR", os.path.expanduser("~/Books"))
CHUNK_TARGET_CHARS = 800  # ~200 tokens — cabe no ctx do Kokoro sem truncar
STATE_DIR_ENV = "JARVIS_STATE_DIR"


def _state_dir() -> Path:
    base = os.environ.get(STATE_DIR_ENV, "")
    if base:
        p = Path(base)
    else:
        p = Path.home() / ".local" / "state" / "jarvis"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _bookmark_path() -> Path:
    return _state_dir() / "audiobook.json"


# ---------------------------------------------------------------------------
# Extração de texto
# ---------------------------------------------------------------------------

def _extract_txt(path: Path) -> str:
    """Lê um arquivo .txt (UTF-8 com fallback)."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _extract_epub(path: Path) -> str:
    """Extrai texto de um .epub (tenta ebooklib; fallback: unzip simples)."""
    try:
        import ebooklib  # type: ignore[import-not-found]
        from ebooklib import epub
        from bs4 import BeautifulSoup  # type: ignore[import-not-found]

        book = epub.read_epub(str(path))
        parts: list[str] = []
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_DOCUMENT:
                soup = BeautifulSoup(item.get_content(), "html.parser")
                parts.append(soup.get_text(separator="\n"))
        return "\n\n".join(parts)
    except ImportError:
        # Fallback: extrai .html/.xhtml do zip
        import zipfile

        parts: list[str] = []
        with zipfile.ZipFile(path) as zf:
            for name in zf.namelist():
                if name.endswith((".html", ".xhtml", ".htm")):
                    try:
                        raw = zf.read(name).decode("utf-8", errors="replace")
                        # Remove tags HTML
                        clean = re.sub(r"<[^>]+>", " ", raw)
                        clean = re.sub(r"\s+", " ", clean).strip()
                        if len(clean) > 50:
                            parts.append(clean)
                    except Exception:  # noqa: BLE001
                        continue
        return "\n\n".join(parts)


def _extract_pdf(path: Path) -> str:
    """Extrai texto de um .pdf usando PyMuPDF (fitz).
    
    Fallback: se o PDF for baseado em imagens (texto vazio),
    renderiza páginas como imagens e usa OCR via pytesseract.
    Preprocessing inspirado no guia-renamer (grayscale + sharpen + contrast).
    """
    try:
        import fitz  # PyMuPDF — type: ignore[import-not-found]

        doc = fitz.open(str(path))
        parts: list[str] = []
        ocr_fallback_needed = False
        
        for page in doc:
            text = page.get_text()
            if text.strip():
                parts.append(text.strip())
            else:
                ocr_fallback_needed = True
        doc.close()
        
        # If we got text from some pages, return it
        if parts and not ocr_fallback_needed:
            return "\n\n".join(parts)
        
        # OCR fallback for image-based PDFs
        if ocr_fallback_needed:
            ocr_text = _ocr_pdf(path)
            if ocr_text:
                # Merge: use extracted text where available, OCR where not
                if parts:
                    return "\n\n".join(parts) + "\n\n" + ocr_text
                return ocr_text
        
        return "\n\n".join(parts) if parts else ""
    except ImportError:
        return ""
    except Exception:  # noqa: BLE001
        return ""


def _ocr_pdf(path: Path) -> str:
    """OCR fallback for image-based PDFs using PyMuPDF + pytesseract.
    
    Renders each page as an image at 300 DPI, preprocesses (grayscale,
    sharpen, contrast), and runs pytesseract OCR.
    Inspired by guia-renamer/core/ocr_extractor.py.
    """
    try:
        import fitz  # PyMuPDF
        from PIL import Image, ImageOps, ImageEnhance, ImageFilter
        import pytesseract
        import io
    except ImportError:
        return ""
    
    try:
        doc = fitz.open(str(path))
        parts: list[str] = []
        render_dpi = 300
        zoom = render_dpi / 72  # PyMuPDF default is 72 DPI
        mat = fitz.Matrix(zoom, zoom)
        
        for page_num in range(min(len(doc), 50)):  # limit to 50 pages
            page = doc[page_num]
            # Render page as image
            pix = page.get_pixmap(matrix=mat)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            
            # Preprocessing (from guia-renamer)
            img_gray = img.convert("L")
            img_gray = img_gray.filter(ImageFilter.SHARPEN)
            img_gray = ImageEnhance.Contrast(img_gray).enhance(2.0)
            img_gray = ImageOps.autocontrast(img_gray)
            
            # OCR with multiple PSM modes for better coverage
            text_parts = []
            for config in ["--psm 3", "--psm 6", "--psm 11"]:
                try:
                    t = pytesseract.image_to_string(
                        img_gray, config=f"{config} -l eng+por"
                    )
                    if t.strip():
                        text_parts.append(t.strip())
                except Exception:  # noqa: BLE001
                    continue
            
            if text_parts:
                # Deduplicate: take the longest result
                best = max(text_parts, key=len)
                parts.append(best)
        
        doc.close()
        return "\n\n".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def extract_text(path: Path | str) -> str:
    """Extrai texto de um livro (.epub, .txt, .pdf)."""
    path = Path(path)
    if not path.exists():
        return ""
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return _extract_epub(path)
    elif suffix == ".txt":
        return _extract_txt(path)
    elif suffix == ".pdf":
        return _extract_pdf(path)
    return ""


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(text: str, target_chars: int = CHUNK_TARGET_CHARS) -> list[str]:
    """Divide texto em chunks por parágrafos, ressentindo limiar de tokens.

    Cada chunk tem no máximo `target_chars` caracteres. Parágrafos são
    respeitados (quebra em branco). Se um parágrafo é maior que o limite,
    é quebrado por frases.
    """
    # Normaliza quebras de linha duplas em separadores de parágrafo
    paragraphs = re.split(r"\n\s*\n", text)
    chunks: list[str] = []
    current = ""

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(current) + len(para) + 2 <= target_chars:
            current = (current + "\n\n" + para).strip() if current else para
        else:
            if current:
                chunks.append(current)
            # Parágrafo maior que o limite → quebra por frases
            if len(para) > target_chars:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                current = ""
                for sent in sentences:
                    if len(current) + len(sent) + 1 <= target_chars:
                        current = (current + " " + sent).strip() if current else sent
                    else:
                        if current:
                            chunks.append(current)
                        current = sent
            else:
                current = para

    if current.strip():
        chunks.append(current.strip())

    return chunks


# ---------------------------------------------------------------------------
# SFX (Sound Effects) — portado do enhanced_audiobook.py legado
# ---------------------------------------------------------------------------

SOUNDS_DIR = Path(os.environ.get(
    "JARVIS_SOUNDS_DIR",
    str(Path.home() / ".local" / "share" / "jarvis" / "sounds"),
))

# Mapa de palavras-chave → arquivos de som
SFX_MAP: dict[str, str] = {
    # Weather
    "rain": "weather/rain.ogg", "thunder": "weather/thunder.ogg",
    "wind": "weather/wind.ogg", "storm": "weather/storm.ogg",
    # Nature
    "birds": "nature/birds.ogg", "waves": "nature/ocean.ogg",
    "ocean": "nature/ocean.ogg", "fire": "nature/fire.ogg",
    "forest": "nature/forest.ogg",
    # Actions
    "door": "actions/door_close.ogg", "knock": "actions/knock.ogg",
    "footsteps": "actions/footsteps.ogg", "explosion": "actions/explosion.ogg",
    "glass_break": "actions/glass_break.ogg", "scream": "actions/scream.ogg",
    "carriage": "city/crowd.ogg", "church_bell": "city/crowd.ogg",
    "clock": "mechanical/clock_ticking.ogg", "crowd": "city/crowd.ogg",
    "ritual": "nature/fire.ogg", "magic": "weather/wind.ogg",
    "metal_clink": "actions/metal_cling.ogg", "metal_clank": "actions/metal_clang.ogg",
    "sword": "actions/metal_cling.ogg", "blade": "actions/metal_clang.ogg",
}


def detect_sfx(text: str) -> list[tuple[str, str]]:
    """Detecta palavras-chave de SFX no texto.
    
    Retorna lista de (keyword, sound_file) encontrados.
    """
    text_lower = text.lower()
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    
    for keyword, sound_file in SFX_MAP.items():
        if keyword in text_lower and keyword not in seen:
            seen.add(keyword)
            found.append((keyword, sound_file))
    
    return found


def play_sfx(sound_file: str, volume: float = 0.6) -> bool:
    """Toca um arquivo de som via mpv (background)."""
    full_path = SOUNDS_DIR / sound_file
    if not full_path.exists():
        return False
    try:
        subprocess.Popen(
            ["mpv", "--no-video", "--volume", str(int(volume * 100)),
             "--really-quiet", str(full_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except (FileNotFoundError, OSError):
        return False


def play_sfx_for_text(text: str, volume: float = 0.4) -> list[str]:
    """Detecta e toca SFX relevantes para o texto dado."""
    effects = detect_sfx(text)
    played: list[str] = []
    for keyword, sound_file in effects:
        if play_sfx(sound_file, volume=volume):
            played.append(keyword)
    return played


def install_sfx(sounds_dir: Path | str | None = None) -> str:
    """Copia arquivos SFX do legado para o diretório atual.
    
    Procura em:
    1. /run/media/nixos/YUMI/BACKUPS/MANJARO_EXTRACTED/.../sounds/
    2. ~/.jarvis/sounds/ (legado direto)
    
    Retorna mensagem de resultado.
    """
    target = Path(sounds_dir) if sounds_dir else SOUNDS_DIR
    
    # Sources to try
    legacy_sources = [
        Path.home() / ".jarvis" / "sounds",
        Path("/run/media/nixos/YUMI/BACKUPS/MANJARO_EXTRACTED/manjaro_extracted/.jarvis/sounds"),
    ]
    
    src_dir = None
    for src in legacy_sources:
        if src.exists() and any(src.iterdir()):
            src_dir = src
            break
    
    if not src_dir:
        return "Nenhum diretório SFX legado encontrado"
    
    # Copy
    import shutil
    target.mkdir(parents=True, exist_ok=True)
    copied = 0
    
    for item in src_dir.rglob("*"):
        if item.is_file():
            rel = item.relative_to(src_dir)
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(item, dest)
                copied += 1
    
    return f"Copiados {copied} arquivos de {src_dir} para {target}"


# ---------------------------------------------------------------------------
# Bookmark (progresso)
# ---------------------------------------------------------------------------

@dataclass
class BookmarkState:
    book: str = ""
    book_path: str = ""
    chunk_index: int = 0
    total_chunks: int = 0
    playing: bool = False
    paused: bool = False


def _load_bookmark() -> BookmarkState:
    path = _bookmark_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BookmarkState(**data)
        except (OSError, ValueError, TypeError):
            pass
    return BookmarkState()


def _save_bookmark(state: BookmarkState) -> None:
    path = _bookmark_path()
    try:
        path.write_text(json.dumps({
            "book": state.book,
            "book_path": state.book_path,
            "chunk_index": state.chunk_index,
            "total_chunks": state.total_chunks,
            "playing": state.playing,
            "paused": state.paused,
        }, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# TTS — Kokoro (delega para voice.py)
# ---------------------------------------------------------------------------

def _tts_chunk(text: str) -> str | None:
    """Sintetiza um chunk com Kokoro. Retorna path do WAV ou None."""
    try:
        from jarvis.core.voice import speak
        result = speak(text, play=False)
        if result.startswith("ERROR"):
            return None
        return result
    except Exception:  # noqa: BLE001
        return None


def _play_wav(path: str) -> None:
    """Toca um WAV sequencialmente."""
    for cmd in (
        ["canberra-gtk-play", "--file", path],
        ["paplay", path],
        ["aplay", "-q", path],
    ):
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            return
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def scan_books(books_dir: str | Path | None = None) -> list[dict[str, Any]]:
    """Escaneia o diretório de livros e retorna lista de {name, path, ext, size}."""
    directory = Path(books_dir or BOOKS_DIR_DEFAULT)
    if not directory.exists():
        return []
    books: list[dict[str, Any]] = []
    for f in sorted(directory.iterdir()):
        if f.is_file() and f.suffix.lower() in (".epub", ".txt", ".pdf"):
            books.append({
                "name": f.stem,
                "path": str(f),
                "ext": f.suffix.lower(),
                "size_kb": round(f.stat().st_size / 1024, 1),
            })
    return books


def _find_book(name: str, books_dir: str | Path | None = None) -> Path | None:
    """Busca um livro por nome (parcial, case-insensitive)."""
    books = scan_books(books_dir)
    low_name = name.lower().strip()
    # Match exato primeiro
    for b in books:
        if b["name"].lower() == low_name:
            return Path(b["path"])
    # Match parcial
    for b in books:
        if low_name in b["name"].lower():
            return Path(b["path"])
    return None


# ---------------------------------------------------------------------------
# Comandos do Audiobook
# ---------------------------------------------------------------------------

def cmd_scan(books_dir: str | Path | None = None) -> str:
    """Lista livros disponíveis."""
    books = scan_books(books_dir)
    if not books:
        return "Nenhum livro encontrado em ~/Books/ (.epub, .txt)"
    lines = [f"📚 {len(books)} livro(s) encontrado(s):"]
    for b in books:
        lines.append(f"  · {b['name']} ({b['ext']}, {b['size_kb']}KB)")
    return "\n".join(lines)


def cmd_list(books_dir: str | Path | None = None) -> str:
    """Lista livros (alias de scan)."""
    return cmd_scan(books_dir)


def cmd_read(book_name: str, books_dir: str | Path | None = None) -> str:
    """Inicia a leitura de um livro — extrai, chunka, e retorna o primeiro chunk."""
    book_path = _find_book(book_name, books_dir)
    if book_path is None:
        return f"Livro '{book_name}' não encontrado em ~/Books/"

    text = extract_text(book_path)
    if not text.strip():
        return f"Não consegui extrair texto de '{book_path.name}'"

    chunks = chunk_text(text)
    if not chunks:
        return f"Texto vazio em '{book_path.name}'"

    state = BookmarkState(
        book=book_path.stem,
        book_path=str(book_path),
        chunk_index=0,
        total_chunks=len(chunks),
        playing=True,
        paused=False,
    )
    _save_bookmark(state)

    chunk = chunks[0]
    wav = _tts_chunk(chunk)
    if wav:
        _play_wav(wav)

    progress = f"[1/{len(chunks)}]"
    preview = chunk[:200] + ("..." if len(chunk) > 200 else "")
    return f"📖 Lendo '{book_path.stem}' {progress}\n\n{preview}"


def cmd_pause() -> str:
    """Pausa a leitura (salva bookmark)."""
    state = _load_bookmark()
    if not state.book:
        return "Nenhum livro em leitura."
    state.playing = False
    state.paused = True
    _save_bookmark(state)
    return f"⏸️ Leitura pausada: '{state.book}' (chunk {state.chunk_index + 1}/{state.total_chunks})"


def cmd_resume() -> str:
    """Retoma a leitura do último bookmark."""
    state = _load_bookmark()
    if not state.book:
        return "Nenhum livro pausado para retomar."
    if not state.paused and state.playing:
        return f"Já estou lendo '{state.book}' (chunk {state.chunk_index + 1}/{state.total_chunks})"

    book_path = Path(state.book_path)
    if not book_path.exists():
        return f"Arquivo '{state.book_path}' não encontrado."

    text = extract_text(book_path)
    chunks = chunk_text(text)
    if not chunks:
        return "Texto vazio no livro."

    state.total_chunks = len(chunks)
    state.playing = True
    state.paused = False
    _save_bookmark(state)

    idx = min(state.chunk_index, len(chunks) - 1)
    chunk = chunks[idx]
    wav = _tts_chunk(chunk)
    if wav:
        _play_wav(wav)

    progress = f"[{idx + 1}/{len(chunks)}]"
    preview = chunk[:200] + ("..." if len(chunk) > 200 else "")
    return f"▶️ Retomando '{state.book}' {progress}\n\n{preview}"


def cmd_stop() -> str:
    """Para a leitura e reseta bookmark."""
    state = _load_bookmark()
    name = state.book or "desconhecido"
    _save_bookmark(BookmarkState())  # reseta
    return f"⏹️ Leitura de '{name}' encerrada."


def cmd_next() -> str:
    """Avança para o próximo chunk."""
    state = _load_bookmark()
    if not state.book:
        return "Nenhum livro em leitura."

    book_path = Path(state.book_path)
    if not book_path.exists():
        return f"Arquivo '{state.book_path}' não encontrado."

    text = extract_text(book_path)
    chunks = chunk_text(text)
    state.total_chunks = len(chunks)

    if state.chunk_index + 1 >= len(chunks):
        _save_bookmark(state)
        return f"🏁 Fim de '{state.book}' ({len(chunks)} chunks). Para reler: leia o livro {state.book}"

    state.chunk_index += 1
    state.playing = True
    state.paused = False
    _save_bookmark(state)

    chunk = chunks[state.chunk_index]
    wav = _tts_chunk(chunk)
    if wav:
        _play_wav(wav)

    progress = f"[{state.chunk_index + 1}/{len(chunks)}]"
    preview = chunk[:200] + ("..." if len(chunk) > 200 else "")
    return f"⏭️ {state.book} {progress}\n\n{preview}"


def cmd_prev() -> str:
    """Volta para o chunk anterior."""
    state = _load_bookmark()
    if not state.book:
        return "Nenhum livro em leitura."

    if state.chunk_index <= 0:
        return f" Já estou no início de '{state.book}'."

    book_path = Path(state.book_path)
    text = extract_text(book_path)
    chunks = chunk_text(text)
    state.total_chunks = len(chunks)

    state.chunk_index -= 1
    state.playing = True
    state.paused = False
    _save_bookmark(state)

    chunk = chunks[state.chunk_index]
    wav = _tts_chunk(chunk)
    if wav:
        _play_wav(wav)

    progress = f"[{state.chunk_index + 1}/{len(chunks)}]"
    preview = chunk[:200] + ("..." if len(chunk) > 200 else "")
    return f"⏮️ {state.book} {progress}\n\n{preview}"


def cmd_status() -> str:
    """Mostra o estado atual da leitura."""
    state = _load_bookmark()
    if not state.book:
        return "📚 Nenhum livro em leitura."
    status = "🔊 Lendo" if state.playing else ("⏸️ Pausado" if state.paused else "⏹️ Parado")
    progress = f"{state.chunk_index + 1}/{state.total_chunks}" if state.total_chunks else "?"
    pct = f" ({state.chunk_index * 100 // state.total_chunks}%)" if state.total_chunks else ""
    return f"{status}: '{state.book}' — chunk {progress}{pct}"


# ---------------------------------------------------------------------------
# Dispatch (usado pelo router/macro)
# ---------------------------------------------------------------------------

def dispatch(args: list[str]) -> str:
    """Dispatch do macro audiobook: <call>audiobook action [args]</call>."""
    if not args:
        return cmd_status()
    action = args[0].lower()
    rest = args[1:]

    if action == "scan":
        return cmd_scan()
    elif action == "list":
        return cmd_list()
    elif action == "read":
        name = " ".join(rest) if rest else ""
        if not name:
            state = _load_bookmark()
            if state.book:
                return cmd_resume()
            return "Qual livro? Ex: leia o livro hobbit"
        return cmd_read(name)
    elif action == "stop":
        return cmd_stop()
    elif action == "pause":
        return cmd_pause()
    elif action == "resume":
        return cmd_resume()
    elif action == "next":
        return cmd_next()
    elif action == "prev":
        return cmd_prev()
    elif action == "status":
        return cmd_status()
    else:
        return f"Ação desconhecida: {action}. Opções: scan, list, read, stop, pause, resume, next, prev, status"
