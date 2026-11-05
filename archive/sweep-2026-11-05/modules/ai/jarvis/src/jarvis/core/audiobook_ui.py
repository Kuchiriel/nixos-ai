"""Audiobook Reader UI — rofi menu, waybar status, feedback integration.

Provides:
- Rofi menu for audiobook control (scan, list, play, pause, stop)
- Waybar status when audiobook is playing
- Event Bus events for audiobook state changes
- feedback.py integration for notifications

Usage from rofi:
    jarvis audiobook              # opens rofi menu
    jarvis audiobook --scan       # scan books directory
    jarvis audiobook --play LOTM  # play specific book
    jarvis audiobook --status     # show current status

Waybar integration:
    Add to waybar config:
    "custom/audiobook": {
        "exec": "jarvis audiobook --waybar",
        "interval": 5,
        "format": "{}"
    }
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _notify(title: str, body: str) -> None:
    """Send notification via feedback.py."""
    try:
        from jarvis.core.feedback import notify
        notify(title, body)
    except Exception:  # noqa: BLE001
        pass


def _emit_event(topic: str, **data: object) -> None:
    """Emit audiobook event via Event Bus."""
    try:
        from jarvis.core.eventbus import get_bus
        get_bus().publish(f"audiobook.{topic}", data)
    except Exception:  # noqa: BLE001
        pass


def scan_and_notify(books_dir: str | None = None) -> str:
    """Scan books directory and notify user."""
    from jarvis.core.audiobook import scan_books

    books = scan_books(books_dir)
    if not books:
        _notify("📚 Audiobook", "Nenhum livro encontrado")
        return "Nenhum livro encontrado"

    names = [b["name"] for b in books[:10]]
    msg = f"{len(books)} livros encontrados: {', '.join(names)}"
    _notify("📚 Audiobook", msg)
    _emit_event("scanned", count=len(books), books=names)
    return msg


def play_book(book_name: str, books_dir: str | None = None) -> str:
    """Start playing a book."""
    from jarvis.core.audiobook import cmd_read

    result = cmd_read(book_name, books_dir)
    _emit_event("playing", book=book_name)
    _notify("▶️ Audiobook", f"Reproduzindo: {book_name}")
    return result


def show_status() -> str:
    """Show current audiobook status."""
    from jarvis.core.audiobook import cmd_status

    result = cmd_status()
    _emit_event("status", status=result[:200])
    return result


def waybar_status() -> dict[str, Any]:
    """Format audiobook status for waybar."""
    try:
        from jarvis.core.audiobook import _load_bookmark

        bookmark = _load_bookmark()
        if bookmark.playing:
            return {
                "text": "󰏤",
                "tooltip": f"▶ {bookmark.book} — chunk {bookmark.chunk_index}/{bookmark.total_chunks}",
                "class": "audiobook-playing",
            }
        elif bookmark.book:
            return {
                "text": "󰏤",
                "tooltip": f"⏸ {bookmark.book} — pausado",
                "class": "audiobook-paused",
            }
    except Exception:  # noqa: BLE001
        pass

    return {
        "text": "",
        "tooltip": "Audiobook: idle",
        "class": "audiobook-idle",
    }


def rofi_menu() -> None:
    """Open rofi menu for audiobook control."""
    options = [
        "📚 Scan livros",
        "📖 Listar livros",
        "▶️  Tocar livro",
        "⏸  Status",
        "⏹  Parar",
    ]

    try:
        proc = subprocess.run(
            ["rofi", "-dmenu", "-p", "Audiobook:", "-theme", "jarvis-cyan"],
            input="\n".join(options),
            capture_output=True,
            text=True,
            timeout=30,
        )
        choice = proc.stdout.strip()

        if "Scan" in choice:
            result = scan_and_notify()
            print(result)
        elif "Listar" in choice:
            from jarvis.core.audiobook import cmd_list
            print(cmd_list())
        elif "Tocar" in choice:
            # Get book name from user
            proc2 = subprocess.run(
                ["rofi", "-dmenu", "-p", "Livro:", "-theme", "jarvis-cyan"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            book = proc2.stdout.strip()
            if book:
                result = play_book(book)
                print(result)
        elif "Status" in choice:
            print(show_status())
        elif "Parar" in choice:
            from jarvis.core.audiobook import cmd_stop
            result = cmd_stop()
            _emit_event("stopped")
            _notify("⏹ Audiobook", "Reprodução parada")
            print(result)
    except FileNotFoundError:
        print("Rofi não encontrado. Use: jarvis audiobook --scan|--play|--status")
    except subprocess.TimeoutExpired:
        pass


def dispatch_audiobook(args: list[str]) -> int:
    """Dispatch audiobook CLI commands."""
    if not args or args[0] in ("-h", "--help"):
        print("Uso: jarvis audiobook [scan|play|status|stop|waybar|menu]")
        return 0

    cmd = args[0]
    if cmd == "scan":
        print(scan_and_notify(args[1] if len(args) > 1 else None))
    elif cmd == "play":
        if len(args) < 2:
            print("Uso: jarvis audiobook --play <nome_do_livro>")
            return 1
        print(play_book(args[1]))
    elif cmd == "status":
        print(show_status())
    elif cmd == "stop":
        from jarvis.core.audiobook import cmd_stop
        print(cmd_stop())
        _emit_event("stopped")
    elif cmd == "waybar":
        print(json.dumps(waybar_status(), ensure_ascii=False))
    elif cmd == "menu":
        rofi_menu()
    else:
        print(f"Comando desconhecido: {cmd}")
        return 1
    return 0
