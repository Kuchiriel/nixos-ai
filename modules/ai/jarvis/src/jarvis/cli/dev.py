"""jarvis dev — CLI interativo de desenvolvimento (estilo Aider).

REPL onde o usuário conversa com o agente e o agente pode:
  - Explorar a codebase via execute_shell (ls, find, grep — não há mais
    ferramentas dedicadas de listagem/busca; tudo passa pelo shell)
  - Ler arquivos (read_file)
  - Editar/criar arquivos (str_replace, com old_str='' para criar)
  - Rodar testes, commitar e buscar na web via execute_shell

Arquitetura (v2.1 — ultra-leve, 100% compatível com llama-server/GGUF):
  - Apenas 3 ferramentas primitivas nativas (read_file, str_replace,
    execute_shell) em vez de ~15 schemas JSON — corta ~2.800 tokens/turno
    de overhead de contexto.
  - Payload HTTP estritamente compatível com a spec OpenAI
    /chat/completions: sem `parallel_tool_calls`, sem `chat_template_kwargs`.
    Modelos "tiny" (<=4B) nem recebem o array `tools` — operam 100% via
    blocos de texto estilo Aider (SEARCH/REPLACE), zerando o overhead.
  - Parser híbrido: tenta tool_calls nativas da API; se ausentes, faz
    fallback para blocos de texto (SEARCH/REPLACE, `>>> READ`, fenced
    shell, JSON solto, e o formato Hermes/Llama-3 `<function=...>
    <parameter=...>`) — cobre tanto modelos com function-calling robusto
    quanto SLMs locais que só seguem instrução em texto.

    NOTA: essa escolha (texto > JSON tool-calling para modelos pequenos)
    segue o próprio Aider, que não usa tool_calls JSON nativamente —
    processa tudo via formatos de diff em texto plano, justamente para
    evitar a inconsistência de function-calling em modelos <30B.
  - Repo map limitado a ~20 arquivos mais recentes (mtime), formatado como
    árvore compacta, com orçamento rígido de ~500 tokens.
  - Histórico da conversa é podado automaticamente (mantém system prompt +
    últimas N mensagens) para evitar crescimento de contexto → latência
    progressiva em sessões longas.
  - /debug: loga o payload exato enviado à API e a resposta crua recebida,
    para diagnosticar formatos de tool-call inesperados ou lentidão.

Uso:
  jarvis dev                    # inicia REPL no CWD
  jarvis dev --project /path    # inicia em diretório específico
  jarvis dev --approve          # ativa aprovação para comandos com efeito
  jarvis dev --once "tarefa"    # executa uma tarefa e sai

Inspirado em: Aider, Claude Code, pi (earendil-works).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

import requests


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
    if "32b" in m or "30b" in m:
        profile = {"name": "large", "max_tokens": 768, "temperature": 0.0}
    elif "7b" in m:
        profile = {"name": "small", "max_tokens": 1024, "temperature": 0.0}
    elif "4b" in m or "3b" in m or "1b" in m:
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

FERRAMENTAS (apenas 3 — mantenha o overhead de contexto mínimo):
- read_file(path, start_line?, end_line?)      → leia SEMPRE antes de editar
- str_replace(path, old_str, new_str)          → old_str deve ser EXATO (copiado do read_file) e único no arquivo; old_str='' cria um arquivo novo
- execute_shell(cmd)                            → ls/find/grep (explorar), pytest/npm test (testar),
                                                   git add -A && git commit -m "msg" (commitar),
                                                   curl (buscar na web), rm/mv/mkdir (qualquer outra ação)

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
        print(f"\n{'─' * 60}")
        print(f"📤 REQUEST → {cfg.llm_base_url.rstrip('/')}/chat/completions")
        print(f"   ({len(messages)} mensagens, ~{sum(len(str(m)) for m in messages) // 4} tokens estimados)")
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])

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
        print(f"📥 RESPONSE ({elapsed:.2f}s)")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
        print(f"{'─' * 60}\n")

    return data


# ---------------------------------------------------------------------------
# Poda de histórico — evita crescimento ilimitado de contexto (= latência
# progressiva e, em modelos "tiny", degradação de qualidade)
# ---------------------------------------------------------------------------

def _trim_messages(messages: list[dict[str, Any]], max_messages: int = 20) -> list[dict[str, Any]]:
    """Mantém a mensagem de system + as últimas `max_messages` mensagens.
    Chamado a cada novo turno de usuário — não corta no meio de um par
    tool_call/tool_result porque só age nas fronteiras de turno (antes de
    anexar o próximo input do usuário)."""
    if len(messages) <= max_messages + 1:
        return messages
    system = messages[0]
    tail = messages[-max_messages:]
    return [system, *tail]


# ---------------------------------------------------------------------------
# As 3 ferramentas primitivas
# ---------------------------------------------------------------------------

def _tool_read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 4000,
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


def _tool_str_replace(path: str, old_str: str, new_str: str) -> str:
    if not path:
        return "ERROR: empty path"
    fp = Path(path)

    if old_str == "":
        if fp.exists():
            return f"ERROR: file already exists — old_str='' só cria arquivos novos: {path}"
        try:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(new_str, encoding="utf-8")
            return f"OK: arquivo criado ({len(new_str)} bytes) — {path}"
        except Exception as e:
            return f"ERROR: {e}"

    if not fp.exists():
        return f"ERROR: file not found: {path} (use old_str='' para criar)"

    try:
        content = fp.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return f"ERROR: {e}"

    count = content.count(old_str)
    if count == 0:
        return "ERROR: old_str não encontrado. Faça read_file novamente e copie o texto EXATO."
    if count > 1:
        return f"ERROR: old_str aparece {count}x — não é único. Adicione mais contexto ao redor."

    new_content = content.replace(old_str, new_str, 1)
    try:
        fp.write_text(new_content, encoding="utf-8")
    except Exception as e:
        return f"ERROR: {e}"
    return f"OK: 1 substituição em {path} ({len(new_content)} bytes)"


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
        print(f"  ⚠  Comando: {cmd}")
        try:
            ans = input("  Permitir? [y/N] ").strip().lower()
        except EOFError:
            return "ERROR: approval denied (EOF)"
        if ans not in ("y", "yes", "s", "sim"):
            return "ERROR: command denied by user"

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


def _execute_tool_call(name: str, args: dict[str, Any], approve: bool = False) -> str:
    """Dispatcher único — só existem 3 ferramentas possíveis."""
    if name == "read_file":
        return _tool_read_file(
            args.get("path", ""),
            args.get("start_line"),
            args.get("end_line"),
        )
    if name == "str_replace":
        return _tool_str_replace(
            args.get("path", ""),
            args.get("old_str", ""),
            args.get("new_str", ""),
        )
    if name == "execute_shell":
        return _tool_execute_shell(args.get("cmd", ""), approve)
    return f"ERROR: unknown tool '{name}' (disponíveis: read_file, str_replace, execute_shell)"


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
# REPL principal
# ---------------------------------------------------------------------------

def dev_repl(project_root: str | None = None, approve: bool = False) -> None:
    if project_root:
        os.environ["JARVIS_PROJECT_ROOT"] = project_root
        os.chdir(project_root)

    profile = _detect_profile()
    tools = _get_tools() if profile["native_tools"] else []

    mode = "function-calling nativo" if profile["native_tools"] else "blocos de texto (Aider-style)"
    print(f"🤖 JARVIS Dev — SLM: {profile['name']} (max_tokens={profile['max_tokens']})")
    print(f"📁 Projeto: {os.getcwd()}")
    print(f"🔧 Ferramentas: read_file, str_replace, execute_shell — modo: {mode}")
    print("   Comandos: /quit, /status, /clear, /map, /model, /recall, /architect, /debug, /help\n")

    repo_map = _build_repo_map(os.getcwd())
    memory_ctx = _build_memory_context()
    system_prompt = _maybe_disable_thinking(
        SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx)
    )

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]

    active_model = profile["name"]
    debug_mode = False

    while True:
        try:
            user_input = input("👤 Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Até logo!")
            break

        if not user_input:
            continue

        if user_input == "/quit":
            print("👋 Até logo!")
            break
        if user_input == "/clear":
            repo_map = _build_repo_map(os.getcwd())
            memory_ctx = _build_memory_context()
            system_prompt = _maybe_disable_thinking(
                SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx)
            )
            messages = [{"role": "system", "content": system_prompt}]
            print("🗑️  Contexto limpo.")
            continue
        if user_input == "/debug":
            debug_mode = not debug_mode
            print(f"🐞 Debug {'ATIVADO' if debug_mode else 'desativado'} — mostra request/response cru da API")
            continue
        if user_input == "/status":
            from jarvis.core.health_monitor import BackendHealthMonitor
            cfg = _get_config()
            monitor = BackendHealthMonitor(cfg.llm_base_url.replace("/v1", ""))
            status = monitor.status_dict()
            print(f"  Backend: {status['state']} ({status['latency_ms']}ms)")
            print(f"  Model: {active_model}")
            print(f"  Modo de ferramentas: {mode}")
            print(f"  Mensagens no histórico: {len(messages)}")
            print(f"  Uptime: {status['uptime_pct']}%")
            continue
        if user_input == "/map":
            repo_map = _build_repo_map(os.getcwd())
            memory_ctx = _build_memory_context()
            system_prompt = _maybe_disable_thinking(
                SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx)
            )
            messages[0] = {"role": "system", "content": system_prompt}
            print("🗺️  Repo map + memória atualizados.")
            continue
        if user_input == "/model":
            print(f"  Modelo atual: {active_model}")
            print(f"  Modo de ferramentas: {mode}")
            print("  Para trocar, edite models.nix e faça rebuild")
            continue
        if user_input == "/recall":
            try:
                from jarvis.core.memory import EpisodicMemory
                cfg = _get_config()
                mem = EpisodicMemory(cfg)
                results = mem.recall(user_input if len(user_input) > 8 else "dev", top_k=3)
                if results:
                    for r in results:
                        print(f"  [{r.get('kind', '?')}] {r.get('text', '')[:100]}")
                else:
                    print("  Nenhuma memória encontrada.")
            except Exception as e:
                print(f"  Erro: {e}")
            continue
        if user_input == "/help":
            print("  /quit      — sair")
            print("  /clear     — limpar contexto")
            print("  /status    — status do backend")
            print("  /map       — atualizar repo map + memória")
            print("  /model     — ver modelo atual")
            print("  /recall    — buscar memória episódica")
            print("  /architect — modo architect (plan + execute)")
            print("  /debug     — mostra request/response cru da API")
            print("  /help      — esta ajuda")
            continue
        if user_input == "/architect":
            task_input = input("📋 Tarefa para architect: ").strip()
            if task_input:
                try:
                    plan = _architect_plan(task_input, profile, tools, debug_mode)
                    if plan:
                        print(f"📋 Plano:\n{plan}")
                        exec_input = input("\nExecutar? [Y/n] ").strip().lower()
                        if exec_input != "n":
                            messages.append({"role": "user", "content": task_input})
                            messages.append({"role": "assistant", "content": f"Plano: {plan}"})
                            messages.append({"role": "user", "content": "Execute este plano. Use as ferramentas disponíveis."})
                    else:
                        print("⚠️  Não foi possível gerar plano.")
                except Exception as e:
                    print(f"❌ Erro: {e}")
            continue

        messages.append({"role": "user", "content": user_input})
        messages = _trim_messages(messages)

        for turn in range(8):
            print(f"  🤔 Pensando... (turno {turn + 1})", end="", flush=True)

            try:
                data = _call_llm(messages, tools, profile, debug=debug_mode)
            except Exception as e:
                print(f"\n  ❌ Erro LLM: {e}")
                break

            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            tool_calls = message.get("tool_calls")

            if not tool_calls and content:
                tool_calls = _to_tool_calls(_parse_text_actions(content))
                print(" (recuperado via parser de texto)" if tool_calls else "")
            else:
                print()

            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or None}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            messages.append(assistant_msg)

            if not tool_calls:
                if content:
                    print(f"🤖 JARVIS: {content}")
                break

            for tc in tool_calls:
                func_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                preview_arg = str(args.get("path", args.get("cmd", "")))[:50]
                print(f"  🔧 {func_name}({preview_arg})")
                output = _execute_tool_call(func_name, args, approve)

                icon = "⚠️ " if output.startswith("ERROR") else "✅"
                preview = output if len(output) <= 120 else f"{output[:120]}…"
                print(f"  {icon} {preview}")

                tool_call_id = tc.get("id") or "call_fallback_0"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": output[:5000],
                })


def _architect_plan(task: str, profile: dict, tools: list, debug: bool = False) -> str | None:
    repo_map = _build_repo_map(os.getcwd())
    plan_prompt = _maybe_disable_thinking(PLAN_PROMPT.format(repo_map=repo_map))
    plan_messages: list[dict[str, Any]] = [
        {"role": "system", "content": plan_prompt},
        {"role": "user", "content": task},
    ]
    try:
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
                result = _execute_tool_call(fn, a)
                tool_id = tc.get("id") or "call_plan_0"
                plan_messages.append({"role": "assistant", "content": None, "tool_calls": [tc]})
                plan_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result[:2000],
                })

        plan_messages.append({"role": "user", "content": "Agora retorne o plano em JSON, campo 'plan'."})
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
        print(f"⚠️  Erro no plano: {e}")
        return None


def dev_once(task: str, project_root: str | None = None, approve: bool = False, debug: bool = False) -> int:
    if project_root:
        os.environ["JARVIS_PROJECT_ROOT"] = project_root
        os.chdir(project_root)

    profile = _detect_profile()
    tools = _get_tools() if profile["native_tools"] else []

    print(f"🤖 JARVIS Dev — {profile['name']}")
    print(f"📋 Tarefa: {task}\n")

    repo_map = _build_repo_map(os.getcwd())
    memory_ctx = _build_memory_context(task)
    system_prompt = _maybe_disable_thinking(
        SYSTEM_PROMPT_TEMPLATE.format(repo_map=repo_map, memory_context=memory_ctx)
    )
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": task},
    ]

    for _ in range(10):
        try:
            data = _call_llm(messages, tools, profile, debug=debug)
        except Exception as e:
            print(f"❌ Erro LLM: {e}")
            return 1

        message = data["choices"][0]["message"]
        content = message.get("content") or ""
        tool_calls = message.get("tool_calls")

        if not tool_calls and content:
            tool_calls = _to_tool_calls(_parse_text_actions(content))

        assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or None}
        if tool_calls:
            assistant_msg["tool_calls"] = tool_calls
        messages.append(assistant_msg)

        if not tool_calls:
            if content:
                print(f"🤖 {content}")
            return 0

        for tc in tool_calls:
            func_name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            print(f"  🔧 {func_name}({str(args)[:60]})")
            output = _execute_tool_call(func_name, args, approve)
            print(f"  → {output[:200]}")

            tool_call_id = tc.get("id") or "call_fallback_0"
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": output[:5000],
            })

    print("⚠️  Máximo de turnos atingido")
    return 1
