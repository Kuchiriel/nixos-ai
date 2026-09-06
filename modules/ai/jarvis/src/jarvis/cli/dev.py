"""jarvis dev — CLI interativo de desenvolvimento (estilo Claude Code).

v4.0 — Usa devtools.py unificado (AST guard, backup, safety, fuzzy match).

REPL onde o usuário conversa com o agente e o agente pode:
  - Explorar a codebase via execute_shell
  - Ler arquivos (read_file)
  - Editar/criar arquivos (str_replace, com old='' para criar)
  - Rodar testes, linter, git, web via execute_shell
  - Busca semântica via semantic_search

Dependências: requests, rich, prompt_toolkit (todas em nixpkgs).

Uso:
  jarvis dev                    # REPL no CWD
  jarvis dev --project /path    # diretório específico
  jarvis dev --approve          # aprovação para comandos com efeito
  jarvis dev --yolo             # auto-aprova tudo
  jarvis dev --once "tarefa"    # executa e sai
  jarvis dev --continue         # retoma última sessão
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from jarvis.core.config import get_config as _get_config

# Tools unificadas — AST guard, backup, safety, fuzzy match 4 camadas
from jarvis.core.devtools import (
    handle_dev_tool,
    read_file as _devtools_read_file,
    str_replace as _devtools_str_replace,
    execute_shell as _devtools_execute_shell,
    semantic_search as _devtools_semantic_search,
    list_directory as _devtools_list_directory,
    write_file as _devtools_write_file,
)
from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm
from rich.rule import Rule
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme



# ---------------------------------------------------------------------------
# Event Bus integration — lifecycle events for REPL session
# ---------------------------------------------------------------------------

def _repl_emit(topic: str, **data: object) -> None:
    """Emit a lifecycle event via Event Bus (best-effort, never breaks REPL)."""
    try:
        from jarvis.core.eventbus import get_bus
        get_bus().publish(f"repl.{topic}", data)
    except Exception:  # noqa: BLE001
        pass



# ---------------------------------------------------------------------------
# UI — console rich, tema e sessão de input (prompt_toolkit)
# ---------------------------------------------------------------------------

_THEME = Theme({
    "jarvis": "bold cyan",
    "user": "bold green",
    "tool": "yellow",
    "tool.ok": "green",
    "tool.error": "bold red",
    "diff.add": "green",
    "diff.del": "red3",
    "dim": "grey58",
    "path": "bold blue",
})
console = Console(theme=_THEME)

_SLASH_COMMANDS = [
    "/quit", "/status", "/clear", "/map", "/model",
    "/recall", "/architect", "/debug", "/help",
    "/reasoning", "/compact", "/vault", "/lessons",
    "/modes", "/mode", "/add", "/drop", "/undo",
    "/stats",
]


def _make_prompt_session() -> PromptSession:
    """Sessão de input com histórico, autosuggest e completar de comandos.

    Substitui o antigo _read_user_input baseado em select.select + janela
    de silêncio de 80ms: prompt_toolkit negocia bracketed-paste nativamente,
    então colar texto multilinha chega como um único evento de paste (sem
    submeter cada \\n como Enter) em qualquer terminal que suporte o
    protocolo — sem heurística de timing frágil."""
    return PromptSession(
        history=InMemoryHistory(),
        auto_suggest=AutoSuggestFromHistory(),
        completer=WordCompleter(_SLASH_COMMANDS, sentence=True),
        complete_while_typing=True,
    )


def _print_diff(diff_text: str | None) -> None:
    """Imprime diff compacto — só linhas +/- com cores, sem painel."""
    if not diff_text:
        return
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            console.print(f"  [diff.add]{line}[/]")
        elif line.startswith("-") and not line.startswith("---"):
            console.print(f"  [diff.del]{line}[/]")
        elif line.startswith("@@"):
            console.print(f"  [dim]{line}[/]")


def _print_status(active_model: str, mode: str, messages: list[dict[str, Any]]) -> None:
    try:
        from jarvis.core.health_monitor import BackendHealthMonitor
        cfg = _get_config()
        monitor = BackendHealthMonitor(cfg.llm_base_url.replace("/v1", ""))
        status = monitor.status_dict()
    except Exception as e:
        console.print(f"[tool.error]Erro ao consultar status: {e}[/]")
        return
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_row("Backend", f"{status['state']} ({status['latency_ms']}ms)")
    table.add_row("Model", active_model)
    table.add_row("Modo", mode)
    table.add_row("Mensagens", str(len(messages)))
    table.add_row("Uptime", f"{status['uptime_pct']}%")
    console.print(Panel(table, title="Status", border_style="dim", title_align="left"))


def _print_recall() -> None:
    try:
        from jarvis.core.memory import EpisodicMemory
        cfg = _get_config()
        mem = EpisodicMemory(cfg)
        results = mem.recall("dev", top_k=3)
    except Exception as e:
        console.print(f"[tool.error]Erro: {e}[/]")
        return
    if not results:
        console.print("[dim]Nenhuma memória encontrada.[/]")
        return
    for r in results:
        console.print(f"  [dim][{r.get('kind', '?')}][/] {r.get('text', '')[:100]}")


EDIT_HISTORY: list[dict[str, Any]] = []
PINNED_FILES: dict[str, str] = {}


def _snapshot_file(path_str: str) -> str | None:
    try:
        from pathlib import Path as _P
        p = _P(path_str)
        if not p.is_absolute():
            p = _P(os.getcwd()) / path_str
        if p.exists():
            return p.read_text(encoding="utf-8")
    except Exception:
        pass
    return None


def _pinned_section(max_chars: int = 8000) -> str:
    if not PINNED_FILES:
        return ""
    parts = ["\nPINNED FILES (contexto explícito, autoritativo):"]
    for p, c in PINNED_FILES.items():
        parts.append(f"\n=== PINNED: {p} ===\n{c[:max_chars]}")
    return "\n".join(parts)


def _restore_edit(entry: dict[str, Any]) -> str:
    from pathlib import Path as _P
    from jarvis.core import devtools
    path, prev = entry.get("path", "?"), entry.get("prev")
    if prev is None:
        try:
            p = _P(path)
            if not p.is_absolute():
                p = _P(os.getcwd()) / path
            p.unlink(missing_ok=True)
            return f"🗑️  {path} removido (era arquivo criado)"
        except Exception as e:
            return f"ERROR: {e}"
    res = devtools.write_file(path, prev)
    if res.get("ok", False):
        return f"↩️  {path} restaurado"
    return f"ERROR: {res.get('error', '?')}"


def _print_help() -> None:
    rows = [
        ("/quit", "sair"),
        ("/clear", "limpar contexto"),
        ("/compact", "compactar sessão (auto ao estourar)"),
        ("/status", "status do backend"),
        ("/map", "atualizar repo map"),
        ("/add <path>", "fixar arquivo no contexto"),
        ("/drop <path|--all>", "soltar arquivo do contexto"),
        ("/undo", "desfazer última edição"),
        ("/model", "ver modelo atual"),
        ("/stats", "telemetria real: tokens, janela, TTFT, TPS"),
        ("/recall", "buscar memória episódica"),
        ("/lessons", "buscar lições aprendidas"),
        ("/vault", "listar notas persistentes"),
        ("/architect", "modo architect (plan + execute)"),
        ("/reasoning", "ver/nível reasoning (low|medium|high)"),
        ("/modes", "listar modos disponíveis"),
        ("/mode <slug>", "trocar de modo"),
        ("/debug", "mostra request/response cru da API"),
        ("/help", "esta ajuda"),
    ]
    table = Table(show_header=False, box=None, padding=(0, 1))
    for cmd, desc in rows:
        table.add_row(f"[tool]{cmd}[/]", desc)
    console.print(Panel(table, title="Comandos", border_style="dim", title_align="left"))


# ---------------------------------------------------------------------------
# Config / perfil do modelo
# ---------------------------------------------------------------------------

def _query_server_context_size() -> int:
    """Query llama.cpp /props endpoint for actual n_ctx.

    Falls back to 0 if server is unavailable.
    """
    cfg = _get_config()
    # /props is at root, not under /v1
    base = cfg.llm_base_url.rstrip('/').replace('/v1', '')
    try:
        resp = requests.get(f"{base}/props", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        n_ctx = data.get("default_generation_settings", {}).get("n_ctx", 0)
        if n_ctx > 0:
            return n_ctx
    except Exception:  # noqa: BLE001
        pass
    return 0


def _detect_profile() -> dict[str, Any]:
    """Detecta o perfil do modelo, o model_id correto para o payload, e se
    devemos usar tool_calls nativas ou operar 100% via blocos de texto.

    v4.1: queries actual n_ctx from llama.cpp /props for accurate context."""
    cfg = _get_config()
    model_id = cfg.llm_model  # default: "default"
    try:
        resp = requests.get(f"{cfg.llm_base_url.rstrip('/')}/models", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if data.get("data"):
            model_id = data["data"][0].get("id", model_id)
    except Exception:  # noqa: BLE001 — model_id é best-effort
        pass

    m = model_id.lower()

    # Extrai o total de parâmetros do nome (ex: "35b" em "qwen3.6-35b-a3b"),
    # não o de ativos (o "a3b" indica ativos por token em modelos MoE — o
    # antigo `"3b" in m` colidia com essa substring e classificava modelos
    # MoE grandes como "tiny", cortando max_tokens e desativando tool_calls
    # nativas à toa). Regex pega o primeiro NxB isolado por fronteira de
    # palavra/hífen que não seja precedido por "a" (ativos).
    total_b_match = re.search(r"(?<![a-z])(\d+(?:\.\d+)?)b(?!\w)", m)
    total_b = float(total_b_match.group(1)) if total_b_match else None

    if total_b is not None and total_b >= 30:
        profile = {"name": "large", "max_tokens": 768, "temperature": 0.0}
    elif total_b is not None and total_b >= 7:
        profile = {"name": "small", "max_tokens": 1024, "temperature": 0.0}
    elif total_b is not None and total_b < 7:
        profile = {"name": "tiny", "max_tokens": 512, "temperature": 0.0}
    else:
        profile = {"name": "default", "max_tokens": 1024, "temperature": 0.0}

    profile["model_id"] = model_id

    # Query actual context size from llama.cpp server
    actual_n_ctx = _query_server_context_size()
    if actual_n_ctx > 0:
        profile["context_size"] = actual_n_ctx
    else:
        profile["context_size"] = max(profile["max_tokens"] * 8, 8192)

    # Modelos "tiny" costumam ter function-calling nativo pouco confiável em
    # GGUF quantizado — por padrão operam só em modo texto (0 tokens de
    # overhead de `tools`). Pode ser sobrescrito via cfg.llm_native_tools.
    override = getattr(cfg, "llm_native_tools", None)
    profile["native_tools"] = override if override is not None else profile["name"] != "tiny"
    return profile


def _maybe_disable_thinking(system_prompt: str) -> str:
    """Adiciona '/no_think' se thinking estiver desabilitado."""
    cfg = _get_config()
    if getattr(cfg, "llm_disable_thinking", False):
        return f"{system_prompt}\n/no_think"
    return system_prompt


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimativa via interface única (tokens.py) — nunca heurística inline.

    Fallback grosseiro quando o servidor ainda não devolveu usage real.
    Prefira SessionTelemetry (números reais) via /stats.
    """
    try:
        from jarvis.core.tokens import estimate_messages as _estimate_messages
        return _estimate_messages(messages)
    except Exception:
        total_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
        return total_chars // 4


