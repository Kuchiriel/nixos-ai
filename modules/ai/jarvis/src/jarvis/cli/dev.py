"""jarvis dev — CLI interativo de desenvolvimento (estilo Aider).

REPL onde o usuário conversa com o agente e o agente pode:
  - Explorar a codebase via execute_shell (ls, find, grep — não há mais
    ferramentas dedicadas de listagem/busca; tudo passa pelo shell)
  - Ler arquivos (read_file)
  - Editar/criar arquivos (str_replace, com old_str='' para criar)
  - Rodar testes, commitar e buscar na web via execute_shell

Arquitetura (v2.2 — UX + confiabilidade de edição):
  - Apenas 3 ferramentas primitivas nativas (read_file, str_replace,
    execute_shell) em vez de ~15 schemas JSON — corta ~2.800 tokens/turno
    de overhead de contexto.
  - Payload HTTP estritamente compatível com a spec OpenAI
    /chat/completions: sem `parallel_tool_calls`, sem `chat_template_kwargs`.
    Modelos "tiny" (<=4B) nem recebem o array `tools` — operam 100% via
    blocos de texto estilo Aider (SEARCH/REPLACE), zerando o overhead.
    Modelos MoE grandes (ex: qwen3.5-30b-a3b) caem em "large" — o regex de
    detecção ignora o sufixo "aXb" (ativos por token), olhando só o total.
  - Parser híbrido: tenta tool_calls nativas da API; se ausentes, faz
    fallback para blocos de texto (SEARCH/REPLACE, `>>> READ`, fenced
    shell, JSON solto, e o formato Hermes/Llama-3 `<function=...>
    <parameter=...>`) — cobre tanto modelos com function-calling robusto
    quanto SLMs locais que só seguem instrução em texto.
  - str_replace com match em cascata (NOVO): se o old_str não bater
    byte-a-byte, tenta um match normalizado (espaços/indentação) antes de
    desistir — inspirado nas 4 estratégias de match do Aider. Modelos
    pequenos raramente copiam whitespace com 100% de fidelidade; sem isso
    a edição falhava e o modelo entrava em loop de retry.
  - Loop de execução único (NOVO): _run_agent_loop() é chamado tanto pelo
    REPL normal quanto pelo /architect quanto pelo --once. Antes, o
    /architect só empilhava mensagens e nunca chamava o LLM de fato — o
    "Executar? [Y/n]" não executava nada até o próximo input manual.
  - Repo map limitado a ~20 arquivos mais recentes (mtime), formatado como
    árvore compacta, com orçamento rígido de ~500 tokens.
  - Histórico da conversa é podado automaticamente (mantém system prompt +
    últimas N mensagens, sempre cortando numa fronteira 'user' segura)
    para evitar crescimento de contexto → latência progressiva.
  - /debug: loga o payload exato enviado à API e a resposta crua recebida.
  - UI (NOVO): rich para saída (painéis, diff colorido, markdown, spinner)
    e prompt_toolkit para entrada (multiline paste nativo — resolve a
    fragilidade do polling manual de stdin — + histórico + autocomplete
    de comandos /).

Dependências além de Python stdlib: requests, rich, prompt_toolkit.
No NixOS, todas as três estão em nixpkgs como pacotes Python puros:
  python3Packages.requests, python3Packages.rich, python3Packages.prompt-toolkit

Uso:
  jarvis dev                    # inicia REPL no CWD
  jarvis dev --project /path    # inicia em diretório específico
  jarvis dev --approve          # ativa aprovação para comandos com efeito
  jarvis dev --once "tarefa"    # executa uma tarefa e sai

Inspirado em: Aider, Claude Code, pi (earendil-works).
"""

from __future__ import annotations

