"""Logging centralizado em JSONL para todos os submódulos do JARVIS.

Cada submódulo (agent, heal, fastpath, voice, rag) escreve eventos
estruturados no mesmo diretório. O formato é JSON Lines (um JSON por linha)
com campos padronizados:

  ts        — timestamp Unix (float)
  iso       — timestamp ISO 8601 com timezone
  module    — módulo gerador (agent|heal|fastpath|voice|rag|doctor|metric)
  event     — nome do evento (tool_call|heal_restart|fastpath_match|etc)
  level     — severidade (info|warn|error)
  detail    — payload livre (dict ou string)

O diretório padrão é ``~/.local/state/jarvis/logs/`` (declarativo via
Config.state_dir + subdir ``logs/``). Um logger por módulo; escrita
append-only; rotação por tamanho (max 10MB por arquivo, keeps 3).

Zero dependências externas — usa apenas stdlib.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 10 * 1024 * 1024  # 10 MB
KEEP_ROTATED = 3


def _default_log_dir() -> Path:
    base = os.environ.get("JARVIS_STATE_DIR", "")
    if base:
        return Path(base).expanduser() / "logs"
    return Path.home() / ".local" / "state" / "jarvis" / "logs"


class Logger:
    """Logger JSONL estruturado — um por módulo (agent, heal, etc)."""

    def __init__(self, module: str, log_dir: Path | None = None) -> None:
        self.module = module
        self._dir = log_dir or _default_log_dir()
        self._dir_ok: bool | None = None  # lazy: None = untested, True/False

    def _ensure_dir(self) -> bool:
        if self._dir_ok is None:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                self._dir_ok = True
            except (OSError, PermissionError):
                self._dir_ok = False
        return self._dir_ok

    @property
    def _file(self) -> Path:
        return self._dir / f"{self.module}.jsonl"

    def _rotate_if_needed(self) -> None:
        f = self._file
        if not f.exists():
            return
        if f.stat().st_size < MAX_FILE_BYTES:
            return
        # Rotaciona: .3 → remove, .2 → .3, .1 → .2, current → .1
        for i in range(KEEP_ROTATED - 1, 0, -1):
            src = f.with_suffix(f".{i}.jsonl")
            dst = f.with_suffix(f".{i + 1}.jsonl")
            if src.exists():
                if i + 1 >= KEEP_ROTATED:
                    src.unlink()
                else:
                    shutil.move(str(src), str(dst))
        shutil.move(str(f), str(f.with_suffix(".1.jsonl")))

    def emit(self, event: str, *, level: str = "info",
             detail: Any = None, **extra: Any) -> None:
        """Emite um evento estruturado."""
        if not self._ensure_dir():
            return  # diretório inacessível (sandbox Nix, etc.)
        entry: dict[str, Any] = {
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "module": self.module,
            "event": event,
            "level": level,
        }
        if detail is not None:
            entry["detail"] = detail
        if extra:
            entry.update(extra)
        self._rotate_if_needed()
        try:
            with self._file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass

    def info(self, event: str, **kw: Any) -> None:
        self.emit(event, level="info", **kw)

    def warn(self, event: str, **kw: Any) -> None:
        self.emit(event, level="warn", **kw)

    def error(self, event: str, **kw: Any) -> None:
        self.emit(event, level="error", **kw)


# ---------------------------------------------------------------------------
# Loggers pré-configurados por módulo
# ---------------------------------------------------------------------------

_loggers: dict[str, Logger] = {}


def get_logger(module: str, log_dir: Path | None = None) -> Logger:
    """Retorna (ou cria) o logger de um módulo. Cache por nome."""
    if module not in _loggers:
        _loggers[module] = Logger(module, log_dir)
    return _loggers[module]


# ---------------------------------------------------------------------------
# Leitura de métricas (para `jarvis metrics`)
# ---------------------------------------------------------------------------

def read_events(module: str | None = None, *,
                since_ts: float | None = None,
                limit: int = 500,
                log_dir: Path | None = None) -> list[dict[str, Any]]:
    """Lê eventos do log. Se module=None, lê de todos os módulos."""
    d = log_dir or _default_log_dir()
    if not d.exists():
        return []

    files: list[Path] = []
    if module:
        f = d / f"{module}.jsonl"
        if f.exists():
            files.append(f)
    else:
        files = sorted(d.glob("*.jsonl"))

    events: list[dict[str, Any]] = []
    for f in files:
        try:
            with f.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if since_ts and ev.get("ts", 0) < since_ts:
                        continue
                    events.append(ev)
        except OSError:
            continue

    # Ordena por timestamp e limita
    events.sort(key=lambda e: e.get("ts", 0), reverse=True)
    return events[:limit]


def compute_metrics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Agrupa eventos e calcula métricas agregadas."""
    metrics: dict[str, Any] = {
        "total_events": len(events),
        "by_module": {},
        "by_level": {"info": 0, "warn": 0, "error": 0},
        "by_event": {},
    }
    for ev in events:
        mod = ev.get("module", "?")
        lvl = ev.get("level", "info")
        evt = ev.get("event", "?")

        metrics["by_module"].setdefault(mod, 0)
        metrics["by_module"][mod] += 1

        if lvl in metrics["by_level"]:
            metrics["by_level"][lvl] += 1

        metrics["by_event"].setdefault(evt, 0)
        metrics["by_event"][evt] += 1

    return metrics
