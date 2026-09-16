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
from typing import Callable, Any

# Re-export from security.py for backward compatibility
from jarvis.core.security import command_allowed, has_chaining_operators, run_shell  # noqa: F401


def detect_profile(model_id: str) -> dict[str, Any]:
    """Detect model profile from model name. Used by tests and REPL.

    Primeiro o registry (tiers declarados em models.nix): um `jarvis-fast`
    de 4B recebe perfil small COM tools (param-count puro o jogaria em
    "tiny" sem tools — foi assim que o REPL anulou o fast tier inteiro).
    Fallback: regex de parâmetros (comportamento legado p/ ids fora do
    registry, ex.: cloud).
    """
    tier_profile = _registry_tier_profile(model_id)
    if tier_profile is not None:
        return tier_profile
    m = model_id.lower()

    # Extract total parameters from name
    total_b_match = re.search(r"(?<![a-z])(\d+(?:\.\d+)?)b(?!\w)", m)
    total_b = float(total_b_match.group(1)) if total_b_match else None

    if total_b is not None and total_b >= 30:
        return {"name": "large", "max_tokens": 768, "max_tokens_per_turn": 768, "temperature": 0.0, "tool_choice": "auto"}
    elif total_b is not None and total_b >= 7:
        return {"name": "small", "max_tokens": 1024, "max_tokens_per_turn": 1024, "temperature": 0.0, "tool_choice": "auto"}
    elif total_b is not None and total_b < 7:
        return {"name": "tiny", "max_tokens": 512, "max_tokens_per_turn": 512, "temperature": 0.0, "tool_choice": "none"}
    else:
        return {"name": "default", "max_tokens": 1024, "max_tokens_per_turn": 1024, "temperature": 0.0, "tool_choice": "auto"}


def _registry_tier_profile(model_id: str) -> dict[str, Any] | None:
    """Perfil por tier do registry (None = id fora do registry)."""
    try:
        from jarvis.core.model_registry import ModelRegistry
        entry = ModelRegistry.load().get(model_id)
    except Exception:
        return None
    base = {"max_tokens_per_turn": 1024, "temperature": 0.0, "tool_choice": "auto"}
    if entry.tier == "reasoning":
        return {"name": "large", "max_tokens": 768, **base}
    if entry.tier == "fast":
        return {"name": "small", "max_tokens": 1024, **base}
    if entry.tier == "speed":
        return {"name": "default", "max_tokens": 1024, **base}
    return None