# --- telemetria de sessão (MISSÃO 4): números REAIS do servidor ---
def _session_telemetry():
    """Singleton lazy de SessionTelemetry (evita import circular no topo)."""
    global _TELEMETRY_SINGLETON
    try:
        return _TELEMETRY_SINGLETON
    except NameError:
        from jarvis.core.context_budget import SessionTelemetry
        _TELEMETRY_SINGLETON = SessionTelemetry()
        return _TELEMETRY_SINGLETON


def _record_llm_telemetry(data: dict[str, Any], latency_s: float, model: str = "") -> None:
    """Extrai usage/timings reais da resposta e alimenta a telemetria."""
    try:
        tel = _session_telemetry()
        usage = data.get("usage", {}) or {}
        timings = data.get("timings", {}) or {}
        details = usage.get("prompt_tokens_details", {}) or {}
        tel.record(
            model=model or data.get("model", ""),
            backend="llama-cpp",
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            latency_s=latency_s,
            tps=float(timings.get("predicted_per_second", 0) or 0),
            cached_tokens=int(details.get("cached_tokens", 0) or 0),
        )
        # Janela real: n_ctx do servidor; uso via slots quando disponível
        if tel.window_tokens <= 0:
            n_ctx = _query_server_context_size()
            if n_ctx > 0:
                tel.window_tokens = n_ctx
        try:
            base = _get_config().llm_base_url.rstrip("/").replace("/v1", "")
            slots = requests.get(f"{base}/slots", timeout=3).json()
            if isinstance(slots, list):
                used = sum(s.get("n_prompt_tokens", 0) for s in slots)
                total = sum(s.get("n_ctx", 0) for s in slots)
                if total > 0:
                    tel.window_tokens = total
                    tel.window_used = used
        except Exception:
            pass
        # Espelha o prompt real na janela quando slots indisponível
        if tel.window_used <= 0 and tel.last and tel.last.prompt_tokens > 0:
            tel.window_used = tel.last.prompt_tokens
    except Exception:
        pass


def _print_stats() -> None:
    """Renderiza telemetria real estilo OpenCode (/stats)."""
    tel = _session_telemetry()
    if tel.n_calls == 0:
        console.print("[dim]sem chamadas nesta sessão — faça uma pergunta primeiro[/]")
        return
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_row("Chamadas", str(tel.n_calls))
    table.add_row("Prompt", f"{tel.total_prompt} tok (real, usage)")
    table.add_row("Completion", f"{tel.total_completion} tok (real, usage)")
    table.add_row("Janela", tel.window_bar())
    table.add_row("TTFT médio", f"{tel.avg_ttft:.2f}s")
    table.add_row("Throughput", f"{tel.avg_tps:.1f} t/s (real, timings)")
    last = tel.last
    if last:
        table.add_row("Última", f"{last.backend}/{last.model} lat={last.latency_s:.2f}s cache={last.cached_tokens}")
    console.print(Panel(table, title="Stats (números reais do servidor)", border_style="dim", title_align="left"))


def _compact_session(messages: list[dict[str, Any]], max_tokens: int = 6000) -> list[dict[str, Any]]:
    """Compacta sessão preservando: system + resumo + turnos recentes.

    Chamado quando _estimate_tokens > max_tokens. O resumo captura o
    essencial do histórico, mantendo o modelo informado sem inflar contexto.
    """
    if _estimate_tokens(messages) <= max_tokens:
        return messages
    system = messages[0]
    recent_count = 6
    if len(messages) <= recent_count + 1:
        return messages
    middle = messages[1:-recent_count]
    recent = messages[-recent_count:]
    summary_parts = ["SESSION HISTORY:"]
    for msg in middle:
        role = msg.get("role", "?")
        content = str(msg.get("content") or "")
        if role == "user":
            summary_parts.append(f"- User: {content[:150]}")
        elif role == "assistant" and content:
            summary_parts.append(f"- Assistant: {content[:150]}")
        elif role == "tool":
            preview = content[:80].replace("\n", " ")
            summary_parts.append(f"- Tool: {preview}")
    for i, m in enumerate(recent):
        if m.get("role") == "user":
            recent = recent[i:]
            break
    summary_msg = {"role": "user", "content": "\n".join(summary_parts)}
    return [system, summary_msg, *recent]


def _auto_index_rag() -> None:
    """Indexa codebase no Qdrant se collection vazia (uma vez por sessão)."""
    if _auto_index_rag._indexed:
        return
    _auto_index_rag._indexed = True
    try:
        from jarvis.core.config import Config
        from jarvis.providers.vector_store import QdrantStore
        cfg = Config()
        store = QdrantStore(cfg)
        if not store.is_available():
            return
        try:
            result = store.client.count(
                collection_name=cfg.qdrant_collection_code, exact=True,
            )
            if result.count > 0:
                return
        except Exception:  # noqa: BLE001 — count é best-effort
            return
        console.print("[dim]📦 Indexando codebase no RAG...[/]")
        try:
            from jarvis.core.rag import HybridIndexer
            indexer = HybridIndexer(cfg)
            total = indexer.index_directory(os.getcwd())
            console.print(f"[dim]✅ {total} chunks indexados.[/]")
        except Exception as e:
            console.print(f"[dim]⚠️  Indexação RAG falhou: {e}[/]")
    except Exception:  # noqa: BLE001 — indexação é best-effort
        pass

_auto_index_rag._indexed = False


def _build_memory_context(query: str = "code edit error fix") -> str:
    """Busca memórias episódicas relevantes para dar contexto ao SLM."""
    try:
        from jarvis.core.memory import EpisodicMemory
        cfg = _get_config()
        mem = EpisodicMemory(cfg)
        if not mem.is_available():
            return ""
        results = mem.recall(query, top_k=3)
        if not results:
            return ""
        lines = ["RECENT LESSONS:"]
        for r in results:
            text = r.get("text", "")[:120]
            lines.append(f"- {text}")
        return "\n".join(lines)
    except Exception:  # noqa: BLE001 — memória é best-effort
        return ""


def _session_state_path(project_root: str | None = None) -> Path:
    """Caminho do estado de sessão persistente do dev CLI."""
    base = Path(os.environ.get("JARVIS_STATE_DIR", "~/.local/state/jarvis")).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    project_root_path = Path(project_root or os.getcwd()).resolve()
    project_id = project_root_path.as_posix().replace("/", "_")
    return base / f"dev-session-{project_id}.json"


def _discover_agent_files(start_dir: str | None = None, max_depth: int = 5) -> list[Path]:
    """Walk up from start_dir discovering agent context files.

    Follows the 2026 standard: AGENTS.md (Linux Foundation), CLAUDE.md
    (Anthropic), GEMINI.md (Google), plus copilot-instructions.md.
    Nearest file takes precedence per AGENTS.md spec.

    Also discovers .jarvismodes (Jarvis custom modes) if present.
    """
    base = Path(start_dir or os.getcwd()).resolve()
    seen: set[Path] = set()
    candidates: list[Path] = []
    cur = base
    depth = 0
    while cur.exists() and depth <= max_depth:
        # Standard agent context files (AGENTS.md spec + vendor extensions)
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "agents.md"):
            p = cur / name
            if p not in seen and p.exists():
                seen.add(p)
                candidates.append(p)
        # GitHub Copilot instructions
        gh = cur / ".github"
        if gh.exists():
            p = gh / "copilot-instructions.md"
            if p.exists() and p not in seen:
                seen.add(p)
                candidates.append(p)
        # Cursor rules (legacy but still honored)
        cr = cur / ".cursorrules"
        if cr.exists() and cr not in seen:
            seen.add(cr)
            candidates.append(cr)
        if cur == cur.parent:
            break
        cur = cur.parent
        depth += 1
    return candidates


def _load_agent_context(start_dir: str | None = None) -> str:
    """Load agent context files — budget-aware, nearest-first.

    Per AGENTS.md spec: closest file wins. We load from nearest to farthest
    and stop when we hit the 3KB budget per-file limit (Codex uses 32KB
    total, but our model has 32K context and system prompt takes ~15-20K).
    """
    files = _discover_agent_files(start_dir)
    if not files:
        return ""
    chunks: list[str] = []
    total_budget = 3000  # max chars per file (conservative for small context)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text and len(text) < total_budget:
                chunks.append(f"# From {path.name} ({path.parent}):\n{text}")
        except Exception:  # noqa: BLE001 — leitura de arquivo é best-effort
            continue
    if not chunks:
        return ""
    return "PROJECT RULES:\n" + "\n---\n".join(chunks)