import difflib
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
    if not diff_text:
        return
    body = Text()
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            body.append(line + "\n", style="diff.add")
        elif line.startswith("-") and not line.startswith("---"):
            body.append(line + "\n", style="diff.del")
        elif line.startswith("@@"):
            body.append(line + "\n", style="dim")
        else:
            body.append(line + "\n", style="dim")
    console.print(Panel(body, border_style="dim", padding=(0, 1), expand=False))


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
    table.add_row("Modo de ferramentas", mode)
    table.add_row("Mensagens no histórico", str(len(messages)))
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
        ("/status", "status do backend"),
        ("/map", "atualizar repo map + memória"),
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

def _get_config():
    from jarvis.core.config import Config
    return Config()


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
    except Exception:
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
    """Compat para desabilitar 'thinking' sem reintroduzir chat_template_kwargs
    no payload (que o llama-server rejeita). Vários templates locais
    (família Qwen3, etc.) respeitam a diretiva '/no_think' dentro do próprio
    prompt — então movemos essa configuração do payload HTTP para o texto."""
    cfg = _get_config()
    if getattr(cfg, "llm_disable_thinking", False):
        return f"{system_prompt}\n/no_think"
    return system_prompt


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
    except Exception:
        return ""


def _checkpoint_state(messages: list[dict[str, Any]], project_root: str | None = None) -> None:
    """Salva um snapshot de sessão em disco para continuar depois de longa execução."""
    try:
        base = Path(os.environ.get("JARVIS_STATE_DIR", "~/.local/state/jarvis")).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        checkpoint_dir = base / "checkpoints"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        project_id = str(Path(project_root or os.getcwd()).resolve())
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        snapshot = {
            "project": project_id,
            "ts": stamp,
            "messages": messages[-30:],
        }
        dest = checkpoint_dir / f"{abs(hash(project_id))}_{stamp}.json"
        dest.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _session_state_path(project_root: str | None = None) -> Path:
    """Caminho do estado de sessão persistente do dev CLI."""
    base = Path(os.environ.get("JARVIS_STATE_DIR", "~/.local/state/jarvis")).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    project_root_path = Path(project_root or os.getcwd()).resolve()
    project_id = project_root_path.as_posix().replace("/", "_")
    return base / f"dev-session-{project_id}.json"


def _summarize_for_autopilot(messages: list[dict[str, Any]], max_items: int = 12) -> list[dict[str, Any]]:
    """Encurta a sessão para manter contexto útil sem empilhar o histórico inteiro."""
    if len(messages) <= max_items:
        return messages
    keep: list[dict[str, Any]] = [messages[0]]
    recent = messages[-max_items:]
    summary_lines = ["AUTO SUMMARY:"]
    for msg in recent:
        role = msg.get("role", "unknown")
        content = str(msg.get("content") or "")
        if role == "tool":
            summary_lines.append(f"- tool: {content[:180]}")
        elif role in {"user", "assistant"}:
            summary_lines.append(f"- {role}: {content[:220]}")
    keep.append({"role": "user", "content": "\n".join(summary_lines)})
    return keep


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
    """Carrega o contexto dos AGENTS.md relevantes de diretórios ancestrais."""
    files = _discover_agent_files(start_dir)
    if not files:
        return ""
    chunks: list[str] = ["ACTIVE AGENT CONTEXT:"]
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
            if text:
                chunks.append(f"--- {path} ---\n{text[:2500]}")
        except Exception:
            continue
    return "\n".join(chunks)


def _persist_session(messages: list[dict[str, Any]], project_root: str | None = None) -> None:
    """Salva histórico para continuar depois do reload/overnight."""
    try:
        state = {
            "project": str(Path(project_root or os.getcwd()).resolve()),
            "messages": messages,
            "ts": time.time(),
        }
        path = _session_state_path(project_root)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        _checkpoint_state(messages, project_root)
    except Exception:
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
    except Exception:
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

