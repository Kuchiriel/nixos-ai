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
import subprocess
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


def _print_help() -> None:
    rows = [
        ("/quit", "sair"),
        ("/clear", "limpar contexto"),
        ("/compact", "compactar sessão (auto ao estourar)"),
        ("/status", "status do backend"),
        ("/map", "atualizar repo map"),
        ("/model", "ver modelo atual"),
        ("/recall", "buscar memória episódica"),
        ("/architect", "modo architect (plan + execute)"),
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

def _detect_profile() -> dict[str, Any]:
    """Detecta o perfil do modelo, o model_id correto para o payload, e se
    devemos usar tool_calls nativas ou operar 100% via blocos de texto."""
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
    """Estimativa rápida de tokens (heurística: 1 token ≈ 4 chars)."""
    total_chars = sum(len(json.dumps(m, ensure_ascii=False)) for m in messages)
    return total_chars // 4


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


def _discover_agent_files(start_dir: str | None = None, max_depth: int = 3) -> list[Path]:
    """Procura AGENTS.md / CLAUDE.md / GEMINI.md / copilot instructions em diretório atual e pais."""
    base = Path(start_dir or os.getcwd()).resolve()
    seen: set[Path] = set()
    candidates: list[Path] = []
    cur = base
    depth = 0
    while cur.exists() and depth <= max_depth:
        for name in ("AGENTS.md", "CLAUDE.md", "GEMINI.md"):
            p = cur / name
            if p not in seen and p.exists():
                seen.add(p)
                candidates.append(p)
        gh = cur / ".github"
        if gh.exists():
            p = gh / "copilot-instructions.md"
            if p.exists() and p not in seen:
                seen.add(p)
                candidates.append(p)
        if cur == cur.parent:
            break
        cur = cur.parent
        depth += 1
    return candidates


def _load_agent_context(start_dir: str | None = None) -> str:
    """Carrega AGENTS.md seletivamente — só arquivos < 3KB."""
    files = _discover_agent_files(start_dir)
    if not files:
        return ""
    chunks: list[str] = []
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text and len(text) < 3000:
                chunks.append(text)
        except Exception:  # noqa: BLE001 — leitura de arquivo é best-effort
            continue
    if not chunks:
        return ""
    return "PROJECT RULES:\n" + "\n---\n".join(chunks)


def _persist_session(messages: list[dict[str, Any]], project_root: str | None = None) -> None:
    """Salva histórico com metadata para resume confiável."""
    try:
        state = {
            "project": str(Path(project_root or os.getcwd()).resolve()),
            "messages": messages,
            "ts": time.time(),
            "token_estimate": _estimate_tokens(messages),
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

TOOLS:
- read_file(path, offset?, limit?) → ler ANTES de editar
- str_replace(path, old, new) → old EXATO e único; vazio = criar
- execute_shell(cmd) → bash (ls/grep/pytest/git/curl)
- semantic_search(query, top_k) → busca semântica no código

TEXT FORMAT (quando não há tool_calls):
>>> READ path
path
<<<<<<< SEARCH
old
=======
new
>>>>>>> REPLACE
```bash
cmd
```

RULES:
1. read_file ANTES de str_replace no mesmo path
2. old = cópia EXATA do read_file
3. Se falhar, re-leia com mais contexto
4. Teste após editar, commit após testar
5. Não invente conteúdo sem ler
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
    """Chama o LLM local. Payload contém SOMENTE chaves da spec OpenAI
    /chat/completions (model, messages, temperature, max_tokens, e
    tools/tool_choice apenas se houver ferramentas ativas). Removidos
    `parallel_tool_calls` e `chat_template_kwargs`, que o llama-server
    rejeita com HTTP 400.

    Com debug=True, imprime o payload exato enviado e a resposta crua
    recebida (incluindo latência), para diagnosticar lentidão ou formatos
    de tool-call que o parser de texto não reconhece."""
    cfg = _get_config()
    payload: dict[str, Any] = {
        "model": profile.get("model_id", cfg.llm_model),
        "messages": messages,
        "temperature": profile["temperature"],
        "max_tokens": profile["max_tokens"],
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    if debug:
        approx_tokens = sum(len(str(m)) for m in messages) // 4
        console.print(Rule(
            f"📤 REQUEST → {cfg.llm_base_url.rstrip('/')}/chat/completions "
            f"({len(messages)} msgs, ~{approx_tokens} tok)",
            style="dim",
        ))
        body = json.dumps(payload, ensure_ascii=False, indent=2)[:4000]
        console.print(Syntax(body, "json", theme="ansi_dark", word_wrap=True))

    t0 = time.monotonic()
    resp = requests.post(
        f"{cfg.llm_base_url.rstrip('/')}/chat/completions",
        json=payload,
        timeout=cfg.llm_timeout,
    )
    elapsed = time.monotonic() - t0
    resp.raise_for_status()
    data = resp.json()

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
# Tools — delegação para devtools.py unificado
# ---------------------------------------------------------------------------

def _execute_tool_call(name: str, args: dict[str, Any], approve: bool = False) -> tuple[str, str | None]:
    """Executa tool via handle_dev_tool (devtools.py). Retorna (texto, diff_ou_None)."""
    # execute_shell requer aprovação
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

_JSON_TAG_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_JSON_CODEBLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

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
    max_turns: int = 16,
) -> bool:
    """Roda turnos até texto puro (sucesso) ou max_turns/erro (falha).

    Inclui auto-compaction: se contexto estimado ultrapassar 70% do
    max_tokens do modelo, compacta automaticamente.
    """
    max_context_tokens = profile["max_tokens"] * 8
    compact_threshold = int(max_context_tokens * 0.7)

    for turn in range(max_turns):
        est = _estimate_tokens(messages)
        if est > compact_threshold:
            messages[:] = _compact_session(messages, max_tokens=int(compact_threshold * 0.6))
            if debug:
                console.print(f"[dim]🗜️  auto-compact: {est} → ~{_estimate_tokens(messages)} tok[/]")

        with console.status(f"[jarvis]pensando…[/] ({turn + 1}/{max_turns})", spinner="dots"):
            try:
                data = _call_llm(messages, tools, profile, debug=debug)
            except Exception as e:
                console.print(f"[tool.error]❌ LLM error: {e}[/]")
                return False

        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls")

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

            tool_call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:6]}"
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": output[:5000],
            })

    console.print(f"[tool.error]⚠️  {max_turns} turnos atingidos[/]")
    return False


