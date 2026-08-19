"""Perfil de usuário dinâmico e contexto adaptativo do JARVIS.

Permite que o agente ajuste comportamento (verbosidade, tom, detalhamento)
com base em preferências declaradas ou inferidas do usuário — sem NUVEM,
sem telemetria, 100% local.

Armazenamento: ``~/.local/state/jarvis/user_profile.json`` (JSON simples).
Cada preferência é uma chave-valor (string). Metadados são preservados
(ultima atualizacao, origem).

Chaves padrão (defaults):
  language       — idioma das respostas (default: "pt-BR")
  verbosity      — nivel de detalhamento: minimal | normal | verbose
  tone           — tom: concise | friendly | technical
  timezone       — timezone do usuario (auto-detectado se vazio)
  expertise      — nivel tecnico: beginner | intermediate | advanced
  preferred_tools — ferramentas preferidas (ex: "rag,agent")
  restrictions   — restricoes de estilo (ex: "no emoji, no jargon")
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, str] = {
    "language": "pt-BR",
    "verbosity": "normal",
    "tone": "concise",
    "timezone": "",
    "expertise": "advanced",
    "preferred_tools": "",
    "restrictions": "",
}


def _profile_path(state_dir: Path | None = None) -> Path:
    if state_dir:
        return state_dir / "user_profile.json"
    base = os.environ.get("JARVIS_STATE_DIR", "")
    if base:
        return Path(base).expanduser() / "user_profile.json"
    return Path.home() / ".local" / "state" / "jarvis" / "user_profile.json"


@dataclass
class UserProfile:
    """Perfil de usuario local — CRUD simples com persistencia JSON."""

    _data: dict[str, str] = field(default_factory=dict)
    _meta: dict[str, dict[str, Any]] = field(default_factory=dict)
    _path: Path | None = None

    def load(self, path: Path | None = None) -> None:
        """Carrega o perfil do disco."""
        p = path or _profile_path()
        self._path = p
        if not p.exists():
            self._data = dict(DEFAULTS)
            self._meta = {}
            return
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            self._data = {k: str(v) for k, v in raw.get("preferences", {}).items()}
            self._meta = raw.get("metadata", {})
            # Merge defaults para chaves novas
            for k, v in DEFAULTS.items():
                if k not in self._data:
                    self._data[k] = v
        except (OSError, json.JSONDecodeError):
            self._data = dict(DEFAULTS)
            self._meta = {}

    def save(self, path: Path | None = None) -> None:
        """Persiste o perfil no disco."""
        p = path or self._path or _profile_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "preferences": self._data,
            "metadata": self._meta,
        }
        p.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def get(self, key: str, default: str = "") -> str:
        """Retorna o valor de uma chave (ou default)."""
        return self._data.get(key, default)

    def set(self, key: str, value: str, *, source: str = "user") -> None:
        """Define uma preferencia e persiste."""
        self._data[key] = value
        self._meta[key] = {
            "updated_at": time.time(),
            "updated_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": source,
        }

    def forget(self, key: str) -> bool:
        """Remove uma chave. Retorna True se existia."""
        if key in self._data:
            del self._data[key]
            self._meta.pop(key, None)
            return True
        return False

    def all(self) -> dict[str, str]:
        """Todas as preferencias."""
        return dict(self._data)

    def meta(self, key: str) -> dict[str, Any]:
        """Metadados de uma chave."""
        return self._meta.get(key, {})


# ---------------------------------------------------------------------------
# Contexto ambiental dinâmico
# ---------------------------------------------------------------------------

def build_context_block(profile: UserProfile) -> str:
    """Gera o bloco de contexto para injecao no system prompt do agente.

    Inclui:
      1. Preferencias do usuario (profile)
      2. Contexto temporal (hora do dia, dia da semana)
      3. Contexto do sistema (hostname, uptime, carga)

    Formato: blocos compactos, sem emojis, otimizados para SLMs.
    """
    parts: list[str] = []

    # 1. Perfil do usuario
    prefs = profile.all()
    lines: list[str] = []
    for k in ("language", "verbosity", "tone", "expertise"):
        v = prefs.get(k, "")
        if v:
            lines.append(f"  {k}: {v}")
    restrictions = prefs.get("restrictions", "")
    if restrictions:
        lines.append(f"  restrictions: {restrictions}")
    if lines:
        parts.append("USER PREFERENCES:\n" + "\n".join(lines))

    # 2. Contexto temporal
    tz = prefs.get("timezone", "")
    try:
        import datetime
        now = datetime.datetime.now()
        hour = now.hour
        weekday = now.strftime("%A")
        time_of_day = (
            "morning" if 5 <= hour < 12
            else "afternoon" if 12 <= hour < 18
            else "evening" if 18 <= hour < 22
            else "night"
        )
        temporal = f"  time: {now.strftime('%H:%M')} ({time_of_day}, {weekday})"
        if tz:
            temporal += f" timezone: {tz}"
        parts.append("ENVIRONMENT:\n" + temporal)
    except Exception:  # noqa: BLE001
        pass

    # 3. Contexto do sistema (leve, sem subprocess pesado)
    try:
        import os as _os
        load = _os.getloadavg()
        mem_line = ""
        try:
            with open("/proc/meminfo", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("MemAvailable:"):
                        kb = int(line.split()[1])
                        mem_line = f"  memory_available: ~{kb // 1024}MB"
                        break
        except OSError:
            pass
        sys_line = f"  load_1m: {load[0]:.1f}  load_5m: {load[1]:.1f}"
        parts.append("SYSTEM:\n" + sys_line + ("\n" + mem_line if mem_line else ""))
    except Exception:  # noqa: BLE001
        pass

    # Ajusta verbosidade com base no perfil
    verbosity = prefs.get("verbosity", "normal")
    if verbosity == "minimal":
        # Apenas perfil + horario (sem sistema)
        parts = [p for p in parts if not p.startswith("SYSTEM")]
    elif verbosity == "verbose":
        # Mantem tudo
        pass

    return "\n\n".join(parts)


def inject_context(system_prompt: str, profile: UserProfile) -> str:
    """Injeta o contexto adaptativo no system prompt do agente.

    Retorna o prompt original + bloco de contexto ao final.
    """
    ctx = build_context_block(profile)
    if not ctx:
        return system_prompt
    return f"{system_prompt}\n\n{ctx}"


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def profile_show(profile: UserProfile) -> str:
    """Formato legivel do perfil."""
    lines = ["User Profile:"]
    for k, v in profile.all().items():
        m = profile.meta(k)
        source = m.get("source", "default")
        lines.append(f"  {k:<20} = {v}  ({source})")
    return "\n".join(lines)


def profile_set(profile: UserProfile, key: str, value: str) -> str:
    """Define uma preferencia e persiste."""
    profile.set(key, value)
    profile.save()
    return f"Profile set: {key} = {value}"


def profile_forget(profile: UserProfile, key: str) -> str:
    """Remove uma preferencia e persiste."""
    if profile.forget(key):
        profile.save()
        return f"Profile forget: {key} removed"
    return f"Profile forget: key '{key}' not found"