def _get_git_state(project_root: str | None = None) -> dict[str, Any]:
    """Get current git state for checkpoint."""
    try:
        root = Path(project_root or os.getcwd()).resolve()
        result = {}
        
        # Get branch
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            result["branch"] = proc.stdout.strip()
        
        # Get commit
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            result["commit"] = proc.stdout.strip()[:8]
        
        # Check if clean
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            result["clean"] = len(proc.stdout.strip()) == 0
        
        return result
    except Exception:
        return {}


def _persist_session(messages: list[dict[str, Any]], project_root: str | None = None) -> None:
    """Salva histórico com metadata para resume confiável.
    
    Enhanced with git state, context usage, and tool call tracking.
    """
    try:
        root = project_root or os.getcwd()
        state = {
            "project": str(Path(root).resolve()),
            "messages": messages,
            "ts": time.time(),
            "token_estimate": _estimate_tokens(messages),
            # Git state for recovery
            "git": _get_git_state(root),
            # Session metadata
            "session_id": f"{int(time.time())}",
            "total_messages": len(messages),
            # Tool call count (from messages)
            "tool_calls": sum(1 for m in messages if m.get("role") == "tool"),
        }
        path = _session_state_path(project_root)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001 — persistência é best-effort
        pass


def _resume_session(project_root: str | None = None) -> list[dict[str, Any]]:
    """Carrega a última sessão persistida, se existir."""
    try:
        path = _session_state_path(project_root)
        if not path.exists():
            return []
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            msg = obj.get("messages")
            if isinstance(msg, list):
                return msg
    except Exception:  # noqa: BLE001 — resume é best-effort
        pass
    return []


def _get_session_info(project_root: str | None = None) -> dict[str, Any] | None:
    """Get session info without loading all messages."""
    try:
        path = _session_state_path(project_root)
        if not path.exists():
            return None
        obj = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            return {
                "project": obj.get("project"),
                "timestamp": obj.get("ts"),
                "token_estimate": obj.get("token_estimate"),
                "git": obj.get("git", {}),
                "total_messages": obj.get("total_messages", 0),
                "tool_calls": obj.get("tool_calls", 0),
            }
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# .jarvismodes — modos customizados (estilo .roomodes)
# ---------------------------------------------------------------------------

def _load_jarvismodes() -> list[dict[str, Any]]:
    """Load custom modes from .jarvismodes file.

    Searches: CWD → project root → ~/.jarvismodes
    Format: YAML with 'modes' key, each mode has slug, name, description,
    roleDefinition, instructions.
    """
    search_paths = [
        Path(os.getcwd()) / ".jarvismodes",
        Path(os.getcwd()) / ".jarvis" / "modes.yaml",
    ]
    # Also check home directory
    home_modes = Path.home() / ".jarvismodes"
    if home_modes.exists():
        search_paths.append(home_modes)

    for path in search_paths:
        if not path.exists():
            continue
        try:
            import yaml  # noqa: F401 — optional dependency
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "modes" in data:
                return data["modes"]
        except ImportError:
            # No yaml — try simple line-based parsing
            return _parse_jarvismodes_simple(path)
        except Exception:
            continue
    return []


def _parse_jarvismodes_simple(path: Path) -> list[dict[str, Any]]:
    """Fallback parser for .jarvismodes without PyYAML.

    Supports a simple format:
      slug: name
      description: text
      instructions: |
        multi-line
        text
    """
    modes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    in_instructions = False
    instructions_lines: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.rstrip()
        if not stripped or stripped.startswith("#"):
            continue
        if in_instructions:
            if line.startswith("  ") or line.startswith("\t"):
                instructions_lines.append(line.strip())
                continue
            else:
                if current and instructions_lines:
                    current["instructions"] = "\n".join(instructions_lines)
                in_instructions = False
                instructions_lines = []

        if stripped.startswith("slug:"):
            if current:
                modes.append(current)
            slug = stripped.split(":", 1)[1].strip()
            current = {"slug": slug}
        elif stripped.startswith("name:") and current:
            current["name"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("description:") and current:
            current["description"] = stripped.split(":", 1)[1].strip()
        elif stripped.startswith("instructions:") and current:
            rest = stripped.split(":", 1)[1].strip()
            if rest == "|" or rest == ">-":
                in_instructions = True
            elif rest:
                current["instructions"] = rest
        elif stripped.startswith("roleDefinition:") and current:
            current["roleDefinition"] = stripped.split(":", 1)[1].strip()

    if current:
        if in_instructions and instructions_lines:
            current["instructions"] = "\n".join(instructions_lines)
        modes.append(current)

    return modes


# ---------------------------------------------------------------------------
# Repo map — árvore compacta, top-N arquivos mais recentes, budget de tokens
# ---------------------------------------------------------------------------

_REPO_MAP_IGNORE_DIRS = {
    ".git", "node_modules", "__pycache__", "result", ".direnv", "nixos",
    ".venv", "venv", "env", "dist", "build", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", "target", ".next", ".cache", "htmlcov", ".idea", ".vscode",
    "egg-info",
}


def _build_repo_map(root: str, max_files: int = 20, max_tokens: int = 500) -> str:
    """Constrói um mapa compacto do repositório (estilo Aider repo-map),
    limitado aos `max_files` arquivos mais recentemente modificados e a um
    orçamento aproximado de `max_tokens` (heurística: 1 token ~= 4 chars).

    NOTA (pesquisa): o Aider "de verdade" usa tree-sitter + PageRank sobre um
    grafo de símbolos (arquivos como nós, referências como arestas) para
    escolher os trechos mais relevantes, não só os mais recentes. É
    significativamente melhor em repos grandes, mas exige grammars
    tree-sitter por linguagem — dependência pesada para o objetivo "ultra-
    leve" deste projeto. Fica como possível v3 se o repo map atual (mtime-
    based) começar a trazer arquivos irrelevantes com frequência.
    """
    entries: list[tuple[str, float]] = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _REPO_MAP_IGNORE_DIRS and not d.startswith(".")
        ]
        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == ".":
            rel_dir = ""
        for f in filenames:
            if f.startswith("."):
                continue
            fp = os.path.join(dirpath, f)
            try:
                mtime = os.path.getmtime(fp)
            except OSError:
                continue
            rel_path = os.path.join(rel_dir, f) if rel_dir else f
            entries.append((rel_path, mtime))

    entries.sort(key=lambda x: -x[1])
    entries = entries[:max_files]
    entries.sort(key=lambda x: x[0])  # ordem alfabética para árvore legível

    tree: dict[str, Any] = {}
    for rel_path, _ in entries:
        parts = rel_path.split(os.sep)
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault("__files__", []).append(parts[-1])

    lines: list[str] = []

    def render(node: dict[str, Any], prefix: str = "") -> None:
        dirs = sorted(k for k in node if k != "__files__")
        files = sorted(node.get("__files__", []))
        for d in dirs:
            lines.append(f"{prefix}{d}/")
            render(node[d], prefix + "  ")
        for f in files:
            lines.append(f"{prefix}{f}")

    render(tree)

    budget_chars = max_tokens * 4
    out = [f"REPO MAP ({len(entries)} arquivos mais recentes):"]
    used = len(out[0])
    for line in lines:
        entry = f"  {line}"
        if used + len(entry) + 1 > budget_chars:
            out.append("  … (truncado por orçamento de tokens)")
            break
        out.append(entry)
        used += len(entry) + 1

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """JARVIS dev agent. PT-BR. Direto.

{repo_map}
{memory_context}
{agent_context}

TOOLS (20 tools disponíveis):
--- Arquivos ---
- read_file(path, offset?, limit?) → ler ANTES de editar
- write_file(path, content) → criar/escrever arquivo
- str_replace(path, old, new) → old EXATO; vazio = criar
- list_directory(path, max_depth?) → listar diretório
--- Shell ---
- execute_shell(cmd) → bash (ls/grep/pytest/git/curl)
  Pipes e ; são permitidos: find ... -o ... | head -20
--- Busca ---
- semantic_search(query, top_k) → busca semântica
- rag_search(query) → busca RAG no codebase
- rag_index(path?) → indexar diretório no RAG
--- Vision ---
- capture_screen() → screenshot
- observe_screen(mode?, question?) → screenshot + vision
--- NixOS ---
- nix_eval(expr) → avaliar Nix
- nix_check() → nix flake check
- nix_search(query) → pesquisar nixpkgs
--- Memória ---
- remember(text, category?) → gravar memória
- recall(query) → buscar memórias
- lessons(query) → lições aprendidas
- vault_list() → notas persistentes
- vault_write(name, content) → escrever nota
--- Web ---
- read_chatgpt(url) → ler conversa ChatGPT compartilhada

LIMITES DE OUTPUT (OBRIGATÓRIO):
- find: máx 30 resultados (use -maxdepth 2 | head -30)
- ls: NUNCA recursivo (sem -R)
- git log: máx 10 linhas (git log --oneline -10)
- cat: PROIBIDO (usar head/tail/sed)
- grep: máx 20 resultados (-m 20)
- Output >50 linhas = resuma em bullets

RULES:
1. read_file ANTES de str_replace no mesmo path
2. old = cópia EXATA do read_file
3. Se falhar, re-leia com mais contexto
4. Teste após editar, commit após testar
5. Não invente conteúdo sem ler
6. Use MCP tools quando built-in tools não bastam
7. ANTES de ler arquivo grande: wc -l (saber tamanho)
"""

PLAN_PROMPT = """JARVIS architect. PT-BR. Direto.

{repo_map}

Leia arquivos necessários e retorne JSON puro:
{{"plan": [{{"action": "read|edit|create|shell", "path": "...", "description": "..."}}]}}
"""


# ---------------------------------------------------------------------------
# Chamada HTTP — payload estritamente compatível com a spec OpenAI
# ---------------------------------------------------------------------------