# ---------------------------------------------------------------------------
# REPL principal
# ---------------------------------------------------------------------------

def dev_repl(project_root: str | None = None, approve: bool = False, continue_session: bool = False, yolo: bool = False) -> None:
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

    console.print(f"[jarvis]jarvis[/] [dim]dev[/] · {profile['name']} · {mode} · [dim]{os.getcwd()}[/]")
    console.print("[dim]/help para comandos[/]\n")

    repo_map = _build_repo_map(os.getcwd())
    memory_ctx = _build_memory_context()
    agent_ctx = _load_agent_context(os.getcwd())
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
    session = _make_prompt_session()

    while True:
        try:
            user_input = session.prompt("> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]tchau[/]")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            console.print("[dim]tchau[/]")
            break

        if user_input == "/clear":
            repo_map = _build_repo_map(os.getcwd())
            memory_ctx = _build_memory_context()
            agent_ctx = _load_agent_context(os.getcwd())
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
            agent_ctx = _load_agent_context(os.getcwd())
            system_prompt = _maybe_disable_thinking(
                SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx, agent_context=agent_ctx)
            )
            messages[0] = {"role": "system", "content": system_prompt}
            console.print("[dim]🗺️  repo map atualizado[/]")
            continue

        if user_input == "/model":
            console.print(f"[dim]{active_model} · {mode}[/]")
            continue

        if user_input == "/recall":
            _print_recall()
            continue

        if user_input == "/help":
            _print_help()
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
    agent_ctx = _load_agent_context(os.getcwd())
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

    repo_map = _build_repo_map(os.getcwd())
    memory_ctx = _build_memory_context(task)
    agent_ctx = _load_agent_context(os.getcwd())
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
