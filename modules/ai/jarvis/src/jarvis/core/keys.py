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
    # NVIDIA_NIM_API_KEY tb: o build.nvidia.com emite nvapi-... e o console
    # antigo emitia NVIDIA_API_KEY. Aceitamos os dois nomes.
    "nvidia": {"env": ["NVIDIA_API_KEY", "NVIDIA_NIM_API_KEY"],
               "files": ["/etc/litellm.env"]},
    # (15/10) vision cloudflare: token + account id do Workers AI.
    "cloudflare_token": {"env": ["CLOUDFLARE_API_TOKEN"],
                         "files": ["/etc/litellm.env"]},
    "cloudflare_account": {"env": ["CLOUDFLARE_ACCOUNT_ID"],
                           "files": ["/etc/litellm.env"]},
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
            # ORDEM DE PREFERÊNCIA (2026-10-02): os alias são testados na
            # ordem do registry, com as linhas por dentro. Antes era o
            # contrário (linha por fora, alias por dentro) e devolvia o
            # PRIMEIRO alias encontrado no arquivo: como `GOOGLE_API_KEY` vem
            # antes de `GEMINI_API_KEY` no /etc/litellm.env, o getter "gemini"
            # devolvia a chave velha do Google e a visão levava 401 com a
            # chave boa sitting right there no arquivo.
            wanted = list(spec.get("env", []))
            lines = []
            for raw_line in text.splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                if k.startswith("export "):
                    k = k[len("export "):].strip()
                lines.append((k, v.strip().strip("\"'")))
            for env_name in wanted:
                for k, v in lines:
                    if k == env_name and v:
                        return v
        except OSError:
            continue
    return ""


def get(name: str) -> str:
    """Retorna o secret `name` ("" se ausente). Nunca levanta.

    PRECEDÊNCIA: ARQUIVO antes do environment (2026-10-02). Diagnosticado
    na prática: o processo JARVIS carrega uma `GEMINI_API_KEY` exportada há
    semanas; quando a chave foi renovada em `/etc/litellm.env`, o `os.environ`
    continuou servindo a velha e a visão recebeu 401 mesmo com o arquivo
    correto. Como quem renova chave edita o arquivo gerenciado por root, o
    arquivo tem de ganhar. O `environment` fica como fallback (útil p/ CI e
    p/ containers sem /etc).
    """
    spec = _SOURCES.get(name, {})
    val = _from_files(spec)
    if val:
        return val
    for env_name in spec.get("env", []):
        val = (os.environ.get(env_name, "") or "").strip().strip("\"'")
        if val:
            return val
    return ""


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
