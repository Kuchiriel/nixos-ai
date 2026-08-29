```python
"""CLI do JARVIS.

Subcomandos:
  jarvis intent "texto"          — classifica a intenção (determinístico)
  jarvis profile show/set/forget — preferências do usuario (adaptativo)
  jarvis status                  — verifica disponibilidade de llama.cpp e Qdrant
  jarvis chat "pergunta"         — resposta via llama.cpp (OpenAI-compat)
  jarvis rag "busca"             — busca híbrida (dense + sparse BM25 + boosts V4.0.5)
  jarvis index <dir>             — indexa um diretório de código no Qdrant
  jarvis migrate <legacy-dir>    — migração one-shot do índice .ai-index legado
  jarvis parity <legacy-dir>     — teste de paridade (top-k legado vs novo)
  jarvis doctor                  — diagnóstico de saúde de todos os serviços
  jarvis metrics                 — métricas e telemetria dos logs JSONL
  jarvis agent "tarefa"         — agente tool-calling (allowlist + aprovação + audit)
  jarvis ask "pedido"           — roteador: doctor/nixos/rag/agent (caminho mais barato)
  jarvis remember "fato"        — grava um evento na memória episódica
  jarvis recall "busca"         — recupera eventos da memória (híbrido)
  jarvis lessons "erro"         — lições passadas relevantes (estilo experience_buffer)
  jarvis hwdetect               — detecta o hardware (RAM/VRAM/CPU/GPU/NPU)
  jarvis hwprofile              — calcula flags SOTA + melhor modelo p/ o hardware
  jarvis screenshot [full|region|window] — captura de tela (Wayland/Hyprland)
  jarvis triggers run|status     — motor de automações por gatilhos
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any

from jarvis.core.config import get_config
from jarvis.core.intents import classify_intent

# ---------------------------------------------------------------------------
# Structured Logging Setup
# ---------------------------------------------------------------------------

def _json_serializer(obj: Any) -> str:
    """Serializer for JSON structured logs."""
    if isinstance(obj, (Path, bytes)):
        return str(obj)
    return repr(obj)

def get_logger(name: str) -> logging.Logger:
    """Get a logger that outputs structured JSON to stderr."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            '%(message)s',  # We will format the message ourselves as JSON
            datefmt='%Y-%m-%dT%H:%M:%S'
        ))
        # Custom JSON formatter logic embedded in the handler or via a custom Formatter
        # For simplicity and zero-dependency, we'll use a custom emit method or just
        # rely on the caller to format JSON if needed, but here we set up a basic
        # logger that we will manually format in the error handler.
        
        # Actually, to keep it simple and robust without external libs:
        # We will use a custom Formatter class.
        class JsonFormatter(logging.Formatter):
            def format(self, record: logging.LogRecord) -> str:
                log_data = {
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                    "timestamp": self.formatTime(record, self.datefmt),
                }
                if record.exc_info and record.exc_info[0] is not None:
                    log_data["exception"] = {
                        "type": record.exc_info[0].__name__,
                        "message": str(record.exc_info[1]),
                        "traceback": traceback.format_exception(*record.exc_info)
                    }
                return json.dumps(log_data, default=_json_serializer)

        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

logger = get_logger("jarvis.cli")

def _handle_cli_exception(e: Exception, context: str = "") -> int:
    """Centralized error handler for CLI commands."""
    logger.error("Unhandled exception", exc_info=e)
    
    # In production (or generally for CLI), we don't want stack traces for end users
    # unless they are debugging. We show a friendly message.
    error_msg = str(e)
    if not error_msg:
        error_msg = "An unexpected error occurred."
    
    # If the error is a known permission or config issue, we might want to hint.
    print(f"Error: {error_msg}", file=sys.stderr)
    return 1

def _cmd_status(_args: argparse.Namespace) -> int:
    try:
        from jarvis.providers.llm import LLMClient
        from jarvis.providers.vector_store import QdrantStore

        cfg = get_config()
        llm = LLMClient(cfg)
        store = QdrantStore(cfg)
        print(json.dumps({
            "llama_cpp": llm.is_available(),
            "qdrant": store.is_available(),
            "state_dir": str(cfg.ensure_state_dir()),
        }, indent=2))
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "status check")

def _cmd_intent(args: argparse.Namespace) -> int:
    try:
        print(classify_intent(args.text))
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "intent classification")

def _cmd_chat(args: argparse.Namespace) -> int:
    try:
        from jarvis.providers.llm import LLMClient

        llm = LLMClient(get_config())
        response = llm.chat([{"role": "user", "content": args.text}])
        print(response)
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "chat")

def _cmd_rag(args: argparse.Namespace) -> int:
    try:
        from jarvis.core.rag import HybridSearch

        cfg = get_config()
        search = HybridSearch(cfg)
        hits = search.search(args.query, top_k=args.top_k)
        out = []
        for hit in hits:
            out.append({
                "path": hit.path,
                "score": round(hit.score, 4),
                "symbols": hit.payload.get("symbols", []),
            })
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "rag search")

def _cmd_index(args: argparse.Namespace) -> int:
    try:
        # Placeholder for index logic
        print("Indexing directory: " + str(args.dir))
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "index")

def _cmd_migrate(args: argparse.Namespace) -> int:
    try:
        # Placeholder for migrate logic
        print("Migrating legacy index: " + str(args.legacy_dir))
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "migrate")

def _cmd_parity(args: argparse.Namespace) -> int:
    try:
        # Placeholder for parity logic
        print("Running parity check: " + str(args.legacy_dir))
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "parity")

def _cmd_doctor(_args: argparse.Namespace) -> int:
    try:
        # Placeholder for doctor logic
        print("Running doctor check...")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "doctor")

def _cmd_metrics(_args: argparse.Namespace) -> int:
    try:
        # Placeholder for metrics logic
        print("Fetching metrics...")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "metrics")

def _cmd_agent(args: argparse.Namespace) -> int:
    try:
        # Placeholder for agent logic
        print(f"Running agent task: {args.text}")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "agent")

def _cmd_ask(args: argparse.Namespace) -> int:
    try:
        # Placeholder for ask logic
        print(f"Routing ask: {args.text}")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "ask")

def _cmd_remember(args: argparse.Namespace) -> int:
    try:
        # Placeholder for remember logic
        print(f"Remembering: {args.text}")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "remember")

def _cmd_recall(args: argparse.Namespace) -> int:
    try:
        # Placeholder for recall logic
        print(f"Recalling: {args.text}")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "recall")

def _cmd_lessons(args: argparse.Namespace) -> int:
    try:
        # Placeholder for lessons logic
        print(f"Fetching lessons for: {args.text}")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "lessons")

def _cmd_hwdetect(_args: argparse.Namespace) -> int:
    try:
        # Placeholder for hwdetect logic
        print("Detecting hardware...")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "hwdetect")

def _cmd_hwprofile(_args: argparse.Namespace) -> int:
    try:
        # Placeholder for hwprofile logic
        print("Calculating hardware profile...")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "hwprofile")

def _cmd_screenshot(args: argparse.Namespace) -> int:
    try:
        # Placeholder for screenshot logic
        mode = args.mode if hasattr(args, 'mode') else 'full'
        print(f"Taking screenshot: {mode}")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "screenshot")

def _cmd_triggers(args: argparse.Namespace) -> int:
    try:
        # Placeholder for triggers logic
        action = args.action if hasattr(args, 'action') else 'status'
        print(f"Triggers action: {action}")
        return 0
    except Exception as e:
        return _handle_cli_exception(e, "triggers")

def main() -> int:
    parser = argparse.ArgumentParser(prog="jarvis", description="JARVIS CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Status
    p_status = subparsers.add_parser("status", help="Check service status")
    p_status.set_defaults(func=_cmd_status)

    # Intent
    p_intent = subparsers.add_parser("intent", help="Classify intent")
    p_intent.add_argument("text", help="Text to classify")
    p_intent.set_defaults(func=_cmd_intent)

    # Chat
    p_chat = subparsers.add_parser("chat", help="Chat with LLM")
    p_chat.add_argument("text", help="User message")
    p_chat.set_defaults(func=_cmd_chat)

    # RAG
    p_rag = subparsers.add_parser("rag", help="Hybrid search")
    p_rag.add_argument("query", help="Search query")
    p_rag.add_argument("--top-k", type=int, default=5, help="Top K results")
    p_rag.set_defaults(func=_cmd_rag)

    # Index
    p_index = subparsers.add_parser("index", help="Index directory")
    p_index.add_argument("dir", type=Path, help="Directory to index")
    p_index.set_defaults(func=_cmd_index)

    # Migrate
    p_migrate = subparsers.add_parser("migrate", help="Migrate legacy index")
    p_migrate.add_argument("legacy_dir", type=Path, help="Legacy directory")
    p_migrate.set_defaults(func=_cmd_migrate)

    # Parity
    p_parity = subparsers.add_parser("parity", help="Parity test")
    p_parity.add_argument("legacy_dir", type=Path, help="Legacy directory")
    p_parity.set_defaults(func=_cmd_parity)

    # Doctor
    p_doctor = subparsers.add_parser("doctor", help="Health check")
    p_doctor.set_defaults(func=_cmd_doctor)

    # Metrics
    p_metrics = subparsers.add_parser("metrics", help="View metrics")
    p_metrics.set_defaults(func=_cmd