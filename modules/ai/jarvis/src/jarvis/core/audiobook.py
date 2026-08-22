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


def extract_text(path: Path) -> str:
    """Extrai texto de um livro (.epub ou .txt)."""
    suffix = path.suffix.lower()
    if suffix == ".epub":
        return _extract_epub(path)
    elif suffix == ".txt":
        return _extract_txt(path)
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
        if f.is_file() and f.suffix.lower() in (".epub", ".txt"):
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