def _call_llm(
    messages: list[dict[str, Any]],
    tools: list[dict],
    profile: dict,
    debug: bool = False,
) -> dict:
    """Chama o LLM via LLMClient (breaker + telemetria reais).

    Unificação da dívida técnica: antes cada chamada abria seu próprio
    requests.post (sem breaker, sem streaming, sem fallback). Agora delega
    ao LLMClient.chat_with_tools() e readapta para o shape cru
    data["choices"][0]["message"] que os 3 callers + text-fallback usam.

    Com debug=True, imprime payload e resposta (conteúdo/tool_calls/
    usage/timings/latência) para diagnosticar lentidão ou formatos de
    tool-call que o parser de texto não reconhece."""
    from jarvis.core.config import Config as _Config
    from jarvis.providers.llm import LLMClient as _LLMClient

    cfg = _get_config()
    model_id = profile.get("model_id", cfg.llm_model)
    payload: dict[str, Any] = {
        "model": model_id,
        "messages": messages,
        "temperature": profile["temperature"],
        "max_tokens": profile["max_tokens"],
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    if debug:
        try:
            from jarvis.core.tokens import estimate_messages as _estimate_messages
            approx_tokens = _estimate_messages(messages)
        except Exception:
            approx_tokens = sum(len(str(m)) for m in messages) // 4
        console.print(Rule(
            f"📤 REQUEST → {cfg.llm_base_url.rstrip('/')}/chat/completions "
            f"({len(messages)} msgs, ~{approx_tokens} tok)",
            style="dim",
        ))
        body = json.dumps(payload, ensure_ascii=False, indent=2)[:4000]
        console.print(Syntax(body, "json", theme="ansi_dark", word_wrap=True))

    client_cfg = _Config(llm_model=model_id, llm_timeout=cfg.llm_timeout)
    t0 = time.monotonic()
    with _LLMClient(config=client_cfg) as client:
        response = client.chat_with_tools(
            messages,
            tools=tools or None,
            temperature=profile["temperature"],
            max_tokens=profile["max_tokens"],
        )
    elapsed = time.monotonic() - t0

    # Shape cru compatível: choices[0].message + usage/model/finish_reason
    data: dict[str, Any] = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": response.content,
                "tool_calls": response.tool_calls or None,
            },
            "finish_reason": response.finish_reason,
        }],
        "usage": response.usage,
        "timings": response.timings,
        "model": response.model_id or model_id,
    }
    _record_llm_telemetry(data, elapsed, model=payload.get("model", ""))

    if debug:
        console.print(Rule(f"📥 RESPONSE ({elapsed:.2f}s)", style="dim"))
        body = json.dumps(data, ensure_ascii=False, indent=2)[:4000]
        console.print(Syntax(body, "json", theme="ansi_dark", word_wrap=True))

    return data


# ---------------------------------------------------------------------------
# Poda de histórico — evita crescimento ilimitado de contexto (= latência
# progressiva e, em modelos "tiny", degradação de qualidade)
# ---------------------------------------------------------------------------

def _trim_messages(messages: list[dict[str, Any]], max_messages: int = 20) -> list[dict[str, Any]]:
    """Mantém a mensagem de system + as últimas `max_messages` mensagens.

    CUIDADO: cortar por posição fixa pode deixar uma mensagem role='tool'
    órfã no topo (sem o assistant/tool_calls correspondente antes dela).
    Chat templates com lógica condicional para agrupar respostas de tool
    (ex: checando o role da mensagem anterior) podem gerar um prompt
    malformado nesse caso — o que na prática se manifestou como geração
    presa/loop (GPU a 99%, sem terminar) quando o histórico cruzava esse
    limiar. Por isso avançamos até a próxima mensagem 'user', que é sempre
    uma fronteira de turno segura (nunca tem tool_calls pendente)."""
    if len(messages) <= max_messages + 1:
        return messages
    system = messages[0]
    tail = messages[-max_messages:]
    for i, m in enumerate(tail):
        if m.get("role") == "user":
            tail = tail[i:]
            break
    return [system, *tail]

# ---------------------------------------------------------------------------
# Auto-commit — Aider-style commit after file modifications
# ---------------------------------------------------------------------------
import subprocess as _sp