SYSTEM_PROMPT_TEMPLATE = """Você é o JARVIS, agente de desenvolvimento local. Responda em PT-BR. Seja direto.

{repo_map}

{memory_context}

{agent_context}

FERRAMENTAS (apenas 4 — mantenha o overhead de contexto mínimo):
- read_file(path, start_line?, end_line?)      → leia SEMPRE antes de editar
- str_replace(path, old_str, new_str)          → old_str deve ser EXATO (copiado do read_file) e único no arquivo; old_str='' cria um arquivo novo
- execute_shell(cmd)                            → ls/find/grep (explorar), pytest/npm test (testar),
                                                   git add -A && git commit -m "msg" (commitar),
                                                   curl (buscar na web), rm/mv/mkdir (qualquer outra ação)
- semantic_search(query, top_k=5)               → busca local no código por semântica antes de ler muitos arquivos

Se sua API não suportar tool_calls nativas, use este formato de TEXTO (estilo Aider):

Para ler um arquivo:
>>> READ caminho/do/arquivo.py

Para editar (old deve ser cópia EXATA e única; vazio = cria arquivo novo):
caminho/do/arquivo.py
<<<<<<< SEARCH
texto exato a substituir
=======
texto novo
>>>>>>> REPLACE

Para rodar shell:
```bash
comando aqui
```

REGRAS:
1. SEMPRE read_file (ou >>> READ) antes de str_replace no mesmo path.
2. old_str deve ser cópia EXATA de um trecho do read_file — não parafraseie.
3. Se str_replace falhar (não encontrado ou não-único), read_file de novo e copie melhor, com mais contexto ao redor.
4. Depois de editar, rode os testes via execute_shell.
5. Depois dos testes passarem, faça commit via execute_shell (git add -A && git commit -m "...").
6. Nunca invente conteúdo de arquivo sem ler primeiro.
7. Se existir AGENTS.md / CLAUDE.md / GEMINI.md / instruções do projeto, siga essas regras antes de agir.
8. Modo hands-off: se o alvo for simples e seguro, execute em lote com poucos turns; se houver risco, pare e peça confirmação.
"""

