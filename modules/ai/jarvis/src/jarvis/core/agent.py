"""Agente de tool calling do JARVIS — implementação própria, inspirada no
conceito de agentes terminais (ex: `earendil-works/pi`, empacotado pelo
`pi.nix` do lukasl-dev). NÃO usa o código do pi: o loop de tool calling é
escrito do zero para o nosso stack, com as três camadas de segurança que o
host precisa (o pi executa qualquer comando sem aprovação):

  1. **Allowlist** — comandos read-only (diagnóstico) sempre permitidos;
  2. **Aprovação** — qualquer comando fora da allowlist exige confirmação
     humana (stdin ou botões no Telegram) quando `--approve` é passado;
     sem `--approve`, é negado;
  3. **Audit trail** — toda execução (ou negação) vai para um JSONL no
     state_dir, com timestamp, comando, exit code e resultado truncado.

Extras do JARVIS: memória episódica (lição automática quando um comando
falha), cliente MCP próprio (mcp-nixos, anti-alucinação) e perfis adaptativos
por modelo.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from typing import Any

import requests

from jarvis.core.logging import get_logger
from jarvis.core.user_profile import UserProfile, inject_context
from jarvis.core.circuit_breaker import CircuitBreaker
from jarvis.core.loop_detector import LoopDetector, RecoveryAction
from jarvis.core.context_budget import ContextBudget
from jarvis.core.validator import ToolValidator

from jarvis.core.config import Config, get_config
from jarvis.providers.mcp import MCPClient, MCPError, parse_command, to_function_tools

# ---------------------------------------------------------------------------
# Constantes (espelho do pi.nix, parametrizadas via Config/env)
# ---------------------------------------------------------------------------

MAX_TURNS = int(os.environ.get("JARVIS_AGENT_MAX_TURNS", "8"))
MAX_REPAIR_RETRIES = int(os.environ.get("JARVIS_AGENT_MAX_REPAIR_RETRIES", "2"))

# Comandos read-only seguros — permitidos sem aprovação (diagnóstico/self-heal).
DEFAULT_ALLOWED_PREFIXES: tuple[str, ...] = (
    "ls", "cat", "head", "tail", "grep", "rg", "find", "wc",
    "df", "free", "ps", "pgrep", "ss", "ip", "uname", "uptime",
    "date", "echo", "hostname", "id", "whoami",
    "systemctl is-active", "systemctl status", "systemctl list-units",
    "journalctl", "nix flake check", "nix eval", "nix build --dry-run",
    "nixos-rebuild dry-build", "nixos-rebuild build",
)

# Limite de caracteres para output de tool — evita saturar o contexto do LLM.
# 8000 chars ≈ 2000 tokens, suficiente para a maioria dos comandos.
TOOL_OUTPUT_MAX_CHARS = int(os.environ.get("JARVIS_TOOL_OUTPUT_MAX_CHARS", "8000"))

from jarvis.core.tool_patterns import CODEBLOCK_JSON_RE
from jarvis.core.tool_patterns import TOOL_CALL_TAG_RE
from jarvis.core.vision import VISION_TOOL
from jarvis.core.devtools import DEV_TOOLS

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "execute_shell",
            "description": "Execute a shell command. Read-only commands run directly; commands with side effects require approval.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {
                        "type": "string",
                        "description": "Shell command to execute.",
                    }
                },
                "required": ["cmd"],
            },
        },
    },
    VISION_TOOL,
    *DEV_TOOLS,
]


# ---------------------------------------------------------------------------
# Auditoria
# ---------------------------------------------------------------------------


class AuditLog:
    """JSONL de auditoria: uma linha por execução/negação de tool."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path

    def _append(self, entry: dict[str, Any]) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record(self, *, cmd: str, allowed: bool, approved: bool, exit_code: int | None, output: str) -> None:
        self._append({
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "cmd": cmd,
            "allowed": allowed,
            "approved": approved,
            "exit_code": exit_code,
            "output_preview": output[:500],
        })


# ---------------------------------------------------------------------------
# Execução segura de comandos
# ---------------------------------------------------------------------------

# Operadores de encadeamento perigosos que permitem execução arbitrária.
# &&, ||, backticks, $() são bloqueados sempre.
# ; e | são permitidos quando o destino é seguro (pipes para head/tail/grep).
# Um SLM pode gerar "cat /etc/shadow; rm -rf /" — o prefix check passaria
# em "cat" mas o segundo comando seria executado.
_DANGEROUS_CHAINING = ("&&", "||", "`", "$(", "${", "\n")