def _auto_commit(tool_name: str, args: dict[str, Any], success: bool) -> None:
    """Auto-commit after successful file modifications (Aider-style).
    
    Only commits for tools that modify files:
    - str_replace
    - write_file
    
    Commit message format: jarvis({tool}): {description}
    Branch: jarvis/{session-id} (created on first commit)
    """
    if not success:
        return
    
    # Only commit for file-modifying tools
    if tool_name not in ("str_replace", "write_file"):
        return
    
    # Check if there are changes to commit
    try:
        result = _sp.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=5,
        )
        if not result.stdout.strip():
            return  # No changes
    except Exception:
        return
    
    # Generate commit message
    path = args.get("path", "unknown")
    if tool_name == "str_replace":
        old = args.get("oldString", "")[:50]
        msg = f"jarvis: edit {path} — {old}..."
    else:
        msg = f"jarvis: create/update {path}"
    
    # Stage and commit
    try:
        _sp.run(["git", "add", "-A"], capture_output=True, timeout=5)
        _sp.run(
            ["git", "commit", "-m", msg, "--no-verify"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        pass  # Never break the REPL for commit failures


# ---------------------------------------------------------------------------
# Tools — delegação para devtools.py unificado
# ---------------------------------------------------------------------------
def _execute_tool_call(name: str, args: dict[str, Any], approve: bool = False) -> tuple[str, str | None]:
    """Executa tool via handle_dev_tool (devtools.py). Retorna (texto, diff_ou_None)."""
    # ── Vision ──
    if name == "capture_screen":
        try:
            from jarvis.core.vision import handle_capture
            result = handle_capture(args)
            return result, None
        except Exception as e:
            return f"ERROR: {e}", None

    if name == "observe_screen":
        try:
            from jarvis.core.vision import observe_screen
            result = observe_screen(args)
            return result, None
        except Exception as e:
            return f"ERROR: {e}", None

    # ── NixOS ──
    if name == "nix_eval":
        import subprocess
        expr = args.get("expr", "")
        if not expr:
            return "ERROR: empty expression", None
        res = subprocess.run(["nix", "eval", "--json", expr], capture_output=True, text=True, timeout=30)
        return res.stdout or res.stderr, None

    if name == "nix_check":
        import subprocess
        res = subprocess.run(["nix", "flake", "check"], capture_output=True, text=True, timeout=120, cwd=os.getcwd())
        return res.stdout or res.stderr or "Check passed", None

    if name == "nix_search":
        import subprocess
        query = args.get("query", "")
        if not query:
            return "ERROR: empty query", None
        res = subprocess.run(["nix", "search", "nixpkgs", query, "--json"], capture_output=True, text=True, timeout=30)
        return res.stdout[:3000] if res.stdout else res.stderr, None

    # ── Memory ──
    if name == "remember":
        try:
            from jarvis.core.memory import EpisodicMemory, MemoryEvent
            em = EpisodicMemory()
            event = MemoryEvent(text=args.get("text", ""), kind=args.get("category", "fact"), meta={"source": "repl"})
            mid = em.remember(event)
            return f"Stored (id={mid}): {args.get('text', '')[:100]}...", None
        except Exception as e:
            return f"ERROR: {e}", None

    if name == "recall":
        try:
            from jarvis.core.memory import EpisodicMemory
            em = EpisodicMemory()
            results = em.recall(args.get("query", ""), top_k=5)
            if not results:
                return "No memories found.", None
            lines = []
            for r in results:
                lines.append(f"[{r.get('kind', '?')}] {r.get('text', '')[:200]}")
            return "\n".join(lines), None
        except Exception as e:
            return f"ERROR: {e}", None

    # ── Vault ──
    if name == "vault_list":
        try:
            from jarvis.core.vault import MemoryVault
            mv = MemoryVault()
            notes = mv.list_notes()
            if not notes:
                return "Vault is empty.", None
            return "Vault notes:\n" + "\n".join(f"- {n}" for n in notes), None
        except Exception as e:
            return f"ERROR: {e}", None

    if name == "vault_write":
        try:
            from jarvis.core.vault import MemoryVault
            mv = MemoryVault()
            note_path = mv.vault_dir / f"{args.get('name', '')}.md"
            note_path.parent.mkdir(parents=True, exist_ok=True)
            note_path.write_text(args.get("content", ""))
            return f"Note saved: {note_path}", None
        except Exception as e:
            return f"ERROR: {e}", None

    # ── RAG ──
    if name == "rag_search":
        try:
            from jarvis.core.rag import HybridSearch
            from jarvis.core.config import Config
            cfg = Config()
            hs = HybridSearch(config=cfg)
            results = hs.search(args.get("query", ""), top_k=5)
            if not results:
                return "No results found.", None
            lines = []
            for r in results:
                lines.append(f"[{r.score:.2f}] {r.path}\n{r.text[:200]}")
            return "\n".join(lines), None
        except Exception as e:
            return f"ERROR: {e}", None

    # ── RAG Index ──
    if name == "rag_index":
        try:
            from jarvis.core.rag import HybridIndexer
            hi = HybridIndexer()
            path = args.get("path", os.getcwd())
            count = hi.index_directory(path)
            return f"Indexed {count} files from {path}", None
        except Exception as e:
            return f"ERROR: {e}", None

    # ── Lessons ──
    if name == "lessons":
        try:
            from jarvis.core.memory import EpisodicMemory
            em = EpisodicMemory()
            result = em.lessons(args.get("query", ""), top_k=3)
            return result or "No lessons found.", None
        except Exception as e:
            return f"ERROR: {e}", None

    # ── ChatGPT Reader ──
    if name == "read_chatgpt":
        try:
            from jarvis.core.chatgpt_reader import handle_chatgpt_read
            result = handle_chatgpt_read(args)
            return result, None
        except Exception as e:
            return f"ERROR: {e}", None

    # ── Multi-AI Reader ──
    if name == "read_ai_conversation":
        try:
            from jarvis.core.multi_ai_reader import read_ai_conversation
            result = read_ai_conversation(args.get("url", ""), args.get("max_chars", 50000))
            return result, None
        except Exception as e:
            return f"ERROR: {e}", None

    # ── execute_shell requer aprovação ──
    if name == "execute_shell" and not approve:
        from jarvis.core.agent import command_allowed
        cmd = args.get("cmd", "")
        if cmd and not command_allowed(cmd):
            console.print(f"  [tool.error]⚠  Comando:[/] {cmd}")
            try:
                if not Confirm.ask("  Permitir?", default=False):
                    return "ERROR: command denied by user", None
            except (EOFError, KeyboardInterrupt):
                return "ERROR: approval denied (EOF)", None

    # Snapshot prévio p/ /undo (só edições de arquivo)
    _prev = None
    _tracked = name in ("write_file", "str_replace") and isinstance(args.get("path"), str)
    if _tracked:
        _prev = _snapshot_file(args["path"])

    # Chama handle_dev_tool do devtools.py
    result_json = handle_dev_tool(name, args)
    try:
        result = json.loads(result_json)
    except json.JSONDecodeError:
        return result_json[:3000], None

    if not result.get("ok", False):
        error = result.get("error", "Unknown error")
        hint = result.get("hint", "")
        msg = f"ERROR: {error}"
        if hint:
            msg += f"\n{hint}"
        return msg, None

    if _tracked:
        EDIT_HISTORY.append({"path": args["path"], "prev": _prev})
        del EDIT_HISTORY[:-20]

    # Extrai diff do resultado do str_replace
    diff = result.pop("diff", None)

    # Converte dict para string para o modelo
    if "content" in result:
        return result["content"], diff
    elif "output" in result:
        return result["output"], diff
    elif "results" in result:
        lines = ["SEARCH RESULTS:"]
        for r in result["results"]:
            lines.append(f"- {r['source']} (score={r['score']})\n{r['text']}")
        return "\n".join(lines), diff
    elif "entries" in result:
        lines = [f"DIRECTORY ({result['count']} items):"]
        for e in result["entries"]:
            icon = "📁" if e["type"] == "dir" else "📄"
            lines.append(f"  {icon} {e['name']}")
        return "\n".join(lines), diff
    elif "path" in result:
        strategy = result.get("strategy", "")
        replacements = result.get("replacements", 1)
        return f"OK: {replacements} substituição(ões) em {result['path']} ({strategy})", diff
    else:
        return json.dumps(result, ensure_ascii=False)[:2000], diff


def _get_tools() -> list[dict[str, Any]]:
    """6 tools lean — overhead ~200 tokens."""
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Lê um arquivo com números de linha. Use sempre antes de str_replace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Caminho relativo do arquivo"},
                        "offset": {"type": "integer", "description": "Linha inicial (opcional, 0-indexed)"},
                        "limit": {"type": "integer", "description": "Máximo de linhas (padrão 2000)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "str_replace",
                "description": "Substitui trecho EXATO. old vazio = criar arquivo novo. Fuzzy match automático.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Caminho relativo do arquivo"},
                        "old": {"type": "string", "description": "Texto exato (vazio para criar)"},
                        "new": {"type": "string", "description": "Texto novo"},
                    },
                    "required": ["path", "old", "new"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_shell",
                "description": "Executa comando shell (bash -c). Explorar, testar, git, curl.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string", "description": "Comando shell completo"}
                    },
                    "required": ["cmd"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "semantic_search",
                "description": "Busca semântica no código (mais inteligente que grep, mais lenta).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Query em linguagem natural"},
                        "top_k": {"type": "integer", "description": "Número de resultados (padrão 5)"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Cria/escreve arquivo completo. Backup automático + AST guard.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Caminho do arquivo"},
                        "content": {"type": "string", "description": "Conteúdo completo"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "Lista diretório (recursivo limitado).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Diretório (padrão: raiz)"},
                        "max_depth": {"type": "integer", "description": "Profundidade (padrão 2)"},
                    },
                    "required": [],
                },
            },
        },
        # ── Vision ──
        {
            "type": "function",
            "function": {
                "name": "capture_screen",
                "description": "Captura screenshot da tela atual.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "observe_screen",
                "description": "Captura e analisa screenshot com vision AI.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "mode": {"type": "string", "enum": ["full", "window"], "description": "Modo de captura"},
                        "question": {"type": "string", "description": "O que analisar"},
                    },
                },
            },
        },
        # ── NixOS ──
        {
            "type": "function",
            "function": {
                "name": "nix_eval",
                "description": "Avalia expressão Nix.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expr": {"type": "string", "description": "Expressão Nix"},
                    },
                    "required": ["expr"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "nix_check",
                "description": "Roda nix flake check.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "nix_search",
                "description": "Pesquisa packages/options no nixpkgs.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Termo de busca"},
                        "type": {"type": "string", "enum": ["packages", "options"], "description": "Tipo"},
                    },
                    "required": ["query"],
                },
            },
        },
        # ── Memory ──
        {
            "type": "function",
            "function": {
                "name": "remember",
                "description": "Grava fato/evento na memória episódica.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "O que gravar"},
                        "category": {"type": "string", "description": "Categoria: fact, event, decision"},
                    },
                    "required": ["text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "recall",
                "description": "Busca memórias por similaridade.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "O que buscar"},
                    },
                    "required": ["query"],
                },
            },
        },
        # ── Vault ──
        {
            "type": "function",
            "function": {
                "name": "vault_list",
                "description": "Lista notas no vault persistente.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "vault_write",
                "description": "Escreve nota no vault.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Nome da nota"},
                        "content": {"type": "string", "description": "Conteúdo"},
                    },
                    "required": ["name", "content"],
                },
            },
        },
        # ── RAG ──
        {
            "type": "function",
            "function": {
                "name": "rag_search",
                "description": "Busca semântica no codebase.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "O que buscar"},
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "rag_index",
                "description": "Indexa diretório no RAG (torna código buscabável).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Diretório para indexar (padrão: atual)"},
                    },
                },
            },
        },
        # ── Lessons ──
        {
            "type": "function",
            "function": {
                "name": "lessons",
                "description": "Busca lições aprendidas de erros passados.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Padrão de erro ou problema"},
                    },
                    "required": ["query"],
                },
            },
        },
        # ── ChatGPT Reader ──
        {
            "type": "function",
            "function": {
                "name": "read_chatgpt",
                "description": "Lê conversa compartilhada do ChatGPT.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL de compartilhamento"},
                        "max_chars": {"type": "integer", "description": "Máx de caracteres (padrão 50000)"},
                    },
                    "required": ["url"],
                },
            },
        },
        # ── Multi-AI Reader ──
        {
            "type": "function",
            "function": {
                "name": "read_ai_conversation",
                "description": "Lê conversa de qualquer IA (ChatGPT, Gemini, Claude). Auto-detecta da URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "URL de compartilhamento"},
                        "max_chars": {"type": "integer", "description": "Máx de caracteres (padrão 50000)"},
                    },
                    "required": ["url"],
                },
            },
        },
    ]


# ---------------------------------------------------------------------------
# Parser híbrido de fallback (estilo Aider) — usado quando o modelo não
# emite tool_calls nativas, ou quando native_tools=False (modelos "tiny")
# ---------------------------------------------------------------------------

_SEARCH_REPLACE_RE = re.compile(
    r"^(?P<path>[^\n`*]+?)\s*\n"
    r"<{5,}\s*SEARCH\s*\n"
    r"(?P<old>.*?)\n"
    r"={5,}\s*\n"
    r"(?P<new>.*?)\n"
    r">{5,}\s*REPLACE",
    re.DOTALL | re.MULTILINE,
)

_SHELL_BLOCK_RE = re.compile(r"```(?:bash|sh|shell)\s*\n(?P<cmd>.*?)```", re.DOTALL)

_READ_MARKER_RE = re.compile(r"^>>>\s*READ\s+(?P<path>\S+)\s*$", re.MULTILINE)

# Reutiliza padrões compartilhados de tool_patterns (DRY)
from jarvis.core.tool_patterns import CODEBLOCK_JSON_RE as _JSON_CODEBLOCK_RE
from jarvis.core.tool_patterns import TOOL_CALL_TAG_RE as _JSON_TAG_RE

# Formato Hermes/Llama-3 tool-use fine-tune, ex:
#   <function=read_file>
#   <parameter=path>
#   src/foo.py
#   </parameter>
#   </function>
# Vários modelos GGUF locais (Qwen/Hermes-tuned) preferem esse formato em
# vez de JSON puro — era o que estava quebrando o parser antigo.
_FUNCTION_TAG_RE = re.compile(
    r"<function=(?P<name>\w+)>\s*(?P<body>.*?)\s*</function>", re.DOTALL
)
_PARAMETER_TAG_RE = re.compile(
    r"<parameter=(?P<key>\w+)>\s*(?P<value>.*?)\s*</parameter>", re.DOTALL
)


