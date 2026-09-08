"""Abstração única de secrets (fonte de verdade: env, via keys-wrapper.sh).

Camadas (ordem):
  1. environment (populado por ~/.config/ai-agents/keys-wrapper.sh ←
     /etc/litellm.env, ou EnvironmentFile=-/etc/*.env nos services);
  2. arquivos legados legíveis (best-effort, nunca exceção).

NUNCA hardcodear path /etc/* nos consumers — usar get()/require().
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


# key lógica → (envs candidatos, arquivos legados KEY=valor ou JSON)
_SOURCES: dict[str, dict[str, Any]] = {
    "tavily": {
        "env": ["TAVILY_API_KEY"],
        "files": ["/etc/jarvis-secrets/tavily.env"],
    },
    "hackmd": {
        "env": ["HMD_API_ACCESS_TOKEN"],
        "files": ["~/.hackmd/config.json"],
        "json_key": "accessToken",
    },
    "telegram_token": {
        "env": ["JARVIS_TELEGRAM_TOKEN", "TELEGRAM_BOT_TOKEN"],
        "files": ["/etc/jarvis-telegram.env"],
    },
    "telegram_chat": {
        "env": ["JARVIS_TELEGRAM_CHAT_ID", "TELEGRAM_CHAT_ID"],
        "files": ["/etc/jarvis-telegram.env"],
    },
    "groq": {"env": ["GROQ_API_KEY"], "files": ["/etc/litellm.env"]},
    "gemini": {"env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "files": ["/etc/litellm.env"]},
    "openrouter": {"env": ["OPENROUTER_API_KEY"], "files": ["/etc/litellm.env"]},
}


def _from_files(spec: dict[str, Any]) -> str:
    """Lê arquivos legados (ignora silenciosamente o ilegível)."""
    for raw in spec.get("files", []):
        try:
            # Via Path.home() (não os.path.expanduser): respeita $HOME
            # e continua mockável nos testes.
            path = Path.home() / raw[2:] if raw.startswith("~/") else Path(raw)
            if not path.exists():
                continue
            text = path.read_text()
            if path.suffix == ".json":
                try:
                    val = json.loads(text).get(spec.get("json_key", ""), "")
                    if val:
                        return str(val).strip()
                except (ValueError, AttributeError):
                    continue
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                # Tolera legado `export KEY="v"` (WebUI escrevia assim).
                k = k.strip()
                if k.startswith("export "):
                    k = k[len("export "):].strip()
                v = v.strip().strip("\"'")
                for env_name in spec.get("env", []):
                    if k == env_name and v:
                        return v
        except OSError:
            continue
    return ""


def get(name: str) -> str:
    """Retorna o secret `name` ("" se ausente). Nunca levanta."""
    spec = _SOURCES.get(name, {})
    for env_name in spec.get("env", []):
        val = (os.environ.get(env_name, "") or "").strip().strip("\"'")
        if val:
            return val
    return _from_files(spec)


def require(name: str) -> str:
    """Como get(), mas levanta ValueError claro se ausente."""
    val = get(name)
    if not val:
        envs = "/".join(_SOURCES.get(name, {}).get("env", [name]))
        raise ValueError(
            f"Secret '{name}' não configurado. Exporte {envs} "
            "(via keys-wrapper.sh) ou configure o EnvironmentFile do serviço."
        )
    return val


def has(name: str) -> bool:
    """True se o secret está disponível."""
    return bool(get(name))