# Comandos que podem aparecer após pipe (seguros, read-only)
_SAFE_PIPE_TARGETS = (
    "head", "tail", "grep", "rg", "wc", "sort", "uniq", "cut",
    "awk", "sed", "tr", "column", "jq", "ls", "cat",
)


def has_dangerous_operators(cmd: str) -> bool:
    """True se o comando contém operadores perigosos (&&, ||, backticks, etc.).

    Pipes (|) e ponto-e-vírgula (;) NÃO são bloqueados aqui — são
    validados separadamente para permitir comandos como:
      find ... -o ... | head -20
      ls dir/ | grep pattern
    """
    for pat in _DANGEROUS_CHAINING:
        if pat in cmd:
            return True
    return False


def _validate_pipes(cmd: str) -> bool:
    """Valida que pipes apontam apenas para comandos seguros.

    Permite: find ... | head, ls ... | grep, etc.
    Bloqueia: find ... | rm, ls ... | xargs rm, etc.
    """
    if "|" not in cmd:
        return True
    parts = cmd.split("|")
    for part in parts[1:]:
        part = part.strip()
        if not part:
            continue
        # Extrair primeiro token (comando)
        first_token = part.split()[0] if part.split() else ""
        # Remover redirects
        first_token = first_token.split(">")[0]
        if first_token and not any(first_token.startswith(p) for p in _SAFE_PIPE_TARGETS):
            return False
    return True


def has_chaining_operators(cmd: str) -> bool:
    """True se o comando contém operadores perigosos.

    Mantido para backward compatibility — usada internamente.
    Pipes e ; são validados separadamente.
    """
    return has_dangerous_operators(cmd)


def command_allowed(cmd: str, allowed_prefixes: tuple[str, ...] | None = None) -> bool:
    """True se o comando começa com um prefixo read-only da allowlist
    E não contém operadores perigosos.

    Pipes (|) e ; são permitidos quando:
    - O pipe aponta para um comando seguro (head, tail, grep, etc.)
    - Exemplo: find ... -o ... | head -20 → OK
    - Exemplo: ls | rm → BLOQUEADO
    """
    prefixes = allowed_prefixes or DEFAULT_ALLOWED_PREFIXES
    stripped = cmd.strip()
    if not stripped:
        return False
    if has_dangerous_operators(stripped):
        return False
    if not _validate_pipes(stripped):
        return False
    # Para comandos com pipes, verificar o comando base (antes do pipe)
    base_cmd = stripped.split("|")[0].strip()
    # Para comandos com ;, verificar cada parte
    for part in stripped.split(";"):
        part = part.strip()
        if not part:
            continue
        check_cmd = part.split("|")[0].strip()
        if not any(check_cmd.startswith(p) for p in prefixes):
            return False
    return True