def _dedupe_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove ações idênticas (mesmo nome+args) — o modelo às vezes repete o
    mesmo tool_call duas vezes no mesmo texto (ex: menciona a ação em prosa
    e depois formaliza em <tool_call>)."""
    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []
    for a in actions:
        key = (a["name"], json.dumps(a["arguments"], sort_keys=True, ensure_ascii=False))
        if key not in seen:
            seen.add(key)
            out.append(a)
    return out


def _parse_text_actions(content: str) -> list[dict[str, Any]] | None:
    """Extrai ações de texto puro quando não há tool_calls nativas.
    Suporta múltiplas ações no mesmo turno (ex: vários blocos SEARCH/REPLACE).

    Prioridade: se o modelo emitiu blocos <function=...> (formato
    Hermes/Llama-3), usa SOMENTE eles — é o formato mais estruturado (tem
    argumentos explícitos) — e ignora qualquer ">>> READ"/texto solto
    redundante que o modelo tenha repetido antes do bloco formal. Sem isso,
    um mesmo pedido (ex: ler um arquivo) podia virar 2 ações idênticas,
    inflando o histórico e duplicando conteúdo de arquivo no contexto."""
    if not content:
        return None

    function_actions: list[dict[str, Any]] = []
    for m in _FUNCTION_TAG_RE.finditer(content):
        name = m.group("name").strip()
        args = {
            pm.group("key").strip(): pm.group("value").strip()
            for pm in _PARAMETER_TAG_RE.finditer(m.group("body"))
        }
        for k in ("start_line", "end_line", "offset", "limit"):
            if k in args and args[k].isdigit():
                args[k] = int(args[k])
        function_actions.append({"name": name, "arguments": args})
    if function_actions:
        return _dedupe_actions(function_actions)

    actions: list[dict[str, Any]] = []

    for m in _SEARCH_REPLACE_RE.finditer(content):
        path = m.group("path").strip().strip("`").strip()
        actions.append({
            "name": "str_replace",
            "arguments": {"path": path, "old": m.group("old"), "new": m.group("new")},
        })

    for m in _READ_MARKER_RE.finditer(content):
        actions.append({"name": "read_file", "arguments": {"path": m.group("path").strip()}})

    for m in _SHELL_BLOCK_RE.finditer(content):
        cmd = m.group("cmd").strip()
        if cmd:
            actions.append({"name": "execute_shell", "arguments": {"cmd": cmd}})

    if actions:
        return _dedupe_actions(actions)

    # Fallback secundário: JSON solto (formato de tool call legado)
    for regex in (_JSON_TAG_RE, _JSON_CODEBLOCK_RE):
        match = regex.search(content)
        if match:
            try:
                parsed = json.loads(match.group(1))
                if isinstance(parsed, dict) and "name" in parsed:
                    return [{"name": parsed["name"], "arguments": parsed.get("arguments", {})}]
            except json.JSONDecodeError:
                pass

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict) and "name" in parsed:
            return [{"name": parsed["name"], "arguments": parsed.get("arguments", {})}]
    except json.JSONDecodeError:
        pass

    return None


def _to_tool_calls(actions: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    """Converte ações extraídas do texto para o mesmo formato de tool_calls
    da API, mantendo o resto do loop agnóstico à origem (nativo vs. texto).

    IDs são uuid curtos e únicos por chamada — o antigo `call_fallback_{i}`
    reiniciava em 0 a cada turno, então conversas com mais de um turno de
    fallback acumulavam tool_call_id duplicados no histórico, o que o
    llama-server rejeita com HTTP 400 assim que o histórico cresce o
    suficiente para expor a colisão na mesma janela de contexto."""
    if not actions:
        return None
    return [
        {
            "id": f"call_{uuid.uuid4().hex[:8]}",
            "type": "function",
            "function": {"name": a["name"], "arguments": json.dumps(a["arguments"], ensure_ascii=False)},
        }
        for a in actions
    ]


# ---------------------------------------------------------------------------
# Loop de execução de agente — ÚNICO em todo o projeto (NOVO em v2.2)
#
# Antes havia 3 cópias quase idênticas desse loop: no REPL principal, no
# handler de /architect (que na verdade nunca chamava o LLM — só empilhava
# mensagens e voltava pro prompt) e em dev_once. Consolidar num só lugar
# corrige o bug do /architect por construção e garante que qualquer fix
# futuro (ex: uma nova estratégia de match) vale para os três fluxos.
# ---------------------------------------------------------------------------

def _run_agent_loop(
    messages: list[dict[str, Any]],
    tools: list[dict],
    profile: dict,
    approve: bool = False,
    debug: bool = False,
    max_turns: int = 30,
    reasoning_level: str = "medium",
) -> bool:
    """Roda turnos até texto puro (sucesso) ou max_turns/erro (falha).

    Inclui auto-compaction: se contexto estimado ultrapassar 70% do
    max_tokens do modelo, compacta automaticamente.
    """
    # Use actual context size from server, not the old max_tokens * 8 heuristic
    context_size = profile.get("context_size", 8192)
    compact_threshold = int(context_size * 0.70)
    compact_target = int(context_size * 0.50)

    for turn in range(max_turns):
        est = _estimate_tokens(messages)
        if est > compact_threshold:
            messages[:] = _compact_session(messages, max_tokens=compact_target)
            _repl_emit("compact.triggered", before=est, after=_estimate_tokens(messages), threshold=compact_threshold)
            if debug:
                console.print(f"[dim]🗜️  auto-compact: {est:,} → ~{_estimate_tokens(messages):,} tok (threshold: {compact_threshold:,})[/]")

        with console.status(f"[jarvis]pensando…[/] ({turn + 1}/{max_turns})", spinner="dots"):
            try:
                data = _call_llm(messages, tools, profile, debug=debug)
            except Exception as e:
                console.print(f"[tool.error]❌ LLM error: {e}[/]")
                return False

        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls")

        # Extract thinking content if present
        thinking = ""
        if "<thinking>" in content and "</thinking>" in content:
            import re as _re
            thinking_match = _re.search(r"<thinking>(.*?)</thinking>", content, _re.DOTALL)
            if thinking_match:
                thinking = thinking_match.group(1).strip()
                content = content[:thinking_match.start()] + content[thinking_match.end():]
                content = content.strip()
        elif reasoning_level != "low" and content:
            # Show first part as thinking if no explicit tags
            lines = content.split("\n")
            if len(lines) > 3:
                thinking = "\n".join(lines[:2])
                content = "\n".join(lines[2:])

        if thinking and reasoning_level != "low":
            console.print(Panel(
                Markdown(thinking) if thinking.strip().startswith(("#", "-", "*", "`")) else thinking,
                title="💭 reasoning",
                title_align="left",
                border_style="dim",
            ))

        used_text_fallback = False
        if not tool_calls and content:
            tool_calls = _to_tool_calls(_parse_text_actions(content))
            used_text_fallback = tool_calls is not None

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or None}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            if content:
                console.print(Panel(
                    Markdown(content), title="🤖", title_align="left", border_style="jarvis",
                ))
            return True

        if used_text_fallback:
            console.print("[dim]  (parser de texto)[/]")

        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            preview_arg = str(args.get("path", args.get("cmd", "")))[:50]
            console.print(f"  [tool]🔧 {func_name}[/] [path]{preview_arg}[/]")

            output, diff = _execute_tool_call(func_name, args, approve)

            is_error = output.startswith("ERROR")
            style = "tool.error" if is_error else "tool.ok"
            icon = "✗" if is_error else "✓"
            preview = output if len(output) <= 120 else f"{output[:120]}…"
            console.print(f"  [{style}]{icon} {preview}[/]")
            if diff:
                _print_diff(diff)

            # Auto-commit after successful file modifications
            if not is_error and diff:
                _auto_commit(func_name, args, success=True)

            tool_call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:6]}"
            _repl_emit("tool.called", tool=func_name, success=not is_error, preview=preview_arg)
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": output[:5000],
            })

    _repl_emit("session.max_turns", max_turns=max_turns)
    console.print(f"[tool.error]⚠️  {max_turns} turnos atingidos[/]")
    return False


# ---------------------------------------------------------------------------
# REPL principal
# ---------------------------------------------------------------------------

def _find_project_root() -> str | None:
    """Auto-detect project root by walking UP from CWD.

    Best practice (2026): Walk up the directory tree from the working
    directory looking for context files. This follows the AGENTS.md spec
    (Linux Foundation) and CLAUDE.md convention: 'agents automatically
    read the nearest file in the directory tree, so the closest one takes
    precedence.' No hardcoded paths — works from any directory.

    Search order: .git (git root) → AGENTS.md → CLAUDE.md → GEMINI.md
    Walking stops at filesystem root or after max_depth levels.
    """
    import subprocess
    # 1. Try git root first (most reliable for repos)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
            cwd=os.getcwd(),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    # 2. Walk up from CWD looking for agent context files
    #    (AGENTS.md spec: nearest file wins, walk up tree)
    base = Path(os.getcwd()).resolve()
    depth = 0
    max_depth = 10
    cur = base
    while cur.exists() and depth <= max_depth:
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md", "agents.md"):
            if (cur / name).exists():
                return str(cur)
        if cur == cur.parent:
            break
        cur = cur.parent
        depth += 1
    return None


def dev_repl(project_root: str | None = None, approve: bool = False, continue_session: bool = False, yolo: bool = False) -> None:
    from jarvis.core.feedback import set_status, clear_status

    # Auto-detect project root if not specified
    if not project_root:
        project_root = _find_project_root()

    if project_root:
        os.environ["JARVIS_PROJECT_ROOT"] = project_root
        os.chdir(project_root)

    if yolo:
        approve = True
        console.print("[tool.ok]⚡ YOLO mode[/]")

    _auto_index_rag()

    profile = _detect_profile()
    tools = _get_tools() if profile["native_tools"] else []
    mode = "native" if profile["native_tools"] else "text"

    # Agent Platform: discover workspace and select persona
    workspace_info = ""
    active_persona = None
    try:
        from jarvis.core.workspace import WorkspaceDiscovery
        ws = WorkspaceDiscovery()
        ws.discover()
        ws.save()
        project_id = os.path.basename(os.getcwd())
        if project_id in ws._projects:
            ctx = ws.get_project_context(project_id)
            workspace_info = f" · {len(ws._projects)} projects"
            # Auto-select persona based on project type
            from jarvis.core.persona import PersonaRegistry
            reg = PersonaRegistry()
            active_persona = reg.select_for_task(project_id)
    except Exception:
        pass

    set_status("listening", "REPL aberto")
    context_size = profile.get("context_size", 0)
    persona_name = active_persona.name if active_persona else "default"
    console.print(f"[jarvis]jarvis[/] [dim]dev[/] · {profile['name']} · {mode}{workspace_info} · [dim]{os.getcwd()}[/]")
    if context_size:
        console.print(f"[dim]ctx: {context_size:,} tokens (from server) · persona: {persona_name}[/]")
    console.print("[dim]/help para comandos[/]\n")

    repo_map = _build_repo_map(os.getcwd())
    memory_ctx = _build_memory_context()
    agent_ctx = _load_agent_context(os.getcwd()) + _pinned_section()
    system_prompt = _maybe_disable_thinking(
        SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx, agent_context=agent_ctx)
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if continue_session:
        resumed = _resume_session(project_root or os.getcwd())
        if resumed:
            messages = resumed
            if len(messages) and messages[0].get("role") == "system":
                messages[0]["content"] = system_prompt
            else:
                messages.insert(0, {"role": "system", "content": system_prompt})
            est = _estimate_tokens(messages)
            console.print(f"[dim]✅ sessão carregada ({est} tok)[/]")

    active_model = profile["name"]
    debug_mode = False
    reasoning_level = "medium"  # low, medium, high
    session = _make_prompt_session()

    while True:
        try:
            user_input = session.prompt("> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]tchau[/]")
            clear_status()
            break

        if not user_input:
            continue

        set_status("thinking", user_input[:50])

        if user_input == "/quit":
            console.print("[dim]tchau[/]")
            clear_status()
            break

        if user_input == "/clear":
            repo_map = _build_repo_map(os.getcwd())
            memory_ctx = _build_memory_context()
            agent_ctx = _load_agent_context(os.getcwd()) + _pinned_section()
            system_prompt = _maybe_disable_thinking(
                SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx, agent_context=agent_ctx)
            )
            messages = [{"role": "system", "content": system_prompt}]
            _persist_session(messages, project_root or os.getcwd())
            console.print("[dim]🗑️  contexto limpo[/]")
            continue

        if user_input == "/compact":
            old_est = _estimate_tokens(messages)
            messages = _compact_session(messages, max_tokens=4000)
            new_est = _estimate_tokens(messages)
            _persist_session(messages, project_root or os.getcwd())
            console.print(f"[dim]🗜️  {old_est} → {new_est} tok[/]")
            continue

        if user_input == "/debug":
            debug_mode = not debug_mode
            console.print(f"[dim]debug {'ON' if debug_mode else 'OFF'}[/]")
            continue

        if user_input == "/status":
            _print_status(active_model, mode, messages)
            continue

        if user_input == "/map":
            repo_map = _build_repo_map(os.getcwd())
            memory_ctx = _build_memory_context()
            agent_ctx = _load_agent_context(os.getcwd()) + _pinned_section()
            system_prompt = _maybe_disable_thinking(
                SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx, agent_context=agent_ctx)
            )
            messages[0] = {"role": "system", "content": system_prompt}
            console.print("[dim]🗺️  repo map atualizado[/]")
            continue

        if user_input == "/model":
            console.print(f"[dim]{active_model} · {mode}[/]")
            continue

        if user_input == "/stats":
            _print_stats()
            continue

        if user_input == "/undo":
            if not EDIT_HISTORY:
                console.print("[dim]nada a desfazer[/]")
            else:
                console.print(f"[dim]{_restore_edit(EDIT_HISTORY.pop())}[/]")
            continue

        if user_input.startswith("/add "):
            target = user_input.split(" ", 1)[1].strip()
            if len(PINNED_FILES) >= 5:
                console.print("[tool.error]máx 5 arquivos fixados (use /drop)[/]")
            else:
                content = _snapshot_file(target)
                if content is None:
                    console.print(f"[tool.error]arquivo não encontrado: {target}[/]")
                else:
                    PINNED_FILES[target] = content
                    repo_map = _build_repo_map(os.getcwd())
                    memory_ctx = _build_memory_context()
                    agent_ctx = _load_agent_context(os.getcwd()) + _pinned_section() + _pinned_section()
                    messages[0] = {"role": "system", "content": _maybe_disable_thinking(
                        SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx, agent_context=agent_ctx))}
                    console.print(f"[dim]📌 {target} fixado ({len(content)} chars)[/]")
            continue

        if user_input == "/drop" or user_input.startswith("/drop "):
            arg = user_input[5:].strip()
            if arg in ("--all", "") and (arg == "--all" or not PINNED_FILES):
                PINNED_FILES.clear()
            elif arg:
                PINNED_FILES.pop(arg, None)
            else:
                console.print("[tool.error]use: /drop <path> | /drop --all[/]")
                continue
            repo_map = _build_repo_map(os.getcwd())
            memory_ctx = _build_memory_context()
            agent_ctx = _load_agent_context(os.getcwd()) + _pinned_section() + _pinned_section()
            messages[0] = {"role": "system", "content": _maybe_disable_thinking(
                SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx, agent_context=agent_ctx))}
            left = ", ".join(PINNED_FILES) or "nenhum"
            console.print(f"[dim]fixados: {left}[/]")
            continue

        if user_input == "/recall":
            _print_recall()
            continue

        if user_input == "/help":
            _print_help()
            continue

        if user_input == "/reasoning":
            console.print(f"[dim]reasoning level: {reasoning_level}[/]")
            continue

        if user_input.startswith("/reasoning "):
            new_level = user_input.split(" ", 1)[1].strip().lower()
            if new_level in ("low", "medium", "high"):
                reasoning_level = new_level
                console.print(f"[dim]reasoning level: {reasoning_level}[/]")
            else:
                console.print("[tool.error]use: /reasoning low|medium|high[/]")
            continue

        if user_input == "/lessons":
            query = session.prompt("query: ").strip()
            if query:
                try:
                    from jarvis.core.memory import EpisodicMemory
                    em = EpisodicMemory()
                    result = em.lessons(query, top_k=5)
                    console.print(Panel(result or "Nenhuma lição encontrada.", title="📚 Lições", border_style="dim", title_align="left"))
                except Exception as e:
                    console.print(f"[tool.error]Erro: {e}[/]")
            continue

        if user_input == "/vault":
            try:
                from jarvis.core.vault import MemoryVault
                mv = MemoryVault()
                notes = mv.list_notes()
                if notes:
                    console.print(Panel("\n".join(f"- {n}" for n in notes), title="📦 Vault", border_style="dim", title_align="left"))
                else:
                    console.print("[dim]Vault vazio.[/]")
            except Exception as e:
                console.print(f"[tool.error]Erro: {e}[/]")
            continue

        if user_input == "/modes":
            modes = _load_jarvismodes()
            if modes:
                table = Table(show_header=False, box=None, padding=(0, 1))
                for m in modes:
                    table.add_row(f"[tool]{m['slug']}[/]", m.get('name', ''), m.get('description', '')[:60])
                console.print(Panel(table, title="🎭 Modos", border_style="dim", title_align="left"))
            else:
                console.print("[dim]Nenhum modo configurado em .jarvismodes[/]")
            continue

        if user_input.startswith("/mode "):
            target_slug = user_input.split(" ", 1)[1].strip().lower()
            modes = _load_jarvismodes()
            found = [m for m in modes if m["slug"] == target_slug]
            if found:
                m = found[0]
                # Reload system prompt with mode-specific instructions
                mode_instructions = m.get("instructions", "")
                mode_role = m.get("roleDefinition", "")
                if mode_instructions or mode_role:
                    extra = f"\n\nMODE: {m.get('name', target_slug)}\n{mode_role}\n\n{mode_instructions}"
                    messages[0] = {"role": "system", "content": system_prompt + extra}
                    console.print(f"[jarvis]modo: {m.get('name', target_slug)}[/]")
                else:
                    console.print(f"[dim]modo '{target_slug}' sem instruções extras[/]")
            else:
                console.print(f"[tool.error]modo '{target_slug}' não encontrado. Use /modes para ver disponíveis.[/]")
            continue

        # ── Agent Platform Commands ──

        if user_input == "/workspace":
            try:
                from jarvis.core.workspace import WorkspaceDiscovery
                ws = WorkspaceDiscovery()
                ws.discover()
                ws.save()
                console.print(Panel(ws.summary(), title="🏗️ Workspace", border_style="dim", title_align="left"))
            except Exception as e:
                console.print(f"[tool.error]Erro: {e}[/]")
            continue

        if user_input.startswith("/workspace "):
            sub = user_input.split(" ", 1)[1].strip()
            try:
                from jarvis.core.workspace import WorkspaceDiscovery
                ws = WorkspaceDiscovery()
                ws.discover()
                ctx = ws.get_project_context(sub)
                if ctx.get("error"):
                    console.print(f"[tool.error]{ctx['error']}[/]")
                else:
                    console.print(Panel(json.dumps(ctx, indent=2, default=str), title=f"🏗️ {sub}", border_style="dim", title_align="left"))
            except Exception as e:
                console.print(f"[tool.error]Erro: {e}[/]")
            continue

        if user_input == "/persona":
            try:
                from jarvis.core.persona import PersonaRegistry
                reg = PersonaRegistry()
                table = Table(show_header=True, box=None, padding=(0, 1))
                table.add_column("ID", style="tool")
                table.add_column("Name")
                table.add_column("Role")
                table.add_column("Tools")
                for p in reg.list_all():
                    table.add_row(p.id, p.name, p.role, str(len(p.tools)))
                console.print(Panel(table, title="🎭 Personas", border_style="dim", title_align="left"))
            except Exception as e:
                console.print(f"[tool.error]Erro: {e}[/]")
            continue

        if user_input.startswith("/persona "):
            sub = user_input.split(" ", 1)[1].strip()
            try:
                from jarvis.core.persona import PersonaRegistry
                reg = PersonaRegistry()
                if sub.startswith("select "):
                    task_desc = sub.split(" ", 1)[1]
                    persona = reg.select_for_task(task_desc)
                    active_persona = persona
                    console.print(f"[jarvis]persona: {persona.name} ({persona.role})[/]")
                else:
                    persona = reg.get(sub)
                    if persona:
                        console.print(Panel(json.dumps(persona.to_dict(), indent=2), title=f"🎭 {persona.name}", border_style="dim", title_align="left"))
                    else:
                        console.print(f"[tool.error]Persona '{sub}' não encontrada[/]")
            except Exception as e:
                console.print(f"[tool.error]Erro: {e}[/]")
            continue

        if user_input == "/workitem" or user_input.startswith("/workitem "):
            try:
                from nightwatch.task_queue import TaskQueue, Task
                queue = TaskQueue(project=os.path.basename(os.getcwd()))
                sub = user_input.split(" ", 1)[1].strip() if " " in user_input else ""
                if sub == "list" or sub == "":
                    tasks = queue._tasks
                    if tasks:
                        table = Table(show_header=True, box=None, padding=(0, 1))
                        table.add_column("ID", style="tool")
                        table.add_column("Status")
                        table.add_column("Description")
                        table.add_column("Project")
                        for t in tasks:
                            table.add_row(t.id[:12], t.status, t.description[:40], t.project)
                        console.print(Panel(table, title="📋 Tasks", border_style="dim", title_align="left"))
                    else:
                        console.print("[dim]Nenhuma task[/]")
                elif sub == "next":
                    task = queue.get_next_task()
                    if task:
                        console.print(Panel(json.dumps(task.to_dict(), indent=2, default=str), title="📋 Next Task", border_style="jarvis", title_align="left"))
                    else:
                        console.print("[dim]Nenhuma tarefa pronta[/]")
                elif sub == "burndown":
                    console.print(json.dumps(queue.get_stats(), indent=2))
                elif sub.startswith("create "):
                    parts = sub.split(" ", 2)
                    desc = parts[1] if len(parts) > 1 else "new task"
                    project = parts[2] if len(parts) > 2 else os.path.basename(os.getcwd())
                    task = Task(id=f"cli-{int(time.time())}", project=project, description=desc, priority=5, risk="low")
                    queue.add_task(task)
                    console.print(f"[tool.ok]Criado: {task.id} — {task.description[:40]}[/]")
                else:
                    console.print("[dim]uso: /workitem [list|next|burndown|create <desc>][/")
            except Exception as e:
                console.print(f"[tool.error]Erro: {e}[/]")
            continue

        if user_input == "/orchestrate" or user_input.startswith("/orchestrate "):
            try:
                from nightwatch.task_queue import TaskQueue
                queue = TaskQueue(project=os.path.basename(os.getcwd()))
                mission = queue.mission
                sub = user_input.split(" ", 1)[1].strip() if " " in user_input else ""
                if sub == "" or sub == "status":
                    stats = queue.get_stats()
                    console.print(f"Mission: active={mission.active}, completed={mission.total_tasks_completed}, commits={mission.total_commits}")
                    console.print(f"Tasks: {stats['total']} total, {stats['completed']} done, {stats['ready']} ready")
                elif sub == "workflows":
                    console.print("Task categories: code-quality, test-coverage, security-scan, nix-check, dedup, docs")
                else:
                    console.print("[dim]uso: /orchestrate [status|workflows|decompose <task>][/")
            except Exception as e:
                console.print(f"[tool.error]Erro: {e}[/]")
            continue

        if user_input == "/architect":
            task_input = session.prompt("> tarefa: ").strip()
            if task_input:
                try:
                    plan = _architect_plan(task_input, profile, tools, debug_mode)
                    if plan:
                        console.print(Panel(plan, title="📋 plano", border_style="jarvis", title_align="left"))
                        exec_input = session.prompt("executar? [Y/n] ").strip().lower()
                        if exec_input != "n":
                            messages.append({"role": "user", "content": task_input})
                            messages.append({"role": "assistant", "content": f"plano: {plan}"})
                            messages.append({"role": "user", "content": "execute o plano"})
                            messages = _trim_messages(messages)
                            _run_agent_loop(messages, tools, profile, approve, debug_mode)
                    else:
                        console.print("[tool.error]⚠️  não gerou plano[/]")
                except Exception as e:
                    console.print(f"[tool.error]❌ {e}[/]")
            continue

        messages.append({"role": "user", "content": user_input})
        messages = _trim_messages(messages)
        ok = _run_agent_loop(messages, tools, profile, approve, debug_mode)
        _persist_session(messages, project_root or os.getcwd())
        if not ok:
            console.print("[dim]ℹ️ sessão salva — continue com --continue[/]")


def _architect_plan(task: str, profile: dict, tools: list, debug: bool = False) -> str | None:
    repo_map = _build_repo_map(os.getcwd())
    plan_prompt = _maybe_disable_thinking(PLAN_PROMPT.format(repo_map=repo_map))
    plan_messages: list[dict[str, Any]] = [
        {"role": "system", "content": plan_prompt},
        {"role": "user", "content": task},
    ]
    try:
        with console.status("[jarvis]lendo arquivos…[/]", spinner="dots"):
            data = _call_llm(plan_messages, tools, profile, debug=debug)
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        tool_calls = msg.get("tool_calls") or _to_tool_calls(_parse_text_actions(content))

        if tool_calls:
            for tc in tool_calls:
                fn = tc["function"]["name"]
                if fn != "read_file":
                    continue
                try:
                    a = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    a = {}
                result, _diff = _execute_tool_call(fn, a)
                tool_id = tc.get("id") or f"call_{uuid.uuid4().hex[:6]}"
                plan_messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
                plan_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result[:2000],
                })

        plan_messages.append({"role": "user", "content": 'retorne JSON: {"plan": [...]}'})
        with console.status("[jarvis]montando plano…[/]", spinner="dots"):
            data2 = _call_llm(plan_messages, tools, profile, debug=debug)
        plan_content = data2["choices"][0]["message"].get("content") or ""
        try:
            parsed = json.loads(plan_content)
            if isinstance(parsed, dict) and "plan" in parsed:
                plan_content = json.dumps(parsed["plan"], ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            pass
        return plan_content[:500]
    except Exception as e:
        console.print(f"[tool.error]⚠️  plano error: {e}[/]")
        return None


def _run_autopilot(task: str, project_root: str | None = None, approve: bool = False, debug: bool = False, continue_session: bool = False, yolo: bool = False) -> int:
    """Modo lote: planeja → executa → checkpoint."""
    if project_root:
        os.environ["JARVIS_PROJECT_ROOT"] = project_root
        os.chdir(project_root)
    if yolo:
        approve = True

    _auto_index_rag()

    profile = _detect_profile()
    tools = _get_tools() if profile["native_tools"] else []
    console.print(f"[jarvis]autopilot[/] · {profile['name']} · {task[:60]}")

    repo_map = _build_repo_map(os.getcwd())
    memory_ctx = _build_memory_context(task)
    agent_ctx = _load_agent_context(os.getcwd()) + _pinned_section()
    system_prompt = _maybe_disable_thinking(
        SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx, agent_context=agent_ctx)
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if continue_session:
        resumed = _resume_session(project_root or os.getcwd())
        if resumed:
            messages = resumed
            if len(messages) and messages[0].get("role") == "system":
                messages[0]["content"] = system_prompt
            else:
                messages.insert(0, {"role": "system", "content": system_prompt})

    plan = _architect_plan(task, profile, tools, debug)
    if plan:
        messages.append({"role": "user", "content": f"Plano inicial:\n{plan}\n\nExecute em etapas curtas com validação de cada fase."})
    messages.append({"role": "user", "content": task})
    messages = _trim_messages(messages)
    ok = _run_agent_loop(messages, tools, profile, approve, debug, max_turns=8)
    _persist_session(messages, project_root or os.getcwd())
    console.print("[dim]🧭 checkpoint salvo[/]")
    _repl_emit("session.ended", success=ok, turns=len(messages))
    return 0 if ok else 1


def dev_once(task: str, project_root: str | None = None, approve: bool = False, debug: bool = False, continue_session: bool = False, yolo: bool = False, autopilot: bool = False) -> int:
    if project_root:
        os.environ["JARVIS_PROJECT_ROOT"] = project_root
        os.chdir(project_root)

    if yolo:
        approve = True

    if autopilot:
        return _run_autopilot(task, project_root=project_root, approve=approve, debug=debug, continue_session=continue_session, yolo=yolo)

    _auto_index_rag()

    profile = _detect_profile()
    tools = _get_tools() if profile["native_tools"] else []

    console.print(f"[jarvis]jarvis[/] [dim]dev[/] · {profile['name']} · {task[:60]}")
    _repl_emit("session.started", task=task[:100], profile=profile["name"])

    repo_map = _build_repo_map(os.getcwd())
    memory_ctx = _build_memory_context(task)
    agent_ctx = _load_agent_context(os.getcwd()) + _pinned_section()
    system_prompt = _maybe_disable_thinking(
        SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx, agent_context=agent_ctx)
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if continue_session:
        resumed = _resume_session(project_root or os.getcwd())
        if resumed:
            messages = resumed
            if len(messages) and messages[0].get("role") == "system":
                messages[0]["content"] = system_prompt
            else:
                messages.insert(0, {"role": "system", "content": system_prompt})

    messages.append({"role": "user", "content": task})
    ok = _run_agent_loop(messages, tools, profile, approve, debug, max_turns=10)
    _persist_session(messages, project_root or os.getcwd())
    return 0 if ok else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="JARVIS Dev — CLI de desenvolvimento local")
    parser.add_argument("--project", type=str, default=None, help="Diretório do projeto")
    parser.add_argument("--approve", action="store_true", help="Ativa aprovação para comandos com efeito")
    parser.add_argument("--yolo", action="store_true", help="Auto-aprova comandos e deixa o agent em modo hands-off")
    parser.add_argument("--continue", dest="continue_session", action="store_true", help="Continua a última sessão persistida do projeto")
    parser.add_argument("--autopilot", action="store_true", help="Modo seguro em lote: plano → execução → validação → checkpoint")
    parser.add_argument("--once", type=str, default=None, help="Executa uma tarefa única e sai")
    parser.add_argument("--debug", action="store_true", help="Modo debug (payloads crus da API)")
    ns = parser.parse_args()

    if ns.once:
        sys.exit(
            dev_once(
                ns.once,
                project_root=ns.project,
                approve=ns.approve,
                debug=ns.debug,
                continue_session=ns.continue_session,
                yolo=ns.yolo,
                autopilot=ns.autopilot,
            )
        )
    else:
        dev_repl(
            project_root=ns.project,
            approve=ns.approve,
            continue_session=ns.continue_session,
            yolo=ns.yolo,
        )