PLAN_PROMPT = """Você é o JARVIS architect. PT-BR. Seja direto.

{repo_map}

Leia os arquivos necessários (read_file ou >>> READ) e monte um PLANO — não execute edições ainda.

Responda em JSON puro, sem markdown:
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
# As 3 ferramentas primitivas
# ---------------------------------------------------------------------------

def _tool_read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 12000,
) -> str:
    if not path:
        return "ERROR: empty path"
    fp = Path(path)
    if not fp.exists():
        return f"ERROR: file not found: {path}"
    if not fp.is_file():
        return f"ERROR: not a file: {path}"
    try:
        text = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

    lines = text.splitlines()
    total = len(lines)
    start = max((start_line or 1) - 1, 0)
    end = min(end_line or total, total)
    window = lines[start:end]

    numbered = "\n".join(f"{start + i + 1:>5} | {line}" for i, line in enumerate(window))
    if len(numbered) <= max_chars:
        suffix = "" if (start == 0 and end == total) else f"\n… (linhas {start + 1}-{end} de {total})"
        return numbered + suffix

    truncated = numbered[:max_chars]
    return (
        f"{truncated}\n… (truncado — {total} linhas totais; use start_line/end_line "
        "ou grep via execute_shell para ver o resto)"
    )


def _find_fuzzy_match(content: str, old_str: str) -> str | None:
    """Tenta localizar old_str no arquivo mesmo com pequenas diferenças de
    espaçamento — usado quando o match exato falha. Modelos pequenos
    quantizados raramente copiam whitespace/indentação com 100% de
    fidelidade ao citar um trecho do read_file; sem essa camada, a edição
    falhava, o modelo tentava de novo e às vezes entrava em loop.

    Estratégia (inspirada nas 4 camadas de match do Aider, reduzida a 1
    para manter o código simples): normaliza espaços/tabs internos de cada
    linha e compara em janelas deslizantes do mesmo tamanho. Só retorna um
    resultado se houver exatamente UM trecho do arquivo real que bate com
    a versão normalizada — ambiguidade (0 ou 2+ candidatos) retorna None,
    igual ao comportamento de "não único" do match exato.
    """
    def norm_line(line: str) -> str:
        return re.sub(r"[ \t]+", " ", line.strip())

    old_lines = [norm_line(line) for line in old_str.splitlines()]
    if not old_lines:
        return None

    content_lines = content.splitlines(keepends=True)
    n = len(old_lines)
    if n == 0 or n > len(content_lines):
        return None

    candidates: list[str] = []
    for i in range(len(content_lines) - n + 1):
        window = content_lines[i:i + n]
        if [norm_line(w) for w in window] == old_lines:
            candidates.append("".join(window))

    return candidates[0] if len(candidates) == 1 else None


def _make_diff(path: str, old: str, new: str) -> str:
    return "\n".join(difflib.unified_diff(
        old.splitlines(), new.splitlines(),
        fromfile=path, tofile=path, lineterm="", n=1,
    ))


def _tool_str_replace(path: str, old_str: str, new_str: str) -> tuple[str, str | None]:
    """Retorna (mensagem_para_o_modelo, diff_para_exibir_ou_None)."""
    if not path:
        return "ERROR: empty path", None
    fp = Path(path)

    if old_str == "":
        if fp.exists():
            return f"ERROR: file already exists — old_str='' só cria arquivos novos: {path}", None
        try:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(new_str, encoding="utf-8")
        except Exception as e:
            return f"ERROR: {e}", None
        diff = _make_diff(path, "", new_str)
        return f"OK: arquivo criado ({len(new_str)} bytes) — {path}", diff

    if not fp.exists():
        return f"ERROR: file not found: {path} (use old_str='' para criar)", None

    try:
        content = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}", None

    count = content.count(old_str)
    matched = old_str
    used_fuzzy = False

    if count == 0:
        fuzzy = _find_fuzzy_match(content, old_str)
        if fuzzy is None:
            return (
                "ERROR: old_str não encontrado (nem com match aproximado por espaçamento). "
                "Faça read_file novamente e copie o texto EXATO."
            ), None
        matched = fuzzy
        used_fuzzy = True
    elif count > 1:
        return f"ERROR: old_str aparece {count}x — não é único. Adicione mais contexto ao redor.", None

    new_content = content.replace(matched, new_str, 1)
    try:
        fp.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return f"ERROR: {e}", None

    diff = _make_diff(path, matched, new_str)
    note = " (via match aproximado — espaçamento diferia)" if used_fuzzy else ""
    return f"OK: 1 substituição em {path}{note} ({len(new_content)} bytes)", diff


def _tool_execute_shell(cmd: str, approve: bool = False) -> str:
    """Primitiva única para explorar (ls/find/grep), testar (pytest/npm test),
    commitar (git add/commit) e buscar na web (curl) — consolida o que antes
    eram ferramentas dedicadas (git_commit, run_tests, web_search, read_url,
    list_directory, code_search). Usa shell=True para suportar comandos
    compostos (ex: `git add -A && git commit -m "msg"`); a gate de aprovação
    (`command_allowed` / --approve) continua sendo a barreira de segurança."""
    from jarvis.core.agent import command_allowed

    if not cmd:
        return "ERROR: empty command"
    if not command_allowed(cmd):
        if not approve:
            return f"ERROR: command not allowed: {cmd} (use --approve)"
        console.print(f"  [tool.error]⚠  Comando:[/] {cmd}")
        try:
            if not Confirm.ask("  Permitir?", default=False):
                return "ERROR: command denied by user"
        except (EOFError, KeyboardInterrupt):
            return "ERROR: approval denied (EOF)"

    try:
        res = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=60,
        )
        output = res.stdout if res.returncode == 0 else (res.stdout + res.stderr)
        if not output.strip():
            output = f"(exit code {res.returncode})"
        return output[:3000]
    except subprocess.TimeoutExpired:
        return "ERROR: command timed out (60s)"
    except Exception as e:
        return f"ERROR: {e}"


def _tool_semantic_search(query: str, top_k: int = 5) -> str:
    """Busca semântica local no Qdrant para encontrar o arquivo certo sem inflar o contexto."""
    if not query or not query.strip():
        return "ERROR: query vazia"
    try:
        from jarvis.core.config import Config
        from jarvis.providers.llm import LLMClient
        from jarvis.providers.vector_store import QdrantStore

        cfg = Config()
        llm = LLMClient(cfg)
        vec = llm.embed(query)
        if not vec:
            return "ERROR: embedding generation failed"
        store = QdrantStore(cfg)
        hits = store.search(cfg.qdrant_collection_code, vec, top_k=top_k)
        if not hits:
            return "OK: semantic_search sem resultados relevantes"

        lines = ["SEMANTIC SEARCH:"]
        for hit in hits[:top_k]:
            payload = hit.get("payload", {})
            path = payload.get("path", "unknown")
            text = str(payload.get("text", ""))[:280]
            score = hit.get("score", 0.0)
            lines.append(f"- {path} (score={score:.3f})\n{text}")
        return "\n".join(lines)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: semantic_search failed: {exc}"


def _execute_tool_call(name: str, args: dict[str, Any], approve: bool = False) -> tuple[str, str | None]:
    """Dispatcher único — só existem 3 ferramentas possíveis. Retorna
    (saída_texto, diff_ou_None) — diff só é preenchido por str_replace, e é
    usado apenas para exibição na UI (o modelo continua recebendo só a
    mensagem de saída, sem inflar o histórico com o diff)."""
    if name == "read_file":
        return _tool_read_file(
            args.get("path", ""),
            args.get("start_line"),
            args.get("end_line"),
        ), None
    if name == "str_replace":
        return _tool_str_replace(
            args.get("path", ""),
            args.get("old_str", ""),
            args.get("new_str", ""),
        )
    if name == "execute_shell":
        return _tool_execute_shell(args.get("cmd", ""), approve), None
    if name == "semantic_search":
        return _tool_semantic_search(args.get("query", ""), args.get("top_k", 5)), None
    return f"ERROR: unknown tool '{name}' (disponíveis: read_file, str_replace, execute_shell, semantic_search)", None


def _get_tools() -> list[dict[str, Any]]:
    """Apenas 3 schemas — overhead total de ~150-250 tokens (vs. ~3.000 do
    array antigo de 15 ferramentas)."""
    return [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Lê o conteúdo de um arquivo com números de linha. Use sempre antes de str_replace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Caminho relativo do arquivo"},
                        "start_line": {"type": "integer", "description": "Linha inicial (opcional, 1-indexed)"},
                        "end_line": {"type": "integer", "description": "Linha final (opcional, inclusive)"},
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "str_replace",
                "description": (
                    "Substitui um trecho EXATO de texto em um arquivo. old_str deve ser "
                    "único no arquivo (copiado do read_file). old_str='' cria um arquivo "
                    "novo com new_str como conteúdo completo."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Caminho relativo do arquivo"},
                        "old_str": {"type": "string", "description": "Texto exato a substituir (vazio para criar arquivo)"},
                        "new_str": {"type": "string", "description": "Texto novo"},
                    },
                    "required": ["path", "old_str", "new_str"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "execute_shell",
                "description": (
                    "Executa um comando shell (bash -c, suporta &&/pipes). Use para: explorar "
                    "arquivos (ls, find, grep), rodar testes (pytest, npm test), git "
                    "(add/commit/diff/log), buscar na web (curl), e qualquer ação que não "
                    "seja ler ou editar um arquivo específico."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cmd": {"type": "string", "description": "Comando shell completo a executar"}
                    },
                    "required": ["cmd"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "semantic_search",
                "description": "Busca semântica local no índice do código para achar o arquivo certo sem inflar o contexto com o repo inteiro.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Query em linguagem natural para encontrar trechos relevantes"},
                        "top_k": {"type": "integer", "description": "Número máximo de resultados (padrão 5)"},
                    },
                    "required": ["query"],
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
        for k in ("start_line", "end_line"):
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
            "arguments": {"path": path, "old_str": m.group("old"), "new_str": m.group("new")},
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
    """Roda turnos até o modelo responder só com texto (sucesso) ou até
    max_turns / erro de LLM (falha). Muta `messages` in-place."""
    for turn in range(max_turns):
        with console.status(f"[jarvis]pensando…[/] (turno {turn + 1}/{max_turns})", spinner="dots"):
            try:
                data = _call_llm(messages, tools, profile, debug=debug)
            except Exception as e:
                console.print(f"[tool.error]❌ Erro LLM: {e}[/]")
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
                    Markdown(content), title="🤖 JARVIS", title_align="left", border_style="jarvis",
                ))
            return True

        if used_text_fallback:
            console.print("[dim]  (ação recuperada via parser de texto)[/]")

        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            preview_arg = str(args.get("path", args.get("cmd", "")))[:60]
            console.print(f"  [tool]🔧 {func_name}[/]([path]{preview_arg}[/])")

            output, diff = _execute_tool_call(func_name, args, approve)

            is_error = output.startswith("ERROR")
            style = "tool.error" if is_error else "tool.ok"
            icon = "⚠️ " if is_error else "✅"
            preview = output if len(output) <= 160 else f"{output[:160]}…"
            console.print(f"  [{style}]{icon} {preview}[/]")
            if diff:
                _print_diff(diff)

            tool_call_id = tc.get("id") or f"call_fallback_{uuid.uuid4().hex[:6]}"
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": output[:5000],
            })

    console.print(
        f"[tool.error]⚠️  Máximo de {max_turns} turnos atingido nesta tarefa[/] — "
        "peça pra continuar ou seja mais específico no próximo pedido."
    )
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
        console.print("[tool.ok]YOLO mode: auto-aprovação ativa para comandos seguros de execução.[/]")

    profile = _detect_profile()
    tools = _get_tools() if profile["native_tools"] else []
    mode = "function-calling nativo" if profile["native_tools"] else "blocos de texto (Aider-style)"

    banner = Table.grid(padding=(0, 1))
    banner.add_row("🤖", f"[jarvis]JARVIS Dev[/] — {profile['name']} (max_tokens={profile['max_tokens']})")
    banner.add_row("📁", os.getcwd())
    banner.add_row("🔧", f"read_file · str_replace · execute_shell — [dim]{mode}[/]")
    console.print(Panel(banner, border_style="jarvis", padding=(0, 1)))
    console.print("[dim]" + "  ".join(_SLASH_COMMANDS) + "[/]\n")

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
            console.print("[dim]✅ Sessão anterior carregada.[/]")

    active_model = profile["name"]
    debug_mode = False
    session = _make_prompt_session()

    while True:
        try:
            user_input = session.prompt("👤 Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[jarvis]👋 Até logo![/]")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            console.print("[jarvis]👋 Até logo![/]")
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
            console.print("[dim]🗑️  Contexto limpo.[/]")
            continue

        if user_input == "/debug":
            debug_mode = not debug_mode
            console.print(f"[dim]🐞 Debug {'ATIVADO' if debug_mode else 'desativado'} — mostra request/response cru da API[/]")
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
            console.print("[dim]🗺️  Repo map + memória atualizados.[/]")
            continue

        if user_input == "/model":
            console.print(f"[dim]Modelo atual: {active_model} — modo: {mode}[/]")
            console.print("[dim]Para trocar, edite models.nix e faça rebuild[/]")
            continue

        if user_input == "/recall":
            _print_recall()
            continue

        if user_input == "/help":
            _print_help()
            continue

        if user_input == "/architect":
            task_input = session.prompt("📋 Tarefa para architect: ").strip()
            if task_input:
                try:
                    plan = _architect_plan(task_input, profile, tools, debug_mode)
                    if plan:
                        console.print(Panel(plan, title="📋 Plano", border_style="jarvis", title_align="left"))
                        exec_input = session.prompt("Executar? [Y/n] ").strip().lower()
                        if exec_input != "n":
                            messages.append({"role": "user", "content": task_input})
                            messages.append({"role": "assistant", "content": f"Plano: {plan}"})
                            messages.append({"role": "user", "content": "Execute este plano. Use as ferramentas disponíveis."})
                            messages = _trim_messages(messages)
                            # FIX: antes o /architect empilhava as mensagens e
                            # voltava pro prompt sem nunca chamar o LLM — o
                            # plano só "executava" se o usuário digitasse
                            # outra coisa depois. Agora roda de fato aqui.
                            _run_agent_loop(messages, tools, profile, approve, debug_mode)
                    else:
                        console.print("[tool.error]⚠️  Não foi possível gerar plano.[/]")
                except Exception as e:
                    console.print(f"[tool.error]❌ Erro: {e}[/]")
            continue

        messages.append({"role": "user", "content": user_input})
        messages = _trim_messages(messages)
        ok = _run_agent_loop(messages, tools, profile, approve, debug_mode)
        _persist_session(messages, project_root or os.getcwd())
        if not ok:
            console.print("[dim]ℹ️ Sessão persistida; pode continuar depois com --continue.[/]")


def _architect_plan(task: str, profile: dict, tools: list, debug: bool = False) -> str | None:
    repo_map = _build_repo_map(os.getcwd())
    plan_prompt = _maybe_disable_thinking(PLAN_PROMPT.format(repo_map=repo_map))
    plan_messages: list[dict[str, Any]] = [
        {"role": "system", "content": plan_prompt},
        {"role": "user", "content": task},
    ]
    try:
        with console.status("[jarvis]lendo arquivos para o plano…[/]", spinner="dots"):
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
                tool_id = tc.get("id") or f"call_plan_{uuid.uuid4().hex[:6]}"
                plan_messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
                plan_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result[:2000],
                })

        plan_messages.append({"role": "user", "content": "Agora retorne o plano em JSON, campo 'plan'."})
        with console.status("[jarvis]montando o plano…[/]", spinner="dots"):
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
        console.print(f"[tool.error]⚠️  Erro no plano: {e}[/]")
        return None


def _run_autopilot(task: str, project_root: str | None = None, approve: bool = False, debug: bool = False, continue_session: bool = False, yolo: bool = False) -> int:
    """Modo seguro de execução em lote: planeja, executa e valida em turnos limitados, com checkpoint final."""
    if project_root:
        os.environ["JARVIS_PROJECT_ROOT"] = project_root
        os.chdir(project_root)
    if yolo:
        approve = True

    profile = _detect_profile()
    tools = _get_tools() if profile["native_tools"] else []
    header = Table.grid(padding=(0, 1))
    header.add_row("🤖", f"[jarvis]AUTOPILOT[/] — {profile['name']}")
    header.add_row("📋", task)
    console.print(Panel(header, border_style="jarvis", padding=(0, 1)))

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
    if len(messages) > 20:
        messages = _summarize_for_autopilot(messages)
    _persist_session(messages, project_root or os.getcwd())
    console.print("[dim]🧭 autopilot: checkpoint salvo e sessão resumível com --continue.[/]")
    return 0 if ok else 1


def dev_once(task: str, project_root: str | None = None, approve: bool = False, debug: bool = False, continue_session: bool = False, yolo: bool = False, autopilot: bool = False) -> int:
    if project_root:
        os.environ["JARVIS_PROJECT_ROOT"] = project_root
        os.chdir(project_root)

    if yolo:
        approve = True

    if autopilot:
        return _run_autopilot(task, project_root=project_root, approve=approve, debug=debug, continue_session=continue_session, yolo=yolo)

    profile = _detect_profile()
    tools = _get_tools() if profile["native_tools"] else []

    header = Table.grid(padding=(0, 1))
    header.add_row("🤖", f"[jarvis]JARVIS Dev[/] — {profile['name']}")
    header.add_row("📋", task)
    console.print(Panel(header, border_style="jarvis", padding=(0, 1)))

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