def run_shell(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Executa via `shlex` (sem shell=True) — mais seguro e auditável."""
    argv = shlex.split(cmd)
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def human_approve(cmd: str, prompt: str = "Permitir execução? [y/N] ") -> bool:
    """Pede confirmação humana no stdin."""
    print(f"⚠  Comando com efeito: {cmd}")
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes", "s", "sim")


# ---------------------------------------------------------------------------
# Perfis adaptativos (7B na VM vs 32B bare-metal)
# ---------------------------------------------------------------------------


def detect_profile(model_id: str) -> dict[str, Any]:
    """Perfil adaptativo por tamanho de modelo.

    4B: max_tokens baixo (tool calls curtos, respostas diretas).
    7B: margem para raciocínio + tool call.
    32B+: tools complexos, respostas detalhadas.
    """
    m = model_id.lower()
    if "32b" in m or "30b" in m:
        return {
            "name": "large",
            "temperature": 0.0,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens_per_turn": 768,
        }
    if "7b" in m:
        return {
            "name": "small",
            "temperature": 0.0,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens_per_turn": 1024,
        }
    if "4b" in m or "3b" in m or "1b" in m:
        return {
            "name": "tiny",
            "temperature": 0.0,
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "max_tokens_per_turn": 512,
        }
    return {
        "name": "default",
        "temperature": 0.0,
        "tool_choice": "auto",
        "parallel_tool_calls": False,
        "max_tokens_per_turn": 1024,
    }


def _extract_json_object(text: str) -> str | None:
    """Extrai o primeiro objeto JSON balanceado de um texto.

    Percorre o texto procurando um `{` que inicie um objeto com
    `"name"` e `"arguments"` (shape de tool call) e faz o balanceamento
    de chaves/colchetes/strings para obter o JSON completo — inclusive
    com objetos aninhados dentro de `arguments`.
    """
    i = 0
    n = len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth_braces = 0
        depth_brackets = 0
        in_string = False
        escaped = False
        j = i
        while j < n:
            ch = text[j]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            else:
                if ch == '"':
                    in_string = True
                elif ch == "{":
                    depth_braces += 1
                elif ch == "}":
                    depth_braces -= 1
                    if depth_braces == 0:
                        candidate = text[i : j + 1]
                        if '"name"' in candidate and '"arguments"' in candidate:
                            return candidate
                        break
                elif ch == "[":
                    depth_brackets += 1
                elif ch == "]":
                    depth_brackets -= 1
            j += 1
        i = j + 1
    return None


def extract_fallback_tool_call(content: str | None) -> dict[str, Any] | None:
    """Recupera tool_call vazado como texto (formato nativo do Qwen)."""
    if not content:
        return None
    # 1) tag nativa <tool_call>{...}</tool_call>
    match = TOOL_CALL_TAG_RE.search(content)
    # 2) JSON em code block ```json {...} ```
    if not match:
        match = CODEBLOCK_JSON_RE.search(content)
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("name"):
            return _normalize_tool_call(parsed)
    # 3) JSON solto no texto (balanceamento de chaves)
    raw = _extract_json_object(content)
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict) and parsed.get("name"):
            return _normalize_tool_call(parsed)
    return None


def _normalize_tool_call(parsed: dict[str, Any]) -> dict[str, Any] | None:
    name = parsed.get("name")
    if not name:
        return None
    arguments = parsed.get("arguments", {})
    if isinstance(arguments, str):
        arguments = json.loads(arguments) if arguments.strip() else {}
    return {"name": name, "arguments": arguments}


def normalize_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]]:
    """Normaliza tool_calls vindas do modelo em formatos mistos.

    O servidor local pode devolver estruturas como:
      - [{"function": {...}}]
      - [{"name": "x", "arguments": {...}}]
      - strings JSON em `arguments`
      - listas vazias / tipos inválidos

    A normalização ignora entradas malformadas em vez de quebrar o loop do
    agente; qualquer item válido segue para execução normal.
    """
    if raw_tool_calls is None:
        return []
    if isinstance(raw_tool_calls, dict):
        raw_tool_calls = [raw_tool_calls]
    if not isinstance(raw_tool_calls, list):
        return []

    normalized: list[dict[str, Any]] = []
    for idx, entry in enumerate(raw_tool_calls):
        if not isinstance(entry, dict):
            continue

        function = entry.get("function") if isinstance(entry.get("function"), dict) else entry
        name = function.get("name") if isinstance(function, dict) else None
        if not isinstance(name, str) or not name.strip():
            continue

        arguments = function.get("arguments", {}) if isinstance(function, dict) else {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                arguments = {}
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, (dict, list)):
            arguments = {}

        normalized.append({
            "id": entry.get("id") or f"call-{idx}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments if isinstance(arguments, (dict, list)) else json.dumps(arguments),
            },
        })
    return normalized


# ---------------------------------------------------------------------------
# Loop do agente
# ---------------------------------------------------------------------------


@dataclass
class AgentResult:
    final_response: str = ""
    turns: int = 0
    commands_run: list[str] = field(default_factory=list)
    commands_denied: list[str] = field(default_factory=list)
    tools_called: list[dict[str, Any]] = field(default_factory=list)  # [{name, args_preview, elapsed_s}]
    total_input_tokens_approx: int = 0  # estimativa de tokens de entrada
    total_output_tokens_approx: int = 0  # estimativa de tokens de saída
    duplicate_tool_warnings: int = 0


class Agent:
    """Loop agente: chat + tools contra um servidor OpenAI-compatível.

    Tools disponíveis:
      - `execute_shell` (allowlist + aprovação + audit)
      - tools MCP read-only (ex: mcp-nixos via `mcp_servers`), que passam
        pelo mesmo audit trail.
    """

    def __init__(
        self,
        config: Config | None = None,
        *,
        approve: bool = False,
        allowed_prefixes: tuple[str, ...] | None = None,
        audit_path: Path | None = None,
        system_prompt: str | None = None,
        session: requests.Session | None = None,
        mcp_servers: dict[str, str] | None = None,
        memory: Any | None = None,
        approver: Callable[[str], bool] | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._cfg = config or Config()
        self._base = self._cfg.llm_base_url.rstrip("/")
        self._approve = approve
        # callable de aprovação — default: terminal (stdin); canais (Telegram)
        # injetam o deles (ex: botões inline)
        self._approver = approver or human_approve
        self._allowed = allowed_prefixes or DEFAULT_ALLOWED_PREFIXES
        self._audit = AuditLog(audit_path)
        self._session = session or requests.Session()
        self._mcp_servers = mcp_servers or {}
        self._memory = memory  # EpisodicMemory opcional (auto-aprendizado)
        self._mcp_clients: dict[str, MCPClient] = {}
        self._mcp_tools: list[dict[str, Any]] = []
        self._system_prompt = system_prompt or (
            "JARVIS, assistente de admin NixOS. Sempre responda em PT-BR. "
            "Respostas curtas e diretas. Use execute_shell para dados/ações. "
            "Comandos read-only rodam direto; comandos com efeito pedem aprovação."
        )
        # Perfil de usuario: preferências + contexto ambiental dinâmico
        self._user_profile = UserProfile()
        try:
            self._user_profile.load()
        except Exception:  # noqa: BLE001 — perfil é best-effort
            pass
        # Circuit breaker para fallback de inferência
        self._circuit_breaker = circuit_breaker

    # --- servidor ---

    def _model_id(self) -> str:
        try:
            resp = self._session.get(f"{self._base}/models", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            if data.get("data"):
                return data["data"][0].get("id", "")
        except (requests.RequestException, ValueError):
            pass
        return ""

    def _chat(self, messages: list[dict[str, Any]], profile: dict[str, Any]) -> dict[str, Any]:
        tools = list(TOOLS)
        if self._mcp_tools:
            tools.extend(to_function_tools(self._mcp_tools))
        payload: dict[str, Any] = {
            "model": self._model_id() or self._cfg.llm_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": profile["tool_choice"],
            "temperature": profile["temperature"],
            "max_tokens": profile["max_tokens_per_turn"],
            "parallel_tool_calls": profile["parallel_tool_calls"],
        }
        # NOTA: response_format: json_object REMOVIDO quando tool_choice está ativo.
        # Conflito: forçar JSON content + tool_choice auto confunde o modelo —
        # ele pode tentar serializar tool_calls como JSON content em vez de usar
        # o campo tool_calls separado. O repair loop já lida com tool_calls
        # vazados como texto (3 camadas de extração).
        # json_object só é útil quando NÃO há tools (ex: rotas sem tool calling).
        # Qwen3 (e Qwen3.6) ativam thinking por padrão via chat template;
        # em CPU (lab) isso dobra a latência e consome max_tokens em
        # reasoning antes do tool call. Desligado via Config (env).
        if self._cfg.llm_disable_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        resp = self._session.post(f"{self._base}/chat/completions", json=payload, timeout=self._cfg.llm_timeout)
        resp.raise_for_status()
        return resp.json()

    def _chat_raw(self, messages: list[dict[str, Any]], profile: dict[str, Any]) -> str:
        """Chat que retorna apenas o conteúdo (para circuit breaker)."""
        data = self._chat(messages, profile)
        return data["choices"][0]["message"]["content"] or ""

    # --- MCP ---

    def _connect_mcp(self) -> None:
        """Inicia os clientes MCP configurados e descobre as tools."""
        for name, cmdline in self._mcp_servers.items():
            if name in self._mcp_clients:
                continue
            command, args = parse_command(cmdline)
            client = MCPClient(command, args, name="jarvis-agent")
            try:
                client.start()
                tools = client.list_tools()
            except (MCPError, OSError) as exc:
                # MCP indisponível nunca derruba o agente: segue sem as tools
                print(f"[agent] MCP '{name}' indisponível: {exc}", file=sys.stderr)
                client.close()
                continue
            self._mcp_clients[name] = client
            self._mcp_tools.extend(tools)

    def _call_mcp_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Executa uma tool MCP no cliente dono dela. Retorna texto."""
        for client in self._mcp_clients.values():
            try:
                return client.call_tool(name, arguments)
            except MCPError as exc:
                if "tool" not in str(exc):
                    continue
                return f"ERROR: {exc}"
        return f"ERROR: tool MCP desconhecida: {name}"

    def _close_mcp(self) -> None:
        for client in self._mcp_clients.values():
            client.close()
        self._mcp_clients.clear()
        self._mcp_tools = []

    def _valid_tool_names(self) -> set[str]:
        """Conjunto de nomes de tools aceitos — execute_shell + MCP + dev tools."""
        from jarvis.core.devtools import DEV_TOOLS as _DEV
        names = {"execute_shell"}
        for t in self._mcp_tools:
            if isinstance(t, dict) and "name" in t:
                names.add(t["name"])
        for t in _DEV:
            names.add(t["function"]["name"])
        return names

    # --- tool ---

    def _execute_tool(self, cmd: str, result: AgentResult) -> str:
        # Validação de entrada — rejeita cmd vazio/malformado
        if not cmd or not cmd.strip():
            return "ERROR: empty command"
        allowed = command_allowed(cmd, self._allowed)
        approved = False
        if not allowed:
            if not self._approve:
                result.commands_denied.append(cmd)
                self._audit.record(cmd=cmd, allowed=False, approved=False, exit_code=None, output="")
                return (
                    f"ERROR: command not in allowlist and approval is disabled "
                    f"(run with --approve to allow human confirmation). "
                    f"Command was: {cmd}"
                )
            if not self._approver(cmd):
                result.commands_denied.append(cmd)
                self._audit.record(cmd=cmd, allowed=False, approved=False, exit_code=None, output="")
                return f"ERROR: command denied by human. Command was: {cmd}"
            approved = True

        result.commands_run.append(cmd)
        log = get_logger("agent")
        t0 = time.time()
        try:
            res = run_shell(cmd, timeout=120)
            elapsed = round(time.time() - t0, 2)
            output = res.stdout if res.returncode == 0 else res.stderr
            if not output.strip():
                output = f"Command executed with exit code {res.returncode}"
            # Trunca output para não saturar o contexto do LLM
            if len(output) > TOOL_OUTPUT_MAX_CHARS:
                output = output[:TOOL_OUTPUT_MAX_CHARS] + f"\n... [truncated, {len(res.stdout)} chars total]"
            self._audit.record(cmd=cmd, allowed=allowed, approved=approved, exit_code=res.returncode, output=output)
            log.info("tool_call", detail={
                "cmd": cmd, "exit_code": res.returncode,
                "allowed": allowed, "approved": approved,
                "elapsed_s": elapsed, "output_len": len(output),
            })
            # auto-aprendizado: comando falhou → grava lição na memória episódica
            if res.returncode != 0 and self._memory is not None:
                self._learn(cmd, output)
            return output
        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - t0, 2)
            self._audit.record(cmd=cmd, allowed=allowed, approved=approved, exit_code=None, output="[timeout]")
            log.warn("tool_timeout", detail={"cmd": cmd, "elapsed_s": elapsed})
            if self._memory is not None:
                self._learn(cmd, "timeout after 120s")
            return "ERROR: command timed out after 120s."
        except Exception as exc:  # noqa: BLE001 — falha vira mensagem p/ o modelo
            elapsed = round(time.time() - t0, 2)
            self._audit.record(cmd=cmd, allowed=allowed, approved=approved, exit_code=None, output=str(exc))
            log.error("tool_error", detail={"cmd": cmd, "error": str(exc), "elapsed_s": elapsed})
            if self._memory is not None:
                self._learn(cmd, str(exc))
            return f"ERROR: {exc}"

    def _learn(self, cmd: str, error_output: str) -> None:
        """Grava uma lição episódica quando um comando falha (experience_buffer)."""
        try:
            self._memory.remember_lesson(
                task=f"agent shell: {cmd}",
                error_pattern=error_output[:200],
                fix="",  # o modelo descobre a correção; lição registra o erro
            )
        except Exception:  # noqa: BLE001 — memória nunca deve quebrar o agente
            pass

    # --- loop principal ---

    def run(self, user_prompt: str) -> AgentResult:
        log = get_logger("agent")
        log.info("agent_start", detail={"prompt": user_prompt[:200]})
        result = AgentResult()
        t0 = time.time()
        self._connect_mcp()
        try:
            r = self._run_loop(user_prompt, result)
            elapsed = round(time.time() - t0, 2)
            log.info("agent_done", detail={
                "turns": r.turns, "elapsed_s": elapsed,
                "commands_run": len(r.commands_run),
                "commands_denied": len(r.commands_denied),
                "tools_called": len(r.tools_called),
                "duplicate_warnings": r.duplicate_tool_warnings,
            })
            return r
        finally:
            self._close_mcp()

    def _lessons_block(self, user_prompt: str) -> str:
        """PAST LESSONS da memória episódica como restrições obrigatórias.

        Porta do cascade_planner do legado: o plano/agente deve respeitar
        lições de erros passados antes de agir ("MANDATORY CONSTRAINTS").
        Retorna vazio se não houver memória ou lições relevantes.
        """
        if self._memory is None:
            return ""
        try:
            return self._memory.lessons(user_prompt, top_k=3)
        except Exception:  # noqa: BLE001 — memória nunca deve quebrar o agente
            return ""

    def _run_loop(self, user_prompt: str, result: AgentResult) -> AgentResult:
        profile = detect_profile(self._model_id())
        lessons = self._lessons_block(user_prompt)
        # Injeta contexto adaptativo (perfil + tempo + sistema) no system prompt
        system = inject_context(self._system_prompt, self._user_profile)
        if lessons:
            system += "\n\nAVOID (past errors):" + lessons
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
        repair_attempts = 0
        last_tool_signature = ""  # para detectar chamadas duplicadas
        consecutive_duplicates = 0

        # ── Loop Detector + Context Budget + Validator (novos) ──
        loop_detector = LoopDetector()
        context_budget = ContextBudget(max_tokens=32000)
        validator = ToolValidator()
        for msg in messages:
            context_budget.add_message(msg)

        # O Qwen pequeno (7B) tende a continuar chamando tools mesmo com dados
        # suficientes. No penúltimo turno, injetamos um aviso de "responda já".
        for turn in range(MAX_TURNS):
            # ── Context budget warning ──
            budget_warning = context_budget.get_budget_warning()
            if budget_warning:
                messages.append({"role": "system", "content": budget_warning})
                context_budget.add_message(messages[-1])
                # Truncar tool outputs se overflow
                if context_budget.is_overflow:
                    context_budget.truncate_tool_outputs(aggressive=True)
                    saved = context_budget.compress_history()
                    log.info("context_compress", detail={"tokens_saved": saved})

            if turn == MAX_TURNS - 2 and messages:
                messages.append({
                    "role": "system",
                    "content": "Stop. Answer now with the data you have.",
                })
            result.turns = turn + 1
            # Circuit breaker: tenta local, fallback se disponível
            if self._circuit_breaker is not None:
                cb_result = self._circuit_breaker.execute(
                    messages, local_fn=lambda msgs: self._chat_raw(msgs, profile),
                )
                # O circuit breaker retorna apenas texto (não tool_calls).
                # Se o backend foi fallback ou rejected, o conteúdo é a resposta final.
                # Se foi local com erro, a resposta é a mensagem de erro.
                # Em todos os casos, tratamos como resposta sem tool calls.
                content = cb_result["response"]
                data = {"choices": [{"message": {"content": content, "tool_calls": None}}]}
            else:
                data = self._chat(messages, profile)
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            tool_calls = normalize_tool_calls(message.get("tool_calls"))

            recovered = False
            if not tool_calls:
                fallback = extract_fallback_tool_call(content)
                if fallback is not None:
                    tool_calls = [{
                        "id": "fallback-0",
                        "type": "function",
                        "function": {
                            "name": fallback["name"],
                            "arguments": json.dumps(fallback["arguments"]),
                        },
                    }]
                    recovered = True

            messages.append({
                "role": "assistant",
                "content": "" if (tool_calls and not recovered) else content,
                "tool_calls": tool_calls,
            })

            if not tool_calls:
                result.final_response = content
                return result

            for tool_call in tool_calls:
                func_name = tool_call["function"]["name"]
                raw_args = tool_call["function"]["arguments"]
                if isinstance(raw_args, (dict, list)):
                    args = raw_args
                elif not raw_args or not raw_args.strip():
                    args = {}
                else:
                    try:
                        args = json.loads(raw_args)
                    except json.JSONDecodeError:
                        repair_attempts += 1
                        if repair_attempts > MAX_REPAIR_RETRIES:
                            result.final_response = (
                                f"Erro: JSON de argumentos malformado após {MAX_REPAIR_RETRIES} tentativas: {raw_args}"
                            )
                            return result
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.get("id", ""),
                            "name": func_name,
                            "content": f"Invalid JSON. Retry with valid JSON: {raw_args[:200]}",
                        })
                        continue

                # Validação de nome de tool — rejeita tools que o modelo
                # hallucinou (não estão no TOOLS declarado nem no MCP).
                if func_name not in self._valid_tool_names():
                    output = f"ERROR: unknown tool '{func_name}'. Available: {sorted(self._valid_tool_names())}"
                    self._audit.record(
                        cmd=f"tool:{func_name}", allowed=False, approved=False,
                        exit_code=None, output=output,
                    )
                elif func_name == "execute_shell":
                    output = self._execute_tool(args.get("cmd", ""), result)
                elif func_name == "capture_screen":
                    from jarvis.core.vision import handle_capture
                    output = handle_capture(args)
                elif func_name in ("read_file", "write_file", "str_replace",
                                   "list_directory", "code_search", "run_tests",
                                   "semantic_search", "jarvis_command"):
                    from jarvis.core.devtools import handle_dev_tool, jarvis_command
                    if func_name == "jarvis_command":
                        res = jarvis_command(args.get("subcommand", "status"), args.get("args", ""))
                        output = res.get("output", res.get("error", "no output"))[:3000]
                    else:
                        output = handle_dev_tool(func_name, args)
                elif self._mcp_clients:
                    output = self._call_mcp_tool(func_name, args)
                else:
                    output = f"ERROR: tool '{func_name}' not available"

                # ── Validation: verificar resultado antes de passar ao modelo ──
                output = validator.enhance_tool_output(func_name, args, output)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.get("id", ""),
                    "name": func_name,
                    "content": output,
                })
                context_budget.add_message(messages[-1])

                # Métricas de observabilidade
                result.tools_called.append({
                    "name": func_name,
                    "args_preview": json.dumps(args, default=str)[:200],
                    "output_len": len(output),
                })

                # ── Loop Detector: verifica padrões de loop ──
                loop_strategy = loop_detector.check(tool_calls, content)
                if loop_strategy.action == RecoveryAction.ABORT:
                    result.final_response = (
                        f"Loop detectado ({loop_strategy.loop_type.value}): "
                        f"{loop_strategy.message}"
                    )
                    return result
                elif loop_strategy.action == RecoveryAction.FORCE_ANSWER:
                    messages.append({
                        "role": "system",
                        "content": loop_strategy.message,
                    })
                    context_budget.add_message(messages[-1])
                elif loop_strategy.action == RecoveryAction.INJECT_WARNING:
                    messages.append({
                        "role": "system",
                        "content": loop_strategy.message,
                    })
                    context_budget.add_message(messages[-1])
                    result.duplicate_tool_warnings += 1
                elif loop_strategy.action == RecoveryAction.CHANGE_STRATEGY:
                    messages.append({
                        "role": "system",
                        "content": loop_strategy.message,
                    })
                    context_budget.add_message(messages[-1])

        result.final_response = (
            f"Erro: número máximo de iterações ({MAX_TURNS}) atingido sem resposta final."
        )
        return result


def main_agent(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis agent [--approve] \"prompt\"."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis agent", description="Agente tool-calling JARVIS")
    parser.add_argument("prompt", help="o que o agente deve fazer")
    parser.add_argument("--approve", action="store_true", help="permite aprovação humana para comandos com efeito")
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    args = parser.parse_args(argv)

    cfg = get_config()
    state = cfg.ensure_state_dir()
    agent = Agent(cfg, approve=args.approve, audit_path=state / "agent-audit.jsonl")
    result = agent.run(args.prompt)

    print(result.final_response)
    if result.commands_run:
        print(f"\n# comandos executados ({len(result.commands_run)}):")
        for c in result.commands_run:
            print(f"  · {c}")
    if result.commands_denied:
        print(f"\n# comandos negados ({len(result.commands_denied)}):")
        for c in result.commands_denied:
            print(f"  · {c}")
    if result.commands_denied:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main_agent())