def _normalize_tool_call(tc: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize a tool call to a standard format.
    
    Handles:
    - arguments as string (JSON) or dict
    - missing name
    - empty arguments
    - preserves non-dict arguments (lists, numbers)
    
    Raises:
        json.JSONDecodeError: If arguments is an invalid JSON string.
    """
    if not isinstance(tc, dict):
        return None
    
    name = tc.get("name") or tc.get("function", {}).get("name")
    if not name:
        return None
    
    # Get arguments
    args = tc.get("arguments") or tc.get("function", {}).get("arguments", {})
    
    # Parse string arguments
    if isinstance(args, str):
        if not args.strip():
            args = {}
        else:
            args = json.loads(args)  # Raises JSONDecodeError for invalid JSON
    
    # Preserve non-dict types (lists, numbers) - don't force to dict
    
    return {"name": name, "arguments": args}


def _extract_json_object(text: str) -> str | None:
    """Extract a balanced JSON object from text."""
    if not text:
        return None
    # Find first {
    start = text.find('{')
    if start < 0:
        return None
    # Count braces to find matching closing }
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if c == '\\' and in_string:
            escape = True
            continue
        if c == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                candidate = text[start:i+1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    return None
    return None


def extract_fallback_tool_call(text: str | None) -> dict[str, Any] | None:
    """Extract tool call from text when native tool calls fail.
    
    Supports:
    - <tool_call>...</tool_call> format
    - JSON in code blocks
    - Bare JSON inline
    
    Returns normalized tool call with arguments parsed.
    """
    if not text:
        return None
    
    result = None
    
    # Look for <tool_call> format
    match = re.search(r'<tool_call>({.*?})</tool_call>', text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    
    # Look for JSON in code blocks
    if result is None:
        match = re.search(r'```(?:json)?\s*({\s*"name"\s*:\s*"[^"]+"[^}]*})\s*```', text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
    
    # Look for bare JSON with name and arguments
    if result is None:
        match = re.search(r'\{\s*"name"\s*:\s*"[^"]+"\s*,\s*"arguments"\s*:', text)
        if match:
            start = text.rfind('{', 0, match.start() + 1)
            if start >= 0:
                depth = 0
                for i in range(start, len(text)):
                    if text[i] == '{':
                        depth += 1
                    elif text[i] == '}':
                        depth -= 1
                        if depth == 0:
                            try:
                                result = json.loads(text[start:i+1])
                            except json.JSONDecodeError:
                                pass
                            break
    
    # Normalize: parse string arguments
    if result is not None and isinstance(result.get("arguments"), str):
        args_str = result["arguments"]
        if args_str.strip():
            try:
                result["arguments"] = json.loads(args_str)
            except json.JSONDecodeError:
                pass  # Keep as string if invalid

    return result


def extract_fallback_tool_calls(text: str | None,
                                limit: int = 3) -> list[dict[str, Any]]:
    """Plural: modelos-ação (xLAM) emitem LISTAS de calls.

    `[{name,arguments}, ...]` (até `limit`) — cada elemento vira uma
    tool_call (base do paralelismo P1). Cai para singular quando não
    é lista. Elementos inválidos são descartados, nunca inventados.
    """
    if not text:
        return []
    stripped = text.strip()
    if stripped.startswith("["):
        try:
            arr = json.loads(stripped)
        except (json.JSONDecodeError, ValueError):
            arr = None
        if isinstance(arr, list):
            out = []
            for el in arr:
                if len(out) >= limit:
                    break
                if not isinstance(el, dict):
                    continue
                name = el.get("name")
                args = el.get("arguments", {})
                if not name or not isinstance(args, dict):
                    continue
                out.append({"name": name, "arguments": args})
            if out:
                return out
    single = extract_fallback_tool_call(text)
    return [single] if single else []

from jarvis.core.logging import get_logger
from jarvis.core.user_profile import UserProfile, inject_context
from jarvis.core.loop_detector import LoopDetector, RecoveryAction
from jarvis.core.context_budget import ContextBudget
from jarvis.core.validator import ToolValidator

from jarvis.core.config import Config, get_config
from jarvis.providers.mcp import MCPClient, MCPError, parse_command, to_function_tools

# ---------------------------------------------------------------------------
# Constantes (espelho do pi.nix, parametrizadas via Config/env)
# ---------------------------------------------------------------------------

# Disciplina de tool-use injetada no system prompt (Agent + REPL).
# Evidência (A/B n=5, 7 tarefas, Bonsai): bare-free 30/35 com 0/5 em
# `echo hello` (no-call); COM este bloco 35/35; grammar-constrained 35/35.
# Modelos pequenos não "sabem" o protocolo do harness sozinhos — dizer
# explicitamente fecha boa parte do gap p/ harnesses comerciais.
TOOL_USE_DISCIPLINE = """TOOL DISCIPLINE (mandatory):
- When the request needs an action, call EXACTLY ONE tool per turn: the one that directly performs it.
- read_file for reading files; execute_shell ONLY for explicit shell commands.
- NEVER invent filenames, paths, or results — only use what you observed.
- Path unknown? LOCATE first (list_directory/semantic_search) — never ask the user for the path before searching.
- A tool failed? Read the [validation] hint and try the suggested alternative — one miss is not a stop.
- Claiming a cause? Cite file:line you actually read this session.
- Two-step request? Do the FIRST step now; the rest in later turns.
- No suitable tool? Answer with text and call nothing."""

MAX_TURNS: int = int(os.environ.get("JARVIS_AGENT_MAX_TURNS", "8"))

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
TOOL_OUTPUT_MAX_CHARS: int = int(os.environ.get("JARVIS_TOOL_OUTPUT_MAX_CHARS", "8000"))

from jarvis.core.tool_patterns import CODEBLOCK_JSON_RE
from jarvis.core.tool_patterns import TOOL_CALL_TAG_RE

logger = get_logger(__name__)


@dataclass
class AgentResult:
    """Result of agent.run()."""
    commands_run: list[str] = field(default_factory=list)
    commands_denied: list[str] = field(default_factory=list)
    final_response: str = ""
    turns: int = 0
    # P0 — conclusão baseada em evidência (completion.py), nunca em afirmação.
    verified: bool = False
    verdict: str = "unknown"  # VERIFIED | UNVERIFIED | STUCK | FAILED
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    plan: str = ""


def human_approve(cmd: str) -> bool:
    """Ask user for approval. Stub — monkeypatchable in tests."""
    return False


class Agent:
    """
    Main agent class handling tool calling, execution, and safety checks.
    """

    def __init__(
        self,
        config: Config | None = None,
        approval_callback: Callable[[str], bool] | None = None,
        session: Any | None = None,
        memory: Any | None = None,
        audit_path: Path | None = None,
        mcp_servers: dict[str, str] | None = None,
        approve: bool = False,
        llm_client: Any | None = None,
        model_requirements: dict | None = None,
        strict_tools: bool = False,
        plan: bool | str | dict | None = None,
        persona_id: str | None = None,
    ):
        self.config = config or get_config()
        self.approval_callback = approval_callback
        self._session = session
        # strict_tools: tool-calls via grammar constrained (response_format
        # JSON) em vez do template jinja — 35/35 no A/B c/ Bonsai.
        self.strict_tools = strict_tools
        # plan: planejamento explícito antes de executar (P0.4).
        # True = self-plan (turno 0 pede plano numerado ao próprio modelo
        # e ancora no contexto); str/dict = {"planner_model": id} (roteia
        # via ensure_model p/ MoE/strong quando o servidor suporta —
        # verificado: MoE-plan→Qwen-exec fixou M1 em 3 turns).
        self.plan = plan
        # Requisitos de modelo p/ routing local (None = comportamento atual:
        # usa config.llm_model sem ensure). Ex.: {"capabilities": {"coding",
        # "tools"}, "tier": "fast"}.
        self.model_requirements = model_requirements
        # Persona ativa (None/"jarvis" = default histórico; "agent" = modo
        # voz/operador). Via registry — sem if/else de strings espalhados.
        self.persona_id = persona_id or "jarvis"
        if llm_client is None:
            from jarvis.providers.llm import LLMClient
            llm_client = LLMClient(self.config, session=session)
        self.llm = llm_client
        self.memory = memory
        self.approve = approve
        self.audit_path = audit_path
        self.mcp_servers = mcp_servers or {}
        self.logger = get_logger(__name__)
        
        # Initialize components
        # NOTE: sem CircuitBreaker próprio aqui — proteção contra backend
        # instável vive no LLMClient (breaker + classificação de erro). Um
        # segundo breaker no Agent contaria falhas em duplicata.
        self.loop_detector = LoopDetector()
        self.context_budget = ContextBudget()
        self.validator = ToolValidator()

        # State
        self._loop_warnings = 0  # consecutive loop-detector warnings before forced stop
        self.state_dir = Path(self.config.state_dir) if self.config.state_dir else Path.cwd() / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.audit_log_path = audit_path or (self.state_dir / "audit.jsonl")

    def _log_audit(self, command: str, exit_code: int | None, result: str, allowed: bool, approved: bool = False) -> None:
        """Append an entry to the audit trail JSONL file."""
        entry = {
            "timestamp": time.time(),
            "cmd": command,
            "command": command,
            "exit_code": exit_code,
            "result_truncated": result[:TOOL_OUTPUT_MAX_CHARS],
            "allowed": allowed,
            "approved": approved,
        }
        try:
            with open(self.audit_log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except IOError as e:
            self.logger.error(f"Failed to write audit log: {e}")

    def _finalize(self, result: "AgentResult",
                  messages: list[dict[str, Any]],
                  forced: str | None = None) -> None:
        """Veredito de conclusão baseado em evidência (P0.2).

        forced: STUCK | FAILED (abort/overflow) — ainda coleta evidence
        do que existe; nunca declara VERIFIED sem check passar.
        """
        from jarvis.core.completion import check_completion
        try:
            v = check_completion(messages)
        except Exception:
            v = None
        if forced in ("STUCK", "FAILED"):
            result.verdict = forced
            result.verified = False
        elif v is not None and v.status == "VERIFIED":
            result.verdict = "VERIFIED"
            result.verified = True
        else:
            result.verdict = "UNVERIFIED"
            result.verified = False
        if v is not None:
            result.evidence = v.evidence
            result.missing = v.missing
        self.logger.emit("agent_verdict", detail={
            "verdict": result.verdict,
            "evidence": len(result.evidence),
            "missing": result.missing[:3],
        })

    def run(self, prompt: str) -> AgentResult:
        """Run agent with a single prompt. Returns AgentResult."""
        result = AgentResult()
        self.logger.emit("agent_start", detail={"prompt": prompt[:100]})
        system_content = "You are JARVIS, an AI coding assistant."
        system_content += f"\n\n{TOOL_USE_DISCIPLINE}"

        # Persona (default jarvis; voz usa "agent"). Via registry.
        # H2: persona PERTURBA acurácia em tasks genéricas (classificação,
        # código). Só usar persona quando o domínio exige expertise
        # (áudio forense, auditoria especializada). Tasks de sistema/código
        # usam regras base (TOOL_USE_DISCIPLINE) que são mais eficazes.
        _joined = prompt.lower() if prompt else ""
        _task_is_domain_specific = any(
            k in _joined for k in ("forensic", "áudio", "auditoria",
                                    "specialist", "persona"))
        if not _task_is_domain_specific:
            _persona = None
        else:
            try:
                from jarvis.core.persona import PersonaRegistry
                _persona = PersonaRegistry().get(self.persona_id)
                if _persona is None:
                    _persona = PersonaRegistry().get("jarvis")
            except Exception:
                _persona = None
        if _persona and _persona.system_prompt_additions:
            system_content += f"\n\nPERSONA ATIVA: {_persona.name} ({_persona.role})\n{_persona.system_prompt_additions}"

        # Inject user profile
        try:
            from jarvis.core.user_profile import UserProfile, build_context_block
            profile = UserProfile()
            profile.load()
            profile_block = build_context_block(profile)
            if profile_block:
                system_content += f"\n\nUSER PREFERENCES:\n{profile_block}"
        except Exception:
            pass
        
        # Inject environment context
        try:
            import platform
            import os
            env_block = f"""ENVIRONMENT:
- OS: {platform.system()} {platform.release()}
- Python: {platform.python_version()}
- CWD: {os.getcwd()}
- User: {os.environ.get('USER', 'unknown')}"""
            system_content += f"\n\n{env_block}"
        except Exception:
            pass
        
        # Inject lessons from memory — qualificadas pelo PROMPT (não ""):
        # lessons("") embaralha por embedding vazio e injeta lições
        # irrelevantes; com o prompt, o recall retorna o que importa.
        if self.memory:
            try:
                lessons = self.memory.lessons(prompt, top_k=3)
                if lessons:
                    system_content += f"\n\nAVOID (past errors):{lessons}"
            except Exception:
                pass
        
        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

        # Routing local (model_requirements): seleciona pelo registry e
        # garante residência via router (ensure idempotente). Sem
        # requirements, nada muda (config.llm_model como antes).
        if self.model_requirements:
            self._ensure_routed_model()

        # P0.4: plano explícito ancorado antes do loop (self ou roteado).
        # Falha no plano nunca aborta o run (segue sem plano).
        if self.plan:
            try:
                _plan_text = self._draft_plan(prompt)
            except Exception:
                _plan_text = ""
            if _plan_text.strip():
                result.plan = _plan_text.strip()[:2000]
                messages.append({
                    "role": "user",
                    "content": "Siga EXATAMENTE este plano, um passo por vez:\n" + result.plan,
                })
                try:
                    self.logger.emit("agent_plan", detail={
                        "chars": len(result.plan)})
                except Exception:
                    pass

        # Anti-loop: fresh detector state per prompt
        self.loop_detector.reset()
        self._loop_warnings = 0

        # Context guard (FASE 13): budget fresco por prompt, semeado com o
        # n_ctx autodetectado do budget compartilhado (evita re-query /props
        # e estado vazado entre prompts). Para ao estourar em vez de queimar
        # turnos que o modelo não consegue mais usar.
        turn_budget = ContextBudget(max_tokens=self.context_budget.max_tokens)
        try:
            turn_budget.add_message(messages[0])
            turn_budget.add_message(messages[1])
        except Exception:
            pass

        # Limites lidos no runtime (não congelados no import): WebUI/CLI
        # podem ajustar JARVIS_AGENT_MAX_TURNS sem reiniciar o processo.
        try:
            max_turns = int(os.environ.get("JARVIS_AGENT_MAX_TURNS", str(MAX_TURNS)))
        except ValueError:
            max_turns = MAX_TURNS
        # P0.2: turnos de verificação (DONE sem evidência → continua).
        verify_turns = 0
        # P0.3: erro idêntico repetido (nome+args) → variar ou STUCK.
        error_seen: dict[str, int] = {}
        for turn in range(max_turns):
            result.turns += 1
            response = self._get_llm_response(messages)
            messages.append(response)
            try:
                turn_budget.add_message(response)
                turn_budget.record_llm_call()
            except Exception:
                pass

            # Context guard: overflow → responde com o que há e para.
            if turn_budget.is_overflow:
                note = "Context budget overflow — stopping to preserve answer quality."
                messages.append({"role": "system", "content": note})
                if not result.final_response:
                    for msg in reversed(messages):
                        if msg.get("role") == "assistant" and msg.get("content"):
                            result.final_response = msg["content"] + f"\n\n[{note}]"
                            break
                    else:
                        result.final_response = f"({note})"
                break
            
            # Extract tool calls
            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "")
            if not tool_calls:
                # Fallback em texto (singular ou lista — xLAM emite arrays;
                # o plural já cobre o singular).
                for _i, _fb in enumerate(extract_fallback_tool_calls(content)):
                    tool_calls.append({
                        "id": f"fb-{turn}-{_i}",
                        "type": "function",
                        "function": _fb,
                    })
                if not tool_calls:
                    # P0.2: texto afirmativo NÃO é DONE — verifica evidência.
                    # Sem evidência e com turnos restantes: continua (máx 2
                    # turnos de verificação) em vez de aceitar calado.
                    from jarvis.core.completion import check_completion
                    try:
                        _v = check_completion(messages)
                    except Exception:
                        _v = None
                    if (_v is not None and _v.status == "VERIFIED") or verify_turns >= 2:
                        result.final_response = content
                        self._finalize(result, messages)
                        break
                    verify_turns += 1
                    messages.append({
                        "role": "system",
                        "content": ("Conclusão sem evidência ainda: "
                                    + "; ".join(_v.missing[:3]) +
                                    ". Continue com a próxima ação concreta "
                                    "(não repita a última tool idêntica)."),
                    })
                    continue

            # Anti-loop: detect repeated/cyclic tool calls and inject a
            # recovery message. If the model ignores the warning twice in a
            # row, stop the loop instead of burning turns on the same call.
            strategy = self.loop_detector.check(tool_calls, content)
            if strategy.action in (RecoveryAction.ABORT, RecoveryAction.FORCE_ANSWER):
                messages.append({"role": "system", "content": strategy.message})
                self._finalize(result, messages, forced="STUCK")
                break
            if strategy.action != RecoveryAction.NONE:
                messages.append({"role": "system", "content": strategy.message})
                self._loop_warnings += 1
                if self._loop_warnings >= 2:
                    self._finalize(result, messages, forced="STUCK")
                    break
            else:
                self._loop_warnings = 0
            
            # Execute tools
            _stuck_abort = False
            # P1: batch paralelo quando o turno inteiro é reads puros (>1).
            # Qualquer shell/escrita/parse-error no lote → caminho serial.
            _pre: dict[int, str] = {}
            if len(tool_calls) > 1:
                _batch: list[tuple[str, dict[str, Any]]] | None = []
                for _tc in tool_calls:
                    _fn = _tc.get("function", _tc)
                    if not isinstance(_fn, dict):
                        _batch = None
                        break
                    try:
                        _ra = _fn.get("arguments", "{}")
                        _ag = json.loads(_ra) if isinstance(_ra, str) else _ra
                    except (json.JSONDecodeError, TypeError):
                        _batch = None
                        break
                    if not isinstance(_ag, dict) or _fn.get("name") != "read_file":
                        _batch = None
                        break
                    _batch.append((_fn.get("name", ""), _ag))
                if _batch is not None:
                    for _i, _r in enumerate(self._parallel_read_batch(_batch)):
                        _pre[_i] = _r
            for _i, tc in enumerate(tool_calls):
                func = tc.get("function", tc)
                if not isinstance(func, dict):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call-{turn}"),
                        "content": "ERROR: Malformed tool call structure",
                    })
                    continue
                name = func.get("name", "")
                try:
                    raw_args = func.get("arguments", "{}")
                    if isinstance(raw_args, str):
                        args = json.loads(raw_args)
                    else:
                        args = raw_args
                except (json.JSONDecodeError, TypeError):
                    args = {}
                if not isinstance(args, dict):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.get("id", f"call-{turn}"),
                        "content": "ERROR: Invalid tool arguments",
                    })
                    continue

                exit_code: int | None = None
                if _i in _pre:
                    tool_result = _pre[_i]
                elif name == "execute_shell":
                    cmd = args.get("cmd", "")
                    # Check if command is allowed
                    if command_allowed(cmd):
                        # Check chaining
                        if has_chaining_operators(cmd):
                            result.commands_denied.append(cmd)
                            tool_result = f"ERROR: Chaining operators not allowed: {cmd}"
                        else:
                            # Execute
                            try:
                                proc = run_shell(cmd)
                            except subprocess.TimeoutExpired:
                                # Timeout vira observation (não aborta o run):
                                # cai no fluxo normal abaixo (validator +
                                # messages.append) para o modelo ver o erro.
                                exit_code = -1
                                tool_result = f"ERROR: Command timed out after 60s: {cmd}"
                                result.commands_run.append(cmd)
                                self._log_audit(cmd, -1, tool_result, True)
                            else:
                                result.commands_run.append(cmd)
                                exit_code = proc.returncode
                                tool_result = (proc.stdout + proc.stderr).rstrip() + "\n[exit: %d]" % proc.returncode
                                self._log_audit(cmd, proc.returncode, tool_result, True)
                            # Auto-learn: record lesson on command failure
                            # (usa exit_code: no timeout não há proc).
                            if exit_code != 0 and self.memory:
                                try:
                                    self.memory.remember_lesson(
                                        task=f"shell: {cmd[:80]}",
                                        error_pattern=tool_result[:200],
                                        fix=f"Command '{cmd[:60]}' failed with exit code {exit_code}",
                                    )
                                except Exception:
                                    pass
                    else:
                        # Needs approval
                        if self.approve:
                            if human_approve(cmd):
                                try:
                                    proc = run_shell(cmd)
                                except subprocess.TimeoutExpired:
                                    exit_code = -1
                                    tool_result = f"ERROR: Command timed out after 60s: {cmd}"
                                    result.commands_run.append(cmd)
                                    self._log_audit(cmd, -1, tool_result, True)
                                else:
                                    result.commands_run.append(cmd)
                                    exit_code = proc.returncode
                                    tool_result = (proc.stdout + proc.stderr).rstrip() + "\n[exit: %d]" % proc.returncode
                                    self._log_audit(cmd, proc.returncode, tool_result, True)
                            else:
                                result.commands_denied.append(cmd)
                                tool_result = f"ERROR: Command denied by user: {cmd}"
                                self._log_audit(cmd, None, tool_result, False)
                        else:
                            result.commands_denied.append(cmd)
                            tool_result = f"ERROR: Command not allowed: {cmd}"
                            self._log_audit(cmd, None, tool_result, False)
                elif name == "read_file":
                    # Leitura read-only via implementação canônica (devtools).
                    # Sem aprovação: risco zero. Erros viram tool result.
                    tool_result = self._exec_read_file(args)
                elif name in ("book_search", "book_resume"):
                    # Livros: read-only como read_file (Qdrant + bookmark).
                    # Sem aprovação, sem escrita. Erros viram tool result.
                    tool_result = self._exec_book(name, args)
                elif name in ("write_file", "str_replace"):
                    # Escrita: jail de projeto + aprovação explícita.
                    # Sem approve: negação honesta (o modelo pede ao usuário
                    # em vez de improvisar redirect via shell).
                    if self.approve and human_approve(
                            f"{name} {args.get('path', '')}"):
                        tool_result = self._exec_write(name, args)
                        result.commands_run.append(f"{name} {args.get('path', '')}")
                        self._log_audit(f"{name} {args.get('path', '')}",
                                        0 if not tool_result.startswith("ERROR") else 1,
                                        tool_result, True)
                    else:
                        result.commands_denied.append(
                            f"{name} {args.get('path', '')}")
                        tool_result = (
                            f"ERROR: {name} needs approval "
                            f"(approve=True + human approval). "
                            f"Path stays inside project jail.")
                        self._log_audit(f"{name} {args.get('path', '')}",
                                        None, tool_result, False)
                else:
                    tool_result = f"ERROR: Unknown tool: {name}"

                # Post-execution validation (FASE 16): structured failure
                # feedback — padrões de erro, exit codes e hints NixOS que o
                # modelo nem sempre extrai sozinho do output cru.
                if self.validator is not None:
                    try:
                        vr = self.validator.validate(name, args, tool_result, exit_code)
                        if vr.warnings:
                            tool_result += "\n[validation: " + "; ".join(vr.warnings[:3]) + "]"
                    except Exception:
                        pass
                try:
                    turn_budget.record_tool_call()
                except Exception:
                    pass

                if _stuck_abort:
                    break

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", f"call-{turn}"),
                    "content": tool_result[:TOOL_OUTPUT_MAX_CHARS],
                })
                # P0.1/P0.3: passo observável + erro idêntico repetido.
                from jarvis.core.completion import classify_error
                _kind = classify_error(tool_result)
                _ok = _kind == "ok"
                result.steps.append({"turn": turn, "tool": name,
                                     "ok": _ok, "kind": _kind})
                try:
                    self.logger.emit("agent_step", detail={
                        "turn": turn, "tool": name, "ok": _ok, "kind": _kind})
                except Exception:
                    pass
                if not _ok:
                    _sig = f"{name}::{json.dumps(args, sort_keys=True, default=str)}"
                    error_seen[_sig] = error_seen.get(_sig, 0) + 1
                    if error_seen[_sig] == 2:
                        messages.append({
                            "role": "system",
                            "content": (f"A mesma chamada falhou 2x ({name}, "
                                        f"erro {_kind}). NÃO repita idêntica: "
                                        f"varie a abordagem (outra tool, outro "
                                        f"path, leia antes, ou conclua STUCK)."),
                        })
                    elif error_seen[_sig] >= 3:
                        self._finalize(result, messages, forced="STUCK")
                        _stuck_abort = True
                        break

            if _stuck_abort:
                if not result.final_response:
                    result.final_response = (
                        "STUCK: mesmo erro 3x seguidas (ver verdict.missing).")
                break

        # Get final response if not set
        if not result.final_response:
            for msg in reversed(messages):
                if msg.get("role") == "assistant" and msg.get("content"):
                    result.final_response = msg["content"]
                    break
        
        if result.verdict == "unknown":
            # Saídas sem veredito (overflow, max_turns): verifica o que há.
            self._finalize(result, messages)
        self.logger.emit("agent_done", detail={
            "turns": result.turns,
            "commands_run": len(result.commands_run),
            "final_length": len(result.final_response),
            "verdict": result.verdict,
            "verified": result.verified,
        })
        return result

    def _draft_plan(self, prompt: str) -> str:
        """Gera plano numerado antes de executar (P0.4).

        self: turno 0 com o próprio executor. routed: garante o modelo
        planejador via ensure_model e usa cliente temporário (restaura o
        executor depois). Falha no plano = segue sem plano (nunca aborta
        o run por isso).
        """
        instruction = (
            "Tarefa: " + prompt + "\nDevolva APENAS um plano numerado de "
            "passos concretos (localizar, ler, diagnosticar, editar, "
            "verificar). Sem executar nada, sem explicações extras.")
        planner = self.llm
        closer = None
        try:
            spec = self.plan
            planner_id = None
            if isinstance(spec, str):
                planner_id = spec
            elif isinstance(spec, dict):
                planner_id = spec.get("planner_model")
            if planner_id:
                from dataclasses import replace
                from jarvis.core.model_lifecycle import ensure_model
                from jarvis.providers.llm import LLMClient
                ensure_model(planner_id, base_url=self.config.llm_base_url)
                cfg = replace(self.config, llm_model=planner_id)
                planner = LLMClient(cfg, session=self._session)
                closer = planner
            if hasattr(planner, "chat"):
                resp = planner.chat(
                    [{"role": "user", "content": instruction}],
                    temperature=0.0, max_tokens=256)
                text = resp.content if hasattr(resp, "content") else resp
            else:
                text = ""
            return text if isinstance(text, str) else ""
        except Exception:
            return ""
        finally:
            try:
                if closer is not None and hasattr(closer, "close"):
                    closer.close()
            except Exception:
                pass

    def _ensure_routed_model(self) -> None:
        """Seleciona modelo pelo registry e garante residência (router).

        O campo `model` do payload passa a ser significativo: o router
        atende o preset pedido (antes, "default" era ignorado pelo servidor
        single-model). Falha de routing/ensure propaga — nunca fallback
        silencioso p/ modelo incapaz.
        """
        from dataclasses import replace
        from jarvis.core.model_lifecycle import ensure_model
        from jarvis.core.model_policy import select_model

        model_id, reason = select_model(self.model_requirements)
        report = ensure_model(model_id, base_url=self.config.llm_base_url)
        self.logger.emit("model_routed", detail={
            "requested": report.requested,
            "selected": report.selected,
            "switched": report.switched,
            "previous": report.previous,
            "startup_latency_s": round(report.startup_latency_s, 2),
            "reason": reason,
        })
        if model_id != self.config.llm_model:
            self.config = replace(self.config, llm_model=model_id)
            from jarvis.providers.llm import LLMClient
            self.llm = LLMClient(self.config, session=self._session)

    @staticmethod
    def _strict_extra(tools: list[dict[str, Any]]) -> dict[str, Any]:
        """response_format p/ tool-calls 100% parseáveis (grammar do server)."""
        names = [t.get("function", {}).get("name", "?") for t in tools]
        return {"response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "toolcall",
                "schema": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string", "enum": names},
                        "arguments": {"type": "object"},
                    },
                    "required": ["tool", "arguments"],
                    "additionalProperties": False,
                },
            },
        }}

    @staticmethod
    def _strict_signatures(tools: list[dict[str, Any]]) -> str:
        """Bloco de assinaturas p/ modo strict (A/B: sem isso o modelo
        adivinha nomes de args — ex.: 'file' em vez de 'path').

        Derivado dos schemas OpenAI já oferecidos (sem duplicar nada)."""
        lines = ["Available tools (respond with ONLY "
                 '{"tool": "<name>", "arguments": {...}}):']
        for t in tools:
            fn = t.get("function", {})
            props = (fn.get("parameters", {}) or {}).get("properties", {})
            req = (fn.get("parameters", {}) or {}).get("required", [])
            args = ", ".join(
                f"{k}{'' if k in req else '?'}"
                for k in props) or "no args"
            lines.append(f"- {fn.get('name', '?')}({args}): "
                         f"{fn.get('description', '')}")
        return "\n".join(lines)

    @staticmethod
    def _strict_to_response(resp: Any, tools: list[dict[str, Any]]) -> Any:
        """Converte content JSON em tool_calls (objeto OU lista).

        Listas (xLAM) viram múltiplas calls (cap 3, base do P1). Fora do
        set oferecido ou JSON inválido: mantém como texto (o loop decide;
        nunca inventa call).
        """
        from jarvis.providers.llm_backend import ChatResponse
        names = {t.get("function", {}).get("name") for t in tools}

        def _one(obj: Any, idx: int) -> dict[str, Any] | None:
            if not isinstance(obj, dict) or obj.get("tool") not in names:
                return None
            args = obj.get("arguments")
            if not isinstance(args, dict):
                return None
            return {
                "id": f"strict-{idx}", "type": "function",
                "function": {"name": obj["tool"],
                             "arguments": json.dumps(args)},
            }

        try:
            parsed = json.loads(resp.content or "")
        except (ValueError, TypeError, AttributeError):
            return resp
        objs = parsed if isinstance(parsed, list) else [parsed]
        calls = [c for i, o in enumerate(objs[:3])
                 if (c := _one(o, i)) is not None]
        if not calls:
            return resp
        return ChatResponse(content="", reasoning=resp.reasoning,
                            tool_calls=calls)

    @staticmethod
    def _exec_read_file(args: dict[str, Any]) -> str:
        """read_file canônico (puro: sem side effects fora do FS lido).

        Ponto único usado pelo caminho serial E pelo batch paralelo (P1):
        mesma semântica, mesma formatação, mesmos erros.
        """
        from jarvis.core.devtools import read_file as _canonical_read
        try:
            offset = int(args.get("offset", 0) or 0)
        except (TypeError, ValueError):
            offset = 0
        try:
            limit = int(args.get("limit", 200) or 200)
        except (TypeError, ValueError):
            limit = 200
        try:
            res = _canonical_read(str(args.get("path", "")), offset=offset, limit=limit)
        except Exception as e:
            return f"ERROR: read failed: {e}"
        if res.get("ok"):
            return f"# {res.get('path', '')} ({res.get('total_lines', 0)} linhas)\n{res.get('content', '')}"
        return f"ERROR: {res.get('error', 'read failed')}"

    @staticmethod
    def _exec_write(name: str, args: dict[str, Any]) -> str:
        """write_file/str_replace canônicos (devtools, project jail)."""
        from jarvis.core import devtools as _dt
        try:
            if name == "write_file":
                res = _dt.write_file(str(args.get("path", "")),
                                     str(args.get("content", "")))
            else:
                res = _dt.str_replace(str(args.get("path", "")),
                                      str(args.get("old", "")),
                                      str(args.get("new", "")))
        except Exception as e:
            return f"ERROR: write failed: {e}"
        if res.get("ok"):
            return f"ok: {name} {res.get('path', args.get('path', ''))}"
        return f"ERROR: {res.get('error', 'write failed')}"

    @staticmethod
    def _exec_book(name: str, args: dict[str, Any]) -> str:
        """book_search/book_resume (audiobook.py, read-only, sem aprovação)."""
        from jarvis.core import audiobook as _ab
        try:
            if name == "book_search":
                hits = _ab.search_books(str(args.get("query", "")),
                                        book=args.get("book") or None)
                if not hits:
                    return "no hits"
                lines = [f"- {h.get('book', '')} cap.{h.get('chapter')} "
                         f"({h.get('title', '')}) [{h.get('score', 0):.2f}]: "
                         f"{h.get('content', '')[:200]}" for h in hits[:5]]
                return "\n".join(lines)
            res = _ab.resume_book(book_name=args.get("book") or None,
                                  hint=str(args.get("hint", "")))
        except Exception as e:
            return f"ERROR: book failed: {e}"
        if res.get("ok"):
            return (f"book={res.get('book')} chapter={res.get('chapter')} "
                    f"position={res.get('position')} reason={res.get('reason')}"
                    + (f" snippet: {res.get('snippet', '')[:200]}"
                       if res.get("snippet") else ""))
        return f"ERROR: {res.get('error', 'book failed')}"

    @staticmethod
    def _parallel_read_batch(items: list[tuple[str, dict[str, Any]]]) -> list[str]:
        """Executa reads independentes em paralelo (P1).

        Regras: SÓ read_file (puro); max 3 workers; timeout 60s cada;
        exceção isolada vira ERROR (nunca derruba o lote); ORDEM
        determinística = ordem de entrada. Shell/escrita JAMAIS entram
        aqui (side effects não admitem reordenação).
        """
        from concurrent.futures import ThreadPoolExecutor
        import contextvars
        results: list[str] = [""] * len(items)
        # Contexto (project root, etc.) NÃO atravessa threads sozinho:
        # copia por item, senão reads resolvem no projeto errado.
        ctxs = [contextvars.copy_context() for _ in items]

        def _one(idx: int, args: dict[str, Any]) -> None:
            try:
                results[idx] = ctxs[idx].run(Agent._exec_read_file, args)
            except Exception as e:
                results[idx] = f"ERROR: parallel read failed: {e}"

        with ThreadPoolExecutor(max_workers=min(3, len(items))) as ex:
            futs = [ex.submit(_one, i, a) for i, (_, a) in enumerate(items)]
            for f in futs:
                try:
                    f.result(timeout=60)
                except Exception as e:
                    pass
        # Timeout sem resultado = erro honesto (slot preservado).
        return [r if r else "ERROR: parallel read timed out" for r in results]

    def _get_llm_response(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        """Get response from LLM via the canonical LLMClient abstraction.

        Previously this method did a raw `requests.post` to llama.cpp,
        bypassing `LLMClient`/backend (circuit breaker, telemetry, error
        classification, backend routing). Now it delegates to
        `LLMClient.chat_with_tools` and adapts `ChatResponse` to the
        OpenAI-style message dict the loop consumes.
        """
        # Profile-aware generation params (hardcoded 1024/0.0 ignored the
        # detected model profile and tool_choice strategy)
        profile = detect_profile(self.config.llm_model or "")
        # Tools expostas ao LLM. `read_file` é sempre oferecida (read-only,
        # risco zero, capacidade central — CASE 1: "leia o arquivo X" nunca
        # deve precisar de RAG). `execute_shell` + MCP exigem mcp_servers.
        # `write_file`/`str_replace` exigem aprovação (self.approve +
        # human_approve): escrita nunca é silenciosa, mas o jail de projeto
        # do devtools impede escape — sem elas o Agent não conclui nenhuma
        # tarefa de edição (observado: planner travou em redirect negado).
        tools: list[dict[str, Any]] = [{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file with line numbers. Use for exact known paths (no RAG needed).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path (absolute or relative to CWD)"},
                        "offset": {"type": "integer", "description": "Start line, 0-indexed (default 0)"},
                        "limit": {"type": "integer", "description": "Max lines (default 200)"},
                    },
                    "required": ["path"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Create/overwrite a file (project jail; needs approval). Use for new files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Destination path"},
                        "content": {"type": "string", "description": "Full content"},
                    },
                    "required": ["path", "content"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "str_replace",
                "description": "Exact string replacement in a file (project jail; needs approval). Use for edits.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old": {"type": "string", "description": "Exact text to find"},
                        "new": {"type": "string", "description": "Replacement"},
                    },
                    "required": ["path", "old", "new"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "book_search",
                "description": "Semantic search over indexed audiobooks (read-only). Use for 'where was the dragon part' questions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "What to find"},
                        "book": {"type": "string", "description": "Optional book filter"},
                    },
                    "required": ["query"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "book_resume",
                "description": "Where to continue reading: bookmark + recency + semantic hint (read-only). Empty hint returns the bookmark.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "book": {"type": "string", "description": "Optional book name"},
                        "hint": {"type": "string", "description": "Optional semantic hint"},
                    },
                    "required": [],
                },
            },
        }]
        if self.mcp_servers:
            tools.append({
                "type": "function",
                "function": {
                    "name": "execute_shell",
                    "description": "Execute a shell command.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "cmd": {"type": "string", "description": "Command to execute"}
                        },
                        "required": ["cmd"]
                    }
                }
            })
            # Add MCP tools
            for server_name, server_cmd in self.mcp_servers.items():
                tools.append({
                    "type": "function",
                    "function": {
                        "name": f"{server_name}_query",
                        "description": f"Query {server_name} MCP server",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "q": {"type": "string", "description": "Query"}
                            },
                            "required": ["q"]
                        }
                    }
                })
        # Strict: schema só nos turnos de chamada. Após observations
        # (role tool presente), o modelo precisa de texto livre p/ a
        # resposta final — schema em todo turno o impediria de concluir.
        need_call = self.strict_tools and not any(
            m.get("role") == "tool" for m in messages)
        if need_call:
            # Assinaturas no system (1x): sem elas o modelo adivinha nomes
            # de args. Modo constrained: content JSON vira tool_calls do
            # loop (A/B 35/35). Nome fora do set = texto.
            if messages and messages[0].get("role") == "system":
                sig = self._strict_signatures(tools)
                if "Available tools (respond with ONLY" not in messages[0].get("content", ""):
                    messages[0] = {**messages[0],
                                   "content": messages[0].get("content", "") + "\n\n" + sig}
        resp = self.llm.chat_with_tools(
            messages,
            tools=None if need_call else tools,
            temperature=profile["temperature"],
            max_tokens=profile["max_tokens"],
            extra=self._strict_extra(tools) if need_call else None,
        )
        if need_call:
            resp = self._strict_to_response(resp, tools)
        return {
            "role": "assistant",
            # Modelos thinking (MoE) podem voltar com content vazio e
            # reasoning preenchido — o loop precisa de algo observável
            # (mesmo fallback do vision: nunca content vazio silencioso).
            "content": resp.content or (
                f"[thinking]\n{resp.reasoning}" if resp.reasoning else ""),
            "tool_calls": resp.tool_calls or [],
        }
        
        # Fallback: raise not implemented
        raise NotImplementedError("LLM provider not configured")