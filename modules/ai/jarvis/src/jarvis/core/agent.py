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
from jarvis.core.security import command_allowed, echo_to_json, has_chaining_operators, run_shell, strip_redundant_chmod_run, suggest_synth_grammar, SYNTH_GRAMMARS  # noqa: F401


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
        # 2048 (exp. 18/09, alavanca B): 1024 truncava writes médios no
        # meio do JSON (L8: 3400 chars cortados); cap maior dá espaço ao
        # encadeamento operacional. Latência só cresce em resposta longa
        # (cap, não alvo). Temp segue 0.0 (determinismo de medição).
        return {"name": "small", "max_tokens": 2048, "max_tokens_per_turn": 2048, "temperature": 0.0, "tool_choice": "auto"}
    elif total_b is not None and total_b < 7:
        return {"name": "tiny", "max_tokens": 512, "max_tokens_per_turn": 512, "temperature": 0.0, "tool_choice": "none"}
    else:
        return {"name": "default", "max_tokens": 2048, "max_tokens_per_turn": 2048, "temperature": 0.0, "tool_choice": "auto"}


def _ctx_derived_max_tokens(ctx: Any) -> int:
    """Orçamento de geração por turno derivado do ctx do models.nix
    (dono 19/09: budget fixo 2048 truncava writes encadeados no L8; cap
    deve escalar com o ctx servido, não ser chutado à mão).
    Tudo em frações do ctx (test_context_drift proíbe literais de tamanho
    fora da fonte): turno = ctx//12 (~8% — sobra p/ prompt + histórico do
    ring em ~10 turns). Proporcional puro: ctx pequeno ganha budget
    pequeno (coerente — janela menor, menos folga). @49k → 4096.
    Sem ctx válido → 2048 (status quo ante).
    """
    try:
        ctx = int(ctx)
    except (TypeError, ValueError):
        return 2048
    if ctx <= 0:
        return 2048
    return max(1, ctx // 12)


def _registry_tier_profile(model_id: str) -> dict[str, Any] | None:
    """Perfil por tier do registry (None = id fora do registry)."""
    try:
        from jarvis.core.model_registry import ModelRegistry
        entry = ModelRegistry.load().get(model_id)
    except Exception:
        return None
    mt = _ctx_derived_max_tokens((entry.raw or {}).get("ctx"))
    base = {"max_tokens_per_turn": mt, "temperature": 0.0,
            "tool_choice": "auto"}
    if entry.tier == "reasoning":
        # 768 deliberado (resposta concisa p/ reasoning; ver detect_profile)
        return {"name": "large", "max_tokens": 768, **base}
    if entry.tier == "fast":
        return {"name": "small", "max_tokens": mt, **base}
    if entry.tier == "speed":
        return {"name": "default", "max_tokens": mt, **base}
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


def _synth_offered(bar_repeat, artifact_repeat, echo_banned) -> bool:
    """synthesize_command aparece no schema? Só pós-bar (progressive
    disclosure — L8g1: oferecida de cara virou distração)."""
    return bool(bar_repeat or artifact_repeat or echo_banned)


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

# Progressive disclosure de tools (Anthropic): book_* SÓ quando a task
# sinaliza livros/áudio. Oferta indiscriminada fez o modelo buscar
# "API keys" no índice de audiobooks 3x (sanitize real, book='nixos').
# Gate por keyword explícita (fail-open fora do run): fallback JSON
# continua despachando se o modelo realmente quiser. Só marcadores
# ESPECÍFICOS de livro/áudio: verbos genéricos ("leia", "ler", "ler
# logs") abriam as tools em task shell (L8 real: book_search numa task
# de intrusion detection) — custando turno + schema a troco de nada.
BOOK_TASK_HINTS = (
    "livro", "book", "capitulo", "capítulo", "chapter", "audiobook",
    "áudio", "audio", "ouvir", "narrador", "personagem", "hobbit",
)

# Disciplina de tool-use injetada no system prompt (Agent + REPL).
# Evidência (A/B n=5, 7 tarefas, Bonsai): bare-free 30/35 com 0/5 em
# `echo hello` (no-call); COM este bloco 35/35; grammar-constrained 35/35.
# Modelos pequenos não "sabem" o protocolo do harness sozinhos — dizer
# explicitamente fecha boa parte do gap p/ harnesses comerciais.
TOOL_USE_DISCIPLINE = """TOOL DISCIPLINE (mandatory):
- One turn = one intent: prefer ONE tool per turn; pure-read batches are one intent. Writes/shell: one per turn, in dependency order (write → chmod → run, never `&&`).
- read_file for reading files; execute_shell ONLY for explicit shell commands.
- NEVER invent filenames, paths, or results — only use what you observed.
- A task may cite ABSOLUTE container paths (e.g. /app/..., /root/...) that DON'T exist on this host. Before reading/writing any referenced file, list_directory CWD (and the referenced subdir, e.g. logs/ rules/) to find the REAL location — resolve to CWD-relative paths.
- A read/write that FAILS on a path is a signal the path is WRONG: list_directory CWD and relocate. NEVER retry writing the same fabricated content to the same failed path (observed: 3x re-write of 'Sample log content' to nonexistent /app/logs → STUCK).
- NEVER write fabricated/sample data for files you have not read. Files you must analyze (logs, csv, rules, json) live in CWD — READ them, do not synthesize.
- Path unknown? LOCATE first (list_directory/semantic_search) — never ask the user for the path before searching.
- Task is FIND something (keys, bugs, files)? SEARCH the whole scope first (grep -r PATTERN dir/ excluding .git, or semantic_search) — reading random files hoping to stumble on it is lottery. Read only what the search returns.
- A tool failed? Read the [validation] hint and try the suggested alternative — one miss is not a stop.
- Task asks to CREATE a file or folder? NEVER verify-then-read the target first: "not found" is the NORMAL state before creation. Call write_file directly with the FULL target path — it creates the file and all missing parent folders. mkdir is unnecessary.
- Claiming a cause? Cite file:line you actually read this session.
- Multi-step request? Do the steps in order until done.
- Task asks to WRITE a computed result? COMPUTE FIRST (create inputs, run), write the result AFTER — compute with python3 stdlib one-liner (csv/json/datetime), never awk/sed gymnastics for joins, dates or averages (pattern: write calc.py with `import csv`, skip header via `next(reader)`, parse dates per-format, compute, `print` ONLY the result, run `python3 calc.py`, THEN write_file with that exact output) — writing a placeholder value early leaves a stale artifact (observed: placeholder written before computing; never updated).
- Deliverables are SCRIPTS that generate files (not the files themselves)? SCRIPT FIRST, always in this shape — (1) write_file the .sh with the REAL logic over the inputs you just read (grep/parse/compute, CWD-relative paths); (2) execute_shell `chmod +x` it (one call); (3) execute_shell run it (`./name.sh`, one call); (4) read_file the GENERATED output to confirm. Hand-writing the generated files instead of running = fabrication (blocked + STUCK). The outputs only exist AFTER the run.
- Do NOT revisit a refuted pattern: once an approach failed and an alternative worked, never go back to the failed one (observed: model completed the correct chain then relapsed into mkdir+placeholder at the end).
- Task is to CLEAN/SANITIZE API keys or secrets? Call sanitize_secrets (one deterministic tool) — do NOT hand-edit str_replace per file.
- Task is to transform CSVs into a structured JSON per schema.json? Call build_json_dataset (deterministic) — do NOT hand-write the JSON.
- Output budget: each reply is CAPPED (~2k tokens) — anything beyond is CUT and LOST. Files >~100 lines MUST be split across turns (write part 1, then append the rest), never one giant call. A cut tool call is discarded, never executed.
- No suitable tool? Answer with text and call nothing."""

MAX_TURNS: int = int(os.environ.get("JARVIS_AGENT_MAX_TURNS", "8"))
# Orçamento wall-clock do run (19/09: run L8 travou numa call LLM stallada,
# sem traj, GPU pinada até aborto manual — max_turns não limita tempo).
# Estoura → STUCK honesto com motivo, sem travar o loop p/ sempre.
MAX_TIME_S: int = int(os.environ.get("JARVIS_AGENT_MAX_TIME_S", "600"))


def _data_task_prompt(prompt: str) -> bool:
    """Task de transformação de dados CSV->JSON (gate da tool determinística)."""
    _p = (prompt or "").lower()
    return all(k in _p for k in ("csv",)) and any(
        k in _p for k in ("json", "schema", "transform", "processa",
                          "transforma", "gerar", "estatística", "estatistica"))


def _secret_task_prompt(prompt: str) -> bool:
    """Task é limpeza de segredos? (gate do worked example de sanitize.)"""
    _p = (prompt or "").lower()
    return any(k in _p for k in (
        "chave", "token", "secret", "senha", "limpe", "sanitiz",
        "api key", "aws", "huggingface", "github",
    ))


def _secret_worked_example(messages: list[dict[str, Any]],
                           prompt: str) -> str | None:
    """Worked example (não prosa) p/ sanitize: quando o modelo trocou o
    NOME da chave e deixou o VALOR, mostra o old→new exato dos valores
    observados no grep. Só em task de segredo + se já houve tentativa."""
    if not _secret_task_prompt(prompt):
        return None
    # valores observados nas saídas de grep/read recentes
    import re as _re
    _vals = set()
    for _m in messages:
        if _m.get("role") != "tool":
            continue
        _c = str(_m.get("content", ""))
        for _v in _re.findall(
                r"AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{36}|hf_[A-Za-z0-9]{10,}",
                _c):
            _vals.add(_v)
    _name_replaced = False
    for _m in messages:
        for _tc in _m.get("tool_calls") or []:
            _fn = _tc.get("function", {})
            if not isinstance(_fn, dict) or _fn.get("name") != "str_replace":
                continue
            try:
                import json as _jl
                _ag = _fn.get("arguments", "{}")
                _ag = _jl.loads(_ag) if isinstance(_ag, str) else _ag
                _o = str(_ag.get("old", "")) if isinstance(_ag, dict) else ""
            except (ValueError, TypeError):
                _o = ""
            if _re.fullmatch(r"[A-Z][A-Z0-9_]*_[A-Z0-9_]+", _o):
                _name_replaced = True
                break
    if not _vals or not _name_replaced:
        return None
    _map = [
        ("AKIA", "<your-aws-access-key-id>"),
        ("ghp_", "<your-github-token>"),
        ("hf_", "<your-huggingface-token>"),
    ]
    _steps = []
    for _v in list(_vals)[:3]:
        for _pre, _ph in _map:
            if _v.startswith(_pre):
                _steps.append(f"'{_v}' -> '{_ph}'")
                break
    if not _steps:
        return None
    return ("WORKED EXAMPLE (faça isto, não troque o NOME da chave): "
            "os VALORES estão intactos; troque o VALOR por placeholder — "
            + "; ".join(_steps) + " (uma tool call por turno).")


def _partial_coverage_note(messages: list[dict[str, Any]], path: str) -> str | None:
    """Alvo editado além do trecho observado? (L4 real: leu 100 de 130+
    linhas e editou às cegas o resto.)

    Retorna nota ou None. Critério: último read_file bem-sucedido do path
    anuncia truncagem ("MAIS linhas") sem leitura complementar posterior.
    """
    if not path:
        return None
    try:
        import json as _jl

        def _rp(m: dict) -> str:
            for tc in m.get("tool_calls") or []:
                fn = tc.get("function", tc)
                if not isinstance(fn, dict):
                    continue
                if fn.get("name") != "read_file":
                    continue
                try:
                    a = fn.get("arguments", {})
                    a = _jl.loads(a) if isinstance(a, str) else a
                except (ValueError, TypeError):
                    continue
                if isinstance(a, dict) and str(a.get("path", "")) == path:
                    return "read"
            return ""

        _last = ""
        for i, m in enumerate(messages):
            if _rp(m):
                nxt = messages[i + 1] if i + 1 < len(messages) else {}
                if nxt.get("role") == "tool":
                    c = str(nxt.get("content", ""))
                    if c.strip().upper().startswith("ERROR"):
                        continue
                    _last = c
        if _last and "MAIS linhas" in _last:
            import re as _re3
            _mm = _re3.search(r"linhas\s+(\d+)\D+(\d+)\s+de\s+(\d+)", _last)
            _rng = f" ({_mm.group(0)})" if _mm else ""
            return (f"{path}: você leu PARCIAL{_rng} — edite SÓ o trecho "
                    f"observado ou complete a leitura (offset/limit) antes.")
    except Exception:
        pass
    return None


def _check_run_json_artifacts(since_ts: float) -> list[str]:
    """ finding .json criados/modificados no run que estão inválidos.

    L8v37: scripts geram alert/report inválidos EM RUNTIME — nenhum gate
    de write enxerga (só completion, no fim do run). Traz a evidência p/
    o momento da observação: após execute_shell, valida *.json do CWD
    tocados neste run (mtime > since_ts). Só top-level, só inválidos
    falam (válido = silêncio). Best-effort, nunca levanta.
    """
    import json as _j4
    from pathlib import Path as _P2
    notes: list[str] = []
    try:
        base = _P2.cwd()
        if not base.is_dir():
            return notes
        for _jf in sorted(base.glob("*.json")):
            try:
                if _jf.stat().st_mtime < since_ts:
                    continue
                if _jf.stat().st_size > 1_000_000:
                    continue
                _j4.loads(_jf.read_text(encoding="utf-8"))
            except OSError:
                continue
            except Exception as _e:
                notes.append(
                    f"[artifact-check: {_jf.name} is not valid JSON: "
                    f"{str(_e)[:120]}]")
    except Exception:
        pass
    return notes


def _missing_binary_hint(cmd: str) -> str:
    """ENOENT num path que EXISTE = shebang quebrado, não arquivo ausente.

    L8/L9 real (NixOS sem /bin/bash): `./script.sh` com `#!/bin/bash`
    falha com "No such file" MESMO com o arquivo lá — o kernel não acha
    o INTERPRETADOR. O OSError genérico mandava o modelo procurar o
    arquivo (que existe) em vez do shebang. Retorna sufixo ou "".
    """
    try:
        import shutil as _sh
        from pathlib import Path as _P
        _first = (cmd.split() or [""])[0].strip("\"'")
        if not _first or _first.startswith("-"):
            return ""
        _cand = _P(_first)
        if not _cand.is_absolute():
            _cand = _P(os.getcwd()) / _cand
        if not _cand.is_file():
            return ""
        _lines = _cand.read_text(encoding="utf-8", errors="replace").splitlines()
        if not _lines or not _lines[0].startswith("#!"):
            return ""
        _interp = _lines[0][2:].strip().split()[0]
        if not _interp:
            return ""
        if _sh.which(_interp) is None and _sh.which(_P(_interp).name) is None:
            return (f" O arquivo EXISTE — o shebang `{_lines[0]}` aponta "
                    f"p/ interpretador ausente (`{_interp}`, fora do PATH). "
                    "Rode via `bash <script>` ou troque o shebang "
                    "p/ `#!/bin/sh`.")
    except Exception:
        pass
    return ""


def _unexecuted_script_note(messages: list[dict[str, Any]]) -> str | None:
    """Script escrito (*.sh/*.py) mas nunca executado? (L8 real: ambos os
    scripts escritos, zero runs — victory declaration bias; Bhatt P3:
    teste direcionado no loop, não instrução genérica.)

    chmod NÃO conta como execução (só prepara). Retorna nota STATE uma
    vez por path (marcador evita spam).
    """
    written: list[str] = []
    try:
        for _m in messages:
            for _tc in _m.get("tool_calls") or []:
                _fn = _tc.get("function", _tc) if isinstance(_tc, dict) else None
                if not isinstance(_fn, dict):
                    continue
                if _fn.get("name") not in ("write_file", "str_replace"):
                    continue
                try:
                    _ag = _fn.get("arguments", "{}")
                    _ag = json.loads(_ag) if isinstance(_ag, str) else _ag
                except (ValueError, TypeError):
                    continue
                _p = str(_ag.get("path", "")) if isinstance(_ag, dict) else ""
                if _p.endswith((".sh", ".py")) and _p not in written:
                    written.append(_p)
        if not written:
            return None
        _blob = json.dumps(messages, default=str)
        pending = []
        for _p in written:
            _base = _p.rsplit("/", 1)[-1]
            _ran = False
            for _m in messages:
                for _tc in _m.get("tool_calls") or []:
                    _fn = _tc.get("function", _tc) if isinstance(_tc, dict) else None
                    if not isinstance(_fn, dict):
                        continue
                    if _fn.get("name") != "execute_shell":
                        continue
                    try:
                        _ag = _fn.get("arguments", "{}")
                        _ag = json.loads(_ag) if isinstance(_ag, str) else _ag
                    except (ValueError, TypeError):
                        continue
                    _cmd = str(_ag.get("cmd", "")) if isinstance(_ag, dict) else ""
                    if (f"./{_base}" in _cmd or re.search(
                            r"\b(python3?|bash|sh)\s+\S*" + re.escape(_base),
                            _cmd)):
                        _ran = True
                        break
                if _ran:
                    break
            if not _ran and f"unexecuted_script:{_base}" not in _blob:
                pending.append(_p)
        if not pending:
            return None
        return ("STATE(unexecuted_script:"
                + ",".join(p.rsplit("/", 1)[-1] for p in pending)
                + "). You WROTE but never RAN: "
                + ", ".join(pending)
                + ". NEXT: execute NOW (`chmod +x` then `./<script>`, "
                "one per call) and iterate on the error output. Zero prose.")
    except Exception:
        return None


def _unread_refs_note(messages: list[dict[str, Any]]) -> str | None:
    """Script escrito referencia arquivos nunca lidos? (L8 real: detector
    com `auth.log` errado + jq errado porque nunca leu logs/ nem rules/
    — escreveu às cegas. Bhatt P1 map-before-code, mecânico.)

    SÓ arquivos que EXISTEM no disco e nunca foram lidos com sucesso.
    v1 marcava também outputs-a-criar (alert.json) e lixo de variável
    shell (`$logs_dir/auth.log`) — mandou o modelo ler 8x arquivos
    inexistentes e queimou o budget (L8 real). Inexistente ≠ legível:
    outputs se CRIAM, não se leem.
    """
    try:
        read_ok: set[str] = set()
        for i, _m in enumerate(messages):
            for _tc in _m.get("tool_calls") or []:
                _fn = _tc.get("function", _tc) if isinstance(_tc, dict) else None
                if not isinstance(_fn, dict) or _fn.get("name") != "read_file":
                    continue
                try:
                    _ag = _fn.get("arguments", "{}")
                    _ag = json.loads(_ag) if isinstance(_ag, str) else _ag
                except (ValueError, TypeError):
                    continue
                _p = str(_ag.get("path", "")) if isinstance(_ag, dict) else ""
                if not _p:
                    continue
                _nxt = messages[i + 1] if i + 1 < len(messages) else {}
                if _nxt.get("role") == "tool" and not str(
                        _nxt.get("content", "")).strip().upper().startswith("ERROR"):
                    read_ok.add(_p)
                    read_ok.add(_p.rsplit("/", 1)[-1])
        if not read_ok:
            return None
        _blob = json.dumps(messages, default=str)
        _refs: list[str] = []
        for _m in messages:
            for _tc in _m.get("tool_calls") or []:
                _fn = _tc.get("function", _tc) if isinstance(_tc, dict) else None
                if not isinstance(_fn, dict):
                    continue
                if _fn.get("name") not in ("write_file", "str_replace"):
                    continue
                try:
                    _ag = _fn.get("arguments", "{}")
                    _ag = json.loads(_ag) if isinstance(_ag, str) else _ag
                except (ValueError, TypeError):
                    continue
                _content = str(_ag.get("content", "") or _ag.get("new", ""))
                _path = str(_ag.get("path", ""))
                if not _path.endswith((".sh", ".py")):
                    continue
                for _tok in re.findall(
                        r"(?:logs|rules|data)/[\w.\-/]+|[\w.\-/]+\.(?:log|json|csv|yaml)",
                        _content):
                    _t = _tok.strip("\"'`)")
                    if (_t in read_ok or _t.rsplit("/", 1)[-1] in read_ok
                            or _t in _refs
                            or f"unread_ref:{_t}" in _blob):
                        continue
                    # Existe no disco? Outputs-a-criar e lixo de variável
                    # shell não existem — mandar ler queima turnos (L8 real).
                    try:
                        from pathlib import Path as _P
                        _cand = _P(_t)
                        if not _cand.is_absolute():
                            _cand = _P(os.getcwd()) / _cand
                        if not _cand.is_file():
                            continue
                    except Exception:
                        continue
                    _refs.append(_t)
        if not _refs:
            return None
        return ("STATE(unread_refs:" + ",".join(_refs) + "). Your script "
                "references files you NEVER read: " + ", ".join(_refs) +
                ". NEXT: read_file EACH one first, then FIX the script "
                "paths/patterns from OBSERVED content (never guess). "
                "Zero prose.")
    except Exception:
        return None

def _placeholder_script_note(messages: list[dict[str, Any]]) -> str | None:
    """Script escrito é placeholder vazio? (L8 real: bonsai gerou .sh com
    `echo "Processing... (placeholder message)"` que executa com exit 0 mas
    não cria alert.json/report.json válidos; L8v15: mesmo padrão em .py com
    "placeholder for the actual logic" — harness precisa detectar DUMMY em
    ambas linguagens, não só unexecuted. Mecânico: marca placeholder sem
    saber a task; instrução de rewrite por linguagem.)"""
    try:
        from pathlib import Path as _P
        try:
            from jarvis.core.devtools import resolve_base as _rb
            _root = _rb()
        except Exception:
            _root = _P(".")
        # TODOS os .sh/.py escritos com sucesso no run (não só o último: L8
        # real — intrusion_detector.sh placeholder foi ofuscado por writes
        # posteriores no response.sh; L8v15 mostrou .py com placeholder
        # passando batido). Avalia o ARQUIVO NO DISCO (verdade atual;
        # fragmentos de str_replace diluem o sinal), com fallback p/
        # conteúdo da mensagem se ilegível.
        _written: dict[str, str] = {}
        for i, _m in enumerate(messages):
            for _tc in _m.get("tool_calls") or []:
                _fn = _tc.get("function", _tc) if isinstance(_tc, dict) else None
                if not isinstance(_fn, dict) or _fn.get("name") not in ("write_file", "str_replace"):
                    continue
                try:
                    _ag = _fn.get("arguments", "{}")
                    _ag = json.loads(_ag) if isinstance(_ag, str) else _ag
                except (ValueError, TypeError):
                    continue
                _p = str(_ag.get("path", "")) if isinstance(_ag, dict) else ""
                _c = str(_ag.get("content", "") or _ag.get("new", "")) if isinstance(_ag, dict) else ""
                if not _p.endswith((".sh", ".py")):
                    continue
                _nxt = messages[i + 1] if i + 1 < len(messages) else {}
                if _nxt.get("role") == "tool" and not str(_nxt.get("content", "")).strip().upper().startswith("ERROR"):
                    _written[_p] = _c
        if not _written:
            return None
        _dump = json.dumps(messages, default=str)
        for _last_path in _written:
            _base = _last_path.rsplit("/", 1)[-1]
            # Um aviso por path (evita spam; próximos turns pegam os demais)
            if f"placeholder_script:{_base}" in _dump:
                continue
            _fp = (_root / _last_path) if not _P(_last_path).is_absolute() else _P(_last_path)
            try:
                _last_content = _fp.read_text(encoding="utf-8") if _fp.is_file() else _written[_last_path]
            except OSError:
                _last_content = _written[_last_path]
            if not _last_content:
                continue
            low = _last_content.lower()
            # Sinais de dummy: placeholder literal, só echos, sem grep/jq/python real
            is_placeholder = (
                "placeholder" in low
                or ("processing logs" in low and "generating" in low and low.count("grep") == 0 and low.count("jq") == 0 and low.count("python") == 0)
                or (low.count("echo") >= 2 and low.count("grep") == 0 and low.count("jq") == 0 and len(low) < 800)
            )
            if not is_placeholder:
                continue
            if _base.endswith(".py"):
                _next = ("NEXT: IMPLEMENT the loop body with REAL working "
                         "code (no placeholder comments): open() the inputs, "
                         "for each rule count pattern matches per log line "
                         "(use `pattern in line` or re.search), collect "
                         "unique IPs, write outputs with json.dump. Then RUN "
                         "it (`python3 " + _base + "`) and read the outputs.")
            else:
                _next = ("NEXT: REWRITE it with REAL logic: read rules/detection_rules.json, grep -c each pattern in logs/auth.log+logs/http.log, extract unique IPs with grep -oE '[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+', build alert.json/report.json with python3 + json.dumps (stdlib, always valid) and timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ). Do NOT pipe grep text into jq (jq reads JSON files, not log lines). Zero prose, one tool call.")
            return (
                f"STATE(placeholder_script:{_base}). Your script {_base} is a PLACEHOLDER (dummy echos, no real logic — it exits 0 but creates no valid output). "
                + _next
            )
    except Exception:
        return None
    return None


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
    api_fallback: bool = False  # True se o resultado veio da cascata API
    api_model: str = ""  # "provider/model" usado no fallback (telemetria)
    # Trajetória completa (mensagens) p/ debug forense offline. Pode ser
    # grande — consumidores devem truncar antes de persistir.
    messages: list[dict[str, Any]] = field(default_factory=list)


def human_approve(cmd: str) -> bool:
    """Ask user for approval. Stub — monkeypatchable in tests."""
    return False


def _api_layer_for(prompt: str) -> str:
    """Camada da cascata pelo prompt (keywords; default dev)."""
    p = (prompt or "").lower()
    if any(k in p for k in ("classifi", "quem fala", "categoria")):
        return "classify"
    if any(k in p for k in ("document", "audit")):
        return "docs"
    if any(k in p for k in ("refactor", "refator", "massa de", "lote",
                             "batch")):
        return "batch"
    return "dev"


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

    @staticmethod
    def _repair_malformed_tool_args(
        response: dict[str, Any], turn: int,
    ) -> tuple[dict[str, Any], str]:
        """Separa tool_calls com arguments JSON inválido.

        L8 real (bonsai): modelo emite write_file gigante de uma vez,
        trunca no max_tokens e os args voltam JSON inválido. O servidor
        500a QUALQUER payload contendo a mensagem malformada — o run
        morria sem recovery. Repara ANTES de guardar no histórico: os
        calls inválidos são REMOVIDOS (nunca executados, nunca
        reenviados) e hint tipado orienta retentar menor.

        Returns (response_sanitizada, hint). Sem calls inválidos, hint
        é "" e response volta intacta.
        """
        tcs = response.get("tool_calls") or []
        if not tcs:
            return response, ""
        ok: list[dict[str, Any]] = []
        bad: list[str] = []
        for tc in tcs:
            fn = tc.get("function", tc) if isinstance(tc, dict) else None
            if isinstance(tc, dict):
                cid = tc.get("id", f"call-{turn}")
            else:
                cid = f"call-{turn}"
            if not isinstance(fn, dict):
                bad.append(cid)
                continue
            raw = fn.get("arguments", "{}")
            try:
                parsed = json.loads(raw) if isinstance(raw, str) else raw
                if not isinstance(parsed, dict):
                    raise ValueError("args não-dict")
            except (ValueError, TypeError):
                bad.append(cid)
                continue
            ok.append(tc)
        if not bad:
            return response, ""
        repaired = dict(response)
        repaired["tool_calls"] = ok
        hint = (
            f"STATE(malformed_tool_args:{','.join(bad)})."
            " Your last tool call had INVALID JSON arguments"
            " (truncated at the token limit?) — it was NOT executed."
            " NEXT: retry the SAME intent with SMALLER arguments:"
            " split big file writes into 2+ steps (write part 1, then"
            " append the rest via execute_shell heredoc), shorten"
            " commands. Entire reply must be ONE action, zero prose.")
        return repaired, hint

    def run(self, prompt: str) -> AgentResult:
        """Run agent with a single prompt. Returns AgentResult."""
        result = AgentResult()
        try:
            self._book_tools_offered = any(
                h in (prompt or "").lower() for h in BOOK_TASK_HINTS)
        except Exception:
            self._book_tools_offered = True
        try:
            self.validator.secret_task = _secret_task_prompt(prompt)
        except Exception:
            self.validator.secret_task = False
        self._secret_task_offered = _secret_task_prompt(prompt)
        self._data_task_offered = _data_task_prompt(prompt)
        self.logger.emit("agent_start", detail={"prompt": prompt[:100]})
        system_content = "You are JARVIS, an AI coding assistant."
        system_content += f"\n\n{TOOL_USE_DISCIPLINE}"
        if _secret_task_prompt(prompt):
            # Framing de tarefa (evita hijack do git-recovery e o loop
            # nome-vs-valor — L4 real: ia pro reflog/merge em vez de editar
            # os segredos nos arquivos de trabalho).
            system_content += ("\n\nTASK MODE: SECRET-SANITIZATION. "
                "Os segredos estão nos ARQUIVOS DE TRABALHO (não em commits/"
                "branches) — NÃO use git reflog/recovery/merge para isto. "
                "Faça: 1) grep -rlE 'AKIA|ghp_|hf_' . para achar os arquivos "
                "com VALORES; 2) edite cada VALOR por placeholder "
                "(str_replace value->placeholder), nunca o NOME da chave; "
                "3) confirme com grep que nenhum valor restou.")

        # Persona (default jarvis; voz usa "agent"). Via registry.
        # H2: persona AUTOMÁTICA (implícita) perturba acurácia em tasks
        # genéricas — só entra quando o domínio exige expertise. Mas persona
        # EXPLÍCITA (caller passou persona_id != default, ex: voice mode
        # "agent", marketing) é contrato do caller: injeta SEMPRE — o gate
        # antigo suprimia até persona explícita e quebrou test_persona.py
        # (2 failures no build Nix 16/09).
        _explicit_persona = self.persona_id not in (None, "", "jarvis")
        if _explicit_persona:
            try:
                from jarvis.core.persona import PersonaRegistry
                _persona = PersonaRegistry().get(self.persona_id)
                if _persona is None:
                    _persona = PersonaRegistry().get("jarvis")
            except Exception:
                _persona = None
        else:
            _joined = prompt.lower() if prompt else ""
            _task_is_domain_specific = any(
                k in _joined for k in ("forensic", "áudio", "auditoria",
                                        "specialist", "persona"))
            if _task_is_domain_specific:
                try:
                    from jarvis.core.persona import PersonaRegistry
                    _persona = PersonaRegistry().get(self.persona_id)
                    if _persona is None:
                        _persona = PersonaRegistry().get("jarvis")
                except Exception:
                    _persona = None
            else:
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

        # Framing RRP por modelo (catálogo 17/09): regras operacionais
        # curtas pelo comportamento conhecido do modelo em uso. Vazio =
        # sem framing (modelos locais sem nota). Persona NÃO entra aqui.
        try:
            from jarvis.core.model_policy import ModelPolicy
            _framing = ModelPolicy.framing_for(
                getattr(self.config, "llm_model", ""))
            if _framing:
                system_content += f"\n\nMODEL FRAMING:\n{_framing}"
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
        # Cascata API: 1 tentativa por run, SÓ no teto local (3 caminhos
        # STUCK abaixo). Flag fresca por prompt como o detector.
        self._api_fallback_used = False

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
        # podem ajustar JARVIS_AGENT_MAX_TURNS/_TIME_S sem reiniciar.
        try:
            max_turns = int(os.environ.get("JARVIS_AGENT_MAX_TURNS", str(MAX_TURNS)))
        except ValueError:
            max_turns = MAX_TURNS
        try:
            max_time_s = int(os.environ.get("JARVIS_AGENT_MAX_TIME_S", str(MAX_TIME_S)))
        except ValueError:
            max_time_s = MAX_TIME_S
        _t0 = time.monotonic()
        # P0.2: turnos de verificação (DONE sem evidência → continua).
        verify_turns = 0
        # Revisão-sintaxe armada: write barrado por `Bash syntax error`
        # agenda 1 pass de review polimórfico (thinking externalizado) na
        # próxima chamada (dono 19/09; caderno > cadeia volátil). One-shot.
        # Teto de 3 passes/run (L8v34: 2 reviews, 143s, zero fix — review
        # sem limite queima latência sem garantia de ganho).
        self._review_syntax_armed = False
        self._reviews_used = 0
        # Bar-repeat: path → hash do último conteúdo barrado (ordem de
        # troca de estratégia no 2º bar idêntico; L8b1 20/09).
        self._bar_repeat: dict[str, str] = {}
        # Artifact-repeat: .json → nº de checks seguidos inválido (ordem de
        # troca no 2º; L8b3 20/09).
        self._artifact_repeat: dict[str, int] = {}
        # Escalada de serialização: 2º artifact-repeat engata ban
        # vinculante de echo-em-JSON no resto do run (L10 retry: repetir a
        # mesma representação amplifica falha; conselho não muta
        # representação — §19 prompt-only → harness-enforced).
        self._json_echo_banned = False
        # P0.3: erro idêntico repetido (nome+args) → variar ou STUCK.
        error_seen: dict[str, int] = {}
        # Truncamentos seguidos no limite de saída (ironclaw/2026): 3x
        # seguidas escala p/ plano em prosa ( giant calls condenados).
        _trunc_streak = 0
        # Turnos só-malformados seguidos (L8b3 20/09: 17 turns, 9 tool calls
        # — até 8 turns queimados em hint sem teto; verify_turns só cobre
        # no-tool-call, não args-malformados).
        _mal_streak = 0
        for turn in range(max_turns):
            result.turns += 1
            # Circuit breaker de tempo: call stallada (TTFT travado sob
            # carga) não respeita max_turns — aborta honesto em vez de
            # pinar GPU até aborto manual (L8n3 real 19/09).
            if time.monotonic() - _t0 > max_time_s:
                if not result.final_response:
                    result.final_response = (
                        f"STUCK: time budget exceeded ({max_time_s}s "
                        "wall-clock).")
                break
            _armed = self._review_syntax_armed and self._reviews_used < 3
            _effort = ("medium" if _armed else None)
            _focus = ("syntax" if _armed else None)
            if _armed:
                self._reviews_used += 1
            self._review_syntax_armed = False
            response = self._get_llm_response(
                messages, reasoning_effort=_effort, review_focus=_focus)
            # Args truncados (helper acima): repara antes de guardar —
            # o servidor nunca recebe a mensagem malformada (era 500
            # fatal). Hint consome o turno; budget de turnos limita.
            response, _mal_hint = self._repair_malformed_tool_args(
                response, turn)
            # Truncamento no limite de saída (ironclaw/2026: finish "length"
            # = descarte + escalada). Conta streak mesmo quando o reparo
            # acima já cobriu o turno (caso L8: length + JSON inválido).
            if response.get("finish_reason") == "length":
                _trunc_streak += 1
            else:
                _trunc_streak = 0
            _note = _mal_hint
            if not _note and response.get("finish_reason") == "length":
                _note = (
                    f"STATE(truncated_output,streak={_trunc_streak})."
                    " Your last reply was CUT at the output token limit —"
                    " anything after the cut was LOST (not executed)."
                    " NEXT: redo the SAME intent in SMALLER pieces: files"
                    " >~50 lines MUST be split (write part 1, then append"
                    " via execute_shell heredoc or str_replace), commands"
                    " short. Entire reply must be ONE action, zero prose."
                    + ("" if _trunc_streak < 3 else
                       " ESCALATION: 3 cuts in a row — NO tool calls now:"
                       " reply with a numbered PLAN in prose first (steps"
                       " small enough to fit), then execute one per turn."))
            messages.append(response)
            if _note and not response.get("tool_calls"):
                # Nenhum call válido: só a nota, sem executar. Só conta o
                # caso MALFORMED (truncamento tem escalada própria p/ plano
                # em prosa — contar junto mataria a estratégia que o próprio
                # harness ordenou). SEM TETO o malformed queimava budget
                # (L8b3: até 8 turns em hint) — 3x seguidas = STUCK honesto.
                if _mal_hint:
                    _mal_streak += 1
                    if _mal_streak >= 3:
                        result.final_response = (
                            "STUCK: tool-call JSON inválido 3x seguidas "
                            "(geração instável no limite de tokens?) — "
                            "parando em vez de queimar budget; reduza o "
                            "tamanho de cada call e tente de novo.")
                        self._finalize(result, messages, forced="STUCK")
                        break
                messages.append({"role": "user", "content": _note})
                continue
            _mal_streak = 0
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
                    _v_ok = _v is not None and _v.status == "VERIFIED"
                    _v_hollow = _v_ok and not any(
                        e for e in (_v.evidence or [])
                        if not e.startswith("sem erro final"))
                    # Promessa futura ("I will check...") com veredito oco:
                    # stall, não conclusão (fix-git real: prometeu git log
                    # e parou). Consome turno de verificação em vez de
                    # finalizar VERIFIED vazio.
                    import re as _re2
                    _v_promise = bool(_v_hollow and _re2.search(
                        r"(i will|vou |vamos |irei|let me|em seguida|next,?\s+i will)",
                        content or "", _re2.IGNORECASE))
                    _v_sub = _v_ok and not _v_hollow
                    if verify_turns >= 2 and not _v_sub:
                        # Orçamento esgotado sem NENHUMA evidência
                        # substantiva: nunca herda VERIFIED (oco ou não) —
                        # stall/promessa não é conclusão (fix-git real).
                        result.final_response = content
                        self._finalize(result, messages)
                        result.verdict = "UNVERIFIED"
                        result.verified = False
                        result.missing = result.missing + [
                            "orçamento de verificação esgotado (2 turnos "
                            "sem ação conclusiva)"]
                        break
                    if _v_ok and not (_v_promise and verify_turns < 2):
                        result.final_response = content
                        self._finalize(result, messages)
                        break
                    verify_turns += 1
                    # Nudge CODIFICADO (não prosa): modelo pequeno em modo
                    # chat ignora conselho em prosa ("Continue com a próxima
                    # ação" rendeu 3 turnos de conversa fiada no fix-git).
                    # Diretiva tipada + formato exato parseável pelo fallback
                    # (<tool_call>/fenced/bare JSON {"name","arguments"}).
                    messages.append({
                        "role": "system",
                        "content": (
                            f"STATE(no_tool_call,verify={verify_turns}/2)."
                            f" MISSING: {'; '.join(_v.missing[:3])}."
                            " NEXT: emit EXACTLY ONE action, zero prose."
                            " Entire reply must be ONE fenced block:\n"
                            '```json\n{"name": '
                            '"execute_shell"|"read_file"|"list_directory", '
                            '"arguments": {...}}\n```\n'
                            "RULES: action != last failed call; paths only "
                            "from observations; unknown path -> "
                            "list_directory/semantic_search first."),
                    })
                    continue

            # Anti-loop: detect repeated/cyclic tool calls and inject a
            # recovery message. If the model ignores the warning twice in a
            # row, stop the loop instead of burning turns on the same call.
            strategy = self.loop_detector.check(tool_calls, content)
            if strategy.action in (RecoveryAction.ABORT, RecoveryAction.FORCE_ANSWER):
                messages.append({"role": "system", "content": strategy.message})
                if self._stuck_or_cascade(result, messages, prompt,
                                          system_content):
                    break
                self._finalize(result, messages, forced="STUCK")
                break
            if strategy.action != RecoveryAction.NONE:
                messages.append({"role": "system", "content": strategy.message})
                self._loop_warnings += 1
                if self._loop_warnings >= 2:
                    if self._stuck_or_cascade(result, messages, prompt,
                                              system_content):
                        break
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
            _sanitized = False
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
                _strip_note = ""
                if _i in _pre:
                    tool_result = _pre[_i]
                elif name == "execute_shell":
                    cmd = args.get("cmd", "")
                    # Carve-out do idiom fundido `chmod +x F && ./F [args]`
                    # (L8: banido pela policy virava STUCK certo; write já
                    # dá +x então o chmod é redundante). Executa SÓ o run —
                    # menos comandos, nunca mais. Resto encadeado cai no
                    # ban normal abaixo.
                    _stripped = strip_redundant_chmod_run(cmd)
                    if _stripped is not None:
                        cmd = _stripped
                        args = {**args, "cmd": cmd}
                        _strip_note = ("[harness: redundant `chmod +x` "
                                       "skipped (.sh already executable)] ")
                    # Ban vinculante pós-escalada: echo/printf com redirect
                    # direto p/ *.json (v27: 4x echo-surgery idêntica; b3:
                    # runtime inválido ×3 — conselho não mutou representação).
                    # jq/write_file intactos (pipe antes do redirect passa).
                    # Computa flag aqui; o ban entra como 1º elo da cadeia
                    # abaixo (não sobrescreve nem executa depois).
                    _echoban = (self._json_echo_banned
                                and echo_to_json(cmd))
                    # Chaining negado SEMPRE (não só no allowlist): com
                    # approve=True o denial caía no human_approve e o shlex
                    # executava QUEBRADO (L8 real: `chmod && ./` aplicava
                    # parcial e falhava críptico; `a | b` corrompia silente
                    # com rc 0). Segurança não negocia; alternativa: 1 cmd
                    # por call, ou grave .sh via write_file e execute-o.
                    # Placeholder literal no comando (L8b1 20/09: `python3
                    # response.py "$1"`, read de `incident_<IP>_...` — token
                    # ALL-CAPS como <IP> nunca existe no disco; redirect
                    # `<f>` minúsculo passa intacto). Antes do chaining.
                    _ph = re.search(r"<[A-Z][A-Z0-9_]*>", cmd)
                    # Molde-JSON aplicado no alvo errado (L8b2 20/09: 2x
                    # `python3 -c open('intrusion_detector.sh','w').write(
                    # json.dumps(...))` — o molde python3-c é p/ OUTPUTS
                    # .json, nunca p/ sobrescrever .sh via shell. Só dispara
                    # com modo 'w' explícito; leitura open('x.sh') passa).
                    _clob = re.search(
                        r"open\(\s*['\"][^'\"]+\.sh['\"]\s*,\s*['\"]w",
                        cmd)
                    if _echoban:
                        result.commands_denied.append(cmd)
                        tool_result = (
                            "ERROR: BLOCKED — echo-to-JSON banned for this "
                            "run (2 invalid JSON artifacts already; repeating "
                            "the representation failed). Emit via jq -n "
                            "--arg/--argjson, or write_file the .json "
                            "(server grammar enforces syntax).")
                        self._log_audit(cmd, None, tool_result, False)
                    elif _clob is not None:
                        result.commands_denied.append(cmd)
                        tool_result = (
                            "ERROR: Refused — writing over a .sh script via "
                            "python3 in shell. The python3 -c mold is for "
                            ".json OUTPUTS (alert.json/report.json), never "
                            "for scripts. Scripts via write_file; data files "
                            "via the mold with a .json path.")
                        self._log_audit(cmd, None, tool_result, False)
                    elif _ph is not None:
                        result.commands_denied.append(cmd)
                        tool_result = (
                            f"ERROR: Literal placeholder {_ph.group(0)} in "
                            f"command — template tokens never exist on disk. "
                            f"Resolve the REAL value first (list_directory, "
                            f"run the producer script), then call with "
                            f"concrete names.")
                        self._log_audit(cmd, None, tool_result, False)
                    elif has_chaining_operators(cmd):
                        result.commands_denied.append(cmd)
                        tool_result = (
                            f"ERROR: Chaining operators not allowed: {cmd}. "
                            "Use ONE simple command per call; for pipelines "
                            "write a .sh via write_file then execute it "
                            "(`chmod +x` + `./script.sh`, one per call).")
                    # Check if command is allowed
                    elif command_allowed(cmd):
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
                        except OSError as e:
                            # Binário inexistente (ex.: modelo chamou
                            # `pandas ...` como se fosse CLI): observation,
                            # nunca crash do run (csv-to-parquet real).
                            exit_code = 127
                            tool_result = (
                                f"ERROR: Command failed to start: {e}. "
                                f"Check the binary exists (`which "
                                f"{cmd.split()[0] if cmd.split() else cmd}`) "
                                "or use `python3 -c` for libraries."
                                + _missing_binary_hint(cmd))
                            result.commands_run.append(cmd)
                            self._log_audit(cmd, 127, tool_result, True)
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
                                except OSError as e:
                                    exit_code = 127
                                    tool_result = (
                                        f"ERROR: Command failed to start: {e}. "
                                        f"Check the binary exists (`which "
                                        f"{cmd.split()[0] if cmd.split() else cmd}`) "
                                        "or use `python3 -c` for libraries."
                                        + _missing_binary_hint(cmd))
                                    result.commands_run.append(cmd)
                                    self._log_audit(cmd, 127, tool_result, True)
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
                    # Placeholder literal no path (L8b1 20/09: read de
                    # `incident_<IP>_<timestamp>.txt` — token de template nunca
                    # existe no disco; barra dirigido em vez de "not found").
                    _php = re.search(r"<[A-Z][A-Z0-9_]*>",
                                     str(args.get("path", "")))
                    if _php is not None:
                        tool_result = (
                            f"ERROR: Literal placeholder {_php.group(0)} in "
                            f"path — resolve the REAL filename first "
                            f"(list_directory, run the producer script), then "
                            f"read the concrete name.")
                    else:
                        tool_result = self._exec_read_file(args)
                elif name == "list_directory":
                    # Listagem read-only (devtools, cap 100). Sem aprovação:
                    # risco zero. É o LOCATE-first da disciplina — existia
                    # na frase mas nunca como tool (L8: instrução impossível).
                    tool_result = self._exec_list(args)
                elif name == "synthesize_command":
                    # Geração mascarada (H-grammar, NVIDIA GCD-bash): sub-call
                    # com GBNF no decode; SÓ gera, nunca executa (sem
                    # aprovação — risco zero; execução passa pelos gates).
                    _gname = str(args.get("grammar", ""))
                    _gbnf = SYNTH_GRAMMARS.get(_gname)
                    if _gbnf is None:
                        tool_result = (
                            f"ERROR: unknown grammar '{_gname}' (available: "
                            f"{', '.join(sorted(SYNTH_GRAMMARS))}).")
                    else:
                        try:
                            _sresp = self.llm.chat_with_tools(
                                [{"role": "system", "content": (
                                    "Emit ONLY the shell command, no prose, "
                                    "no fences.")},
                                 {"role": "user", "content": str(
                                     args.get("desc", ""))}],
                                tools=None, temperature=0.0, max_tokens=128,
                                role="worker", extra={"grammar": _gbnf})
                            _lines = [
                                _ln.strip().strip("`").strip()
                                for _ln in (_sresp.content or "").splitlines()
                                if _ln.strip()]
                            tool_result = (_lines[0] if _lines else
                                           "ERROR: empty synthesis — "
                                           "rephrase desc and retry.")
                        except Exception as _e:
                            tool_result = (
                                f"ERROR: synthesis failed: {str(_e)[:150]}")
                    result.commands_run.append("synthesize_command")
                    self._log_audit("synthesize_command", 0, tool_result, True)
                elif name == "build_json_dataset":
                    from jarvis.core.devtools import build_json_dataset as _bj
                    tool_result = json.dumps(
                        _bj(args.get("schema", "schema.json"),
                            args.get("out", "organization.json")),
                        ensure_ascii=False, default=str)
                    result.commands_run.append("build_json_dataset")
                    self._log_audit("build_json_dataset", 0, tool_result, True)
                elif name == "sanitize_secrets":
                    from jarvis.core.devtools import sanitize_secrets as _ss
                    tool_result = json.dumps(
                        _ss(args.get("root"), args.get("dry_run", False)),
                        ensure_ascii=False, default=str)
                    result.commands_run.append("sanitize_secrets")
                    self._log_audit("sanitize_secrets", 0, tool_result, True)
                    try:
                        _ssr = json.loads(tool_result)
                        if _ssr.get("ok") and _ssr.get("changed", 0) > 0:
                            # Determinístico: task concluída — manda parar
                            # (senão o modelo continua tentando substituir
                            # os literais dos padrões até STUCK; L4 real).
                            _sanitized = True
                    except (ValueError, TypeError):
                        pass
                elif name in ("book_search", "book_resume"):
                    # Livros: read-only como read_file (Qdrant + bookmark).
                    # Sem aprovação, sem escrita. Erros viram tool result.
                    tool_result = self._exec_book(name, args)
                elif name in ("write_file", "str_replace"):
                    # Escrita: jail de projeto + aprovação explícita.
                    # Sem approve: negação honesta (o modelo pede ao usuário
                    # em vez de improvisar redirect via shell).
                    # Prefix-gating AgentLTL-style (dono 19/09, L8 real 4x):
                    # .json INVÁLIDO com NADA computado no run (zero
                    # execute_shell, zero .sh/.py escritos) = fabricação de
                    # output sem produtores. Bloqueio MECÂNICO pré-execução
                    # (prompt, erro dirigido e validator foram ignorados):
                    # autorar o script que computa, RODAR, depois escrever
                    # a saída. .json válido (ex.: config) passa intacto.
                    _gate_block = False
                    if name == "write_file" and str(
                            args.get("path", "")).endswith(".json"):
                        try:
                            json.loads(str(args.get("content", "")))
                        except Exception:
                            _has_exec = _has_prod = False
                            for _m in messages:
                                for _tc in _m.get("tool_calls") or []:
                                    _f = _tc.get("function", _tc)
                                    if not isinstance(_f, dict):
                                        continue
                                    _fn = _f.get("name")
                                    if _fn in ("execute_shell",
                                               "jarvis_execute"):
                                        _has_exec = True
                                    elif _fn in ("write_file",
                                                 "str_replace"):
                                        try:
                                            _ga = _f.get("arguments", {})
                                            _ga = (json.loads(_ga)
                                                   if isinstance(_ga, str)
                                                   else _ga)
                                        except Exception:
                                            _ga = {}
                                        if str((_ga or {}).get(
                                                "path", "")).endswith(
                                                    (".sh", ".py")):
                                            _has_prod = True
                                    if _has_exec and _has_prod:
                                        break
                                if _has_exec and _has_prod:
                                    break
                            _gate_block = not _has_exec and not _has_prod
                    _gate_msg = (
                        "ERROR: BLOCKED — invalid JSON with nothing "
                        "computed this run (no execute_shell, no "
                        ".sh/.py written). Do NOT hand-write JSON "
                        "outputs. Author the script that computes this "
                        "(.py reading the real inputs + json.dumps, or "
                        ".sh), RUN it, then write its output.")
                    if not _gate_block:
                        # RUN-WHAT-YOU-WROTE mecânico (L8 variante real):
                        # re-editar .sh escrito com sucesso mas NUNCA
                        # executado = fiddle sem feedback (3x str_replace
                        # no-op até STUCK). Trava a re-escrita e força
                        # chmod+run primeiro; typo real aparece no erro do
                        # run. Só conta write com resultado ok (exclui a
                        # call atual, ainda sem resultado).
                        _tpath = str(args.get("path", ""))
                        if _tpath.endswith(".sh"):
                            _base2 = _tpath.rsplit("/", 1)[-1]
                            _wok = _ran2 = False
                            for _i2, _m in enumerate(messages):
                                for _tc in _m.get("tool_calls") or []:
                                    _f = _tc.get("function", _tc)
                                    if not isinstance(_f, dict):
                                        continue
                                    if _f.get("name") in ("write_file",
                                                          "str_replace"):
                                        try:
                                            _ga = _f.get("arguments", {})
                                            _ga = (json.loads(_ga)
                                                   if isinstance(_ga, str)
                                                   else _ga)
                                        except Exception:
                                            _ga = {}
                                        if str((_ga or {}).get(
                                                "path", "")).endswith(_base2):
                                            _nx = (messages[_i2 + 1]
                                                   if _i2 + 1 < len(messages)
                                                   else {})
                                            if (_nx.get("role") == "tool"
                                                    and not str(_nx.get(
                                                        "content", "")).strip(
                                                        ).upper().startswith(
                                                        "ERROR")):
                                                _wok = True
                                    elif _f.get("name") in (
                                            "execute_shell",
                                            "jarvis_execute"):
                                        try:
                                            _ga = _f.get("arguments", {})
                                            _ga = (json.loads(_ga)
                                                   if isinstance(_ga, str)
                                                   else _ga)
                                        except Exception:
                                            _ga = {}
                                        _c = str((_ga or {}).get("cmd", ""))
                                        if (f"./{_base2}" in _c
                                                or re.search(
                                                    r"\b(bash|sh)\s+\S*"
                                                    + re.escape(_base2),
                                                    _c)):
                                            _ran2 = True
                            if _wok and not _ran2:
                                _gate_block = True
                                _gate_msg = (
                                    f"ERROR: BLOCKED — {_base2} was written "
                                    "but never executed. Do NOT re-edit it "
                                    "blind: RUN it first in TWO separate "
                                    "calls (`chmod +x "
                                    f"{_base2}`, then `./{_base2}` — `&&` is "
                                    "blocked), read its real output/errors, "
                                    "THEN fix.")
                    if not _gate_block:
                        # MOVE-FORWARD (formigueiro: não aperfeiçoa uma câmara
                        # enquanto as outras estão vazias — L8v41: 11 turns
                        # só no detector, response.sh nunca começado).
                        # Re-editar .sh que já EXECUTOU COM SUCESSO (exit 0)
                        # com deliverable citado ausente = polimento antes da
                        # cobertura. Trava até o ausente existir; depois
                        # libera tudo (fase de refinamento). Só re-edit
                        # (arquivo tem que EXISTIR): criar nunca trava.
                        _tpath3 = str(args.get("path", ""))
                        if _tpath3.endswith(".sh"):
                            _base3 = _tpath3.rsplit("/", 1)[-1]
                            try:
                                from jarvis.core.devtools import (
                                    resolve_base as _rb4)
                                _root3 = _rb4()
                            except Exception:
                                from pathlib import Path as _P5
                                _root3 = _P5(".")
                            from pathlib import Path as _P6
                            _fp3 = (_root3 / _tpath3 if not _P6(
                                _tpath).is_absolute() else _P6(_tpath3))
                            _ran_ok = False
                            try:
                                if _fp3.is_file():
                                    for _i3, _m3 in enumerate(messages):
                                        for _tc3 in (_m3.get("tool_calls")
                                                     or []):
                                            _f3 = _tc3.get("function", _tc3)
                                            if not isinstance(_f3, dict):
                                                continue
                                            if _f3.get("name") not in (
                                                    "execute_shell",
                                                    "jarvis_execute"):
                                                continue
                                            try:
                                                _ga3 = _f3.get("arguments",
                                                                {})
                                                _ga3 = (json.loads(_ga3)
                                                        if isinstance(
                                                            _ga3, str)
                                                        else _ga3)
                                            except Exception:
                                                _ga3 = {}
                                            _c3 = str((_ga3 or {}).get(
                                                "cmd", ""))
                                            if (f"./{_base3}" not in _c3
                                                    and not re.search(
                                                        r"\b(bash|sh)\s+\S*"
                                                        + re.escape(_base3),
                                                        _c3)):
                                                continue
                                            _nx3 = (messages[_i3 + 1]
                                                    if _i3 + 1 < len(messages)
                                                    else {})
                                            if ("[exit: 0]" in str(_nx3.get(
                                                    "content", ""))):
                                                _ran_ok = True
                                                break
                                        if _ran_ok:
                                            break
                            except Exception:
                                _ran_ok = False
                            if _ran_ok:
                                try:
                                    from jarvis.core.completion import (
                                        missing_deliverables as _md3)
                                    _miss3 = _md3(messages, _root3)
                                except Exception:
                                    _miss3 = []
                                _miss3 = [
                                    _m for _m in _miss3 if _base3 not in _m]
                                if _miss3:
                                    _gate_block = True
                                    _gate_msg = (
                                        f"ERROR: BLOCKED — {_base3} already "
                                        f"runs successfully, but "
                                        f"{'; '.join(_miss3[:2])}. Write the "
                                f"missing deliverable FIRST "
                                f"(skeleton is fine); {_base3} "
                                f"unlocks for refinement after all "
                                f"deliverables exist.")
                    if not _gate_block and name in ("write_file",
                                                    "str_replace"):
                        # Placeholder literal no PATH do write (h1 20/09:
                        # `incident_<IP>_<timestamp>.txt` criado literal no
                        # disco; guards de read/exec não cobrem write —
                        # mesma família do 1d39951, fecha o buraco).
                        _wpp = re.search(r"<[A-Z][A-Z0-9_]*>",
                                         str(args.get("path", "")))
                        if _wpp is not None:
                            _gate_block = True
                            _gate_msg = (
                                f"ERROR: BLOCKED — literal placeholder "
                                f"{_wpp.group(0)} in write path. Template "
                                f"tokens never exist on disk: resolve the "
                                f"REAL filename first (list_directory, run "
                                f"the producer with real values), then write "
                                f"the concrete name.")
                        # Poison absoluto NO CONTEÚDO (L8b1 20/09: conteúdo com
                        # `rules_file=/rules/...` passou no gate de sintaxe e
                        # falhou só no run. Só dispara quando o relativo EXISTE
                        # no CWD e o absoluto NÃO — absoluto real (ex.: CWD
                        # absoluto /tmp/l8bX/logs/x, L8b5 20/09) é legítimo e
                        # passar batido virava STUCK por falso-positivo).
                        _wcontent = str(args.get("content", "") or args.get(
                            "new_string", ""))
                        _pm = None
                        for _m in re.finditer(r"/(app|rules|logs)/",
                                              _wcontent):
                            _s, _e = _m.span()
                            _a = _s
                            while (_a > 0 and _wcontent[_a - 1]
                                   not in " \t\n\"'=():;"):
                                _a -= 1
                            _b = _e
                            while (_b < len(_wcontent) and _wcontent[_b]
                                   not in " \t\n\"'=():;"):
                                _b += 1
                            if os.path.exists(_wcontent[_a:_b]):
                                continue
                            if os.path.exists(_m.group(1)):
                                _pm = _m
                                break
                        if _pm is not None:
                            _gate_block = True
                            _gate_msg = (
                                f"ERROR: BLOCKED — absolute container path "
                                f"`{_pm.group(0)}` in written content. Files "
                                f"live under CWD: replace every "
                                f"`{_pm.group(0)}` with `{_pm.group(0)[1:]}` "
                                f"and rewrite.")
                    if not _gate_block and name == "write_file":
                        # Burro: recusa carga excessiva (write gigante →
                        # trunca nos 4096 tokens do tier → args malformados →
                        # hint → budget queimado; L8b3/b4). Castor no lugar:
                        # primeiro graveto = esqueleto mínimo + molde de
                        # forma (sem valores da task), depois estende. Só
                        # código/dados (.sh/.py/.json) — prosa passa intacta.
                        _wpath4 = str(args.get("path", ""))
                        _wcont4 = str(args.get("content", ""))
                        if (_wpath4.endswith((".sh", ".py", ".json"))
                                and len(_wcont4) > 4000):
                            _gate_block = True
                            _gate_msg = (
                                "ERROR: BLOCKED — carga excessiva "
                                f"({len(_wcont4)} chars; limite 4000 p/ "
                                "código/dados). Writes gigantes truncam no "
                                "limite de tokens e voltam malformados. "
                                "FRACIONE (graveto por graveto): 1) escreva "
                                "o ESQUELETO mínimo válido (molde abaixo), "
                                "2) execute, 3) estenda via str_replace.\n"
                                "Molde .sh:\n#!/bin/sh\nset -uo pipefail")
                    if _gate_block:
                        result.commands_denied.append(
                            f"{name} {args.get('path', '')}")
                        tool_result = _gate_msg
                        self._log_audit(f"{name} {args.get('path', '')}",
                                        None, tool_result, False)
                    elif self.approve and human_approve(
                            f"{name} {args.get('path', '')}"):
                        tool_result = self._exec_write(name, args)
                        # Falha de SINTAXE no write arma 1 pass de revisão
                        # polimórfica (foco syntax) na próxima chamada: o
                        # modelo reexamina com molde, em vez de repetir cego.
                        if "Bash syntax error" in tool_result:
                            self._review_syntax_armed = True
                        # Bar-repeat: mesmo path + conteúdo idêntico barrado
                        # 2x seguidas → ordem de TROCA DE ESTRATÉGIA (L8b1
                        # 20/09: 3x mesmo intrusion_detector.sh barrado; ver a
                        # linha + molde não moveu — repetir texto falhou, o
                        # método tem que mudar).
                        if name in ("write_file", "str_replace"):
                            import hashlib as _hl
                            _bkey = str(args.get("path", ""))
                            _bval = str(args.get("content", "") or args.get(
                                "new_string", ""))
                            _bhash = _hl.md5(_bval.encode()).hexdigest()[:12]
                            if tool_result.startswith("ERROR") and (
                                    "Bash syntax error" in tool_result
                                    or "JSON error" in tool_result):
                                if self._bar_repeat.get(_bkey) == _bhash:
                                    tool_result += (
                                        "\nBLOQUEADO 2x com CONTEÚDO IDÊNTICO "
                                        "— repetir o texto falhou. TROQUE DE "
                                        "ESTRATÉGIA agora: emita o script via "
                                        "python3 (molde acima) ou escreva a "
                                        "versão MÍNIMA (shebang + greps + "
                                        "python3 -c p/ o JSON), execute, e só "
                                        "então estenda.")
                                self._bar_repeat[_bkey] = _bhash
                            elif not tool_result.startswith("ERROR"):
                                self._bar_repeat.pop(_bkey, None)
                        # JSON inválido COM produtores no run: 1 reescrita sob
                        # gramática json_object (C1). Sem produtores = fabricação
                        # (prefix-gate acima já barrou antes de chegar aqui).
                        if (name == "write_file"
                                and str(args.get("path", "")).endswith(".json")
                                and "JSON error" in tool_result):
                            _rw = self._grammar_json_rewrite(
                                str(args.get("content", "")))
                            if _rw is not None:
                                args = {**args, "content": _rw}
                                tool_result = self._exec_write(name, args)
                                if not tool_result.startswith("ERROR"):
                                    tool_result += (
                                        "\n[grammar-rewrite: syntax enforced "
                                        "by server grammar; values from model]")
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

                if _strip_note and not tool_result.startswith("ERROR"):
                    tool_result = _strip_note + tool_result

                # Artefatos JSON do run validados no momento da observação
                # (não só no veredito): scripts geram outputs em runtime,
                # fora de todo gate de write. Vale p/ sucesso E falha
                # (writes parciais acontecem antes do exit != 0).
                if name in ("execute_shell", "jarvis_execute"):
                    for _anote in _check_run_json_artifacts(_t0):
                        tool_result += "\n" + _anote
                        # Repeat: mesmo .json inválido em 2 checks seguidos →
                        # ordem de TROCA DE ESTRATÉGIA (L8b3 20/09: detector
                        # válido+executável gerando JSON inválido; o aviso
                        # "regenerate" sozinho não moveu — ovo inviável pede
                        # método novo, não repetição do gerador).
                        _am = re.search(r"artifact-check: (\S+\.json)", _anote)
                        if _am is not None:
                            _akey = _am.group(1)
                            _acount = self._artifact_repeat.get(_akey, 0) + 1
                            self._artifact_repeat[_akey] = _acount
                            if _acount >= 2:
                                # Escalada soft→binding: a partir daqui
                                # echo/printf com redirect p/ *.json é
                                # BLOCKED (só jq/write_file). Monotônico no
                                # run (falha semântica determinística, não
                                # transiente).
                                self._json_echo_banned = True
                                tool_result += (
                                    f"\nBLOQUEADO 2x: {_akey} segue inválido "
                                    f"— repetir o gerador falhou. TROQUE DE "
                                    f"ESTRATÉGIA: delete {_akey} (`rm "
                                    f"{_akey}`), gere-o via python3 -c com "
                                    f"VALORES reais já computados (grep -c, "
                                    f"grep -o), e SÓ então ajuste o script "
                                    f"p/ replicar o formato válido.")

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
                # Sucesso pelo MECANISMO (exit code / convenção "ERROR:"),
                # nunca por keyword no conteúdo: stdout com "not allowed"
                # (ex.: grep em auth.log, L8 real) ou JSON com "invalid"
                # (detection_rules.json) NÃO é falha. Classificador só
                # rotula falhas genuínas (política de retry).
                if name == "execute_shell" and exit_code is not None:
                    _ok = (exit_code == 0)
                else:
                    _ok = not tool_result.startswith("ERROR")
                _kind = "ok" if _ok else classify_error(tool_result)
                result.steps.append({"turn": turn, "tool": name,
                                     "ok": _ok, "kind": _kind,
                                     "args": str(args)[:120]})
                try:
                    self.logger.emit("agent_step", detail={
                        "turn": turn, "tool": name, "ok": _ok, "kind": _kind})
                except Exception:
                    pass
                if not _ok:
                    _sig = f"{name}::{json.dumps(args, sort_keys=True, default=str)}"
                    error_seen[_sig] = error_seen.get(_sig, 0) + 1
                    if error_seen[_sig] == 2:
                        # Recuperação CODIFICADA (não conselho): mesmo formato
                        # exato do fallback + alternativa concreta. Prosa
                        # ("varie a abordagem") foi ignorada e rendeu 3ª
                        # repetição idêntica no fix-git.
                        messages.append({
                            "role": "system",
                            "content": (
                                f"STATE(same_call_failed_2x,tool={name},"
                                f"error={_kind}). NEXT: EXACTLY ONE action, "
                                "zero prose, DIFFERENT call. Entire reply must "
                                "be ONE fenced block:\n"
                                '```json\n{"name": "<other tool>", '
                                '"arguments": {...}}\n```\n'
                                "RULES: never repeat this call; read_file "
                                "failed -> execute_shell recon "
                                "(`ls`, `git log --all --oneline -n 20`, "
                                "`git reflog -n 20`); shell failed -> "
                                "read the target file first."),
                        })
                    elif error_seen[_sig] >= 3:
                        if self._stuck_or_cascade(result, messages, prompt,
                                                  system_content):
                            _stuck_abort = True
                            break
                        self._finalize(result, messages, forced="STUCK")
                        _stuck_abort = True
                        break

            _cov_notes = []
            for _tc in tool_calls:
                _fn = _tc.get("function", _tc)
                if not isinstance(_fn, dict):
                    continue
                if _fn.get("name") in ("write_file", "str_replace"):
                    try:
                        _ra = _fn.get("arguments", "{}")
                        _ag = json.loads(_ra) if isinstance(_ra, str) else _ra
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(_ag, dict) and _ag.get("path"):
                        _n = _partial_coverage_note(
                            messages, str(_ag.get("path")))
                        if _n and _n not in _cov_notes:
                            _cov_notes.append(_n)
            if _cov_notes:
                messages.append({
                    "role": "system",
                    "content": "COVERAGE: " + " ".join(_cov_notes),
                })

            # Worked example p/ sanitize (ver helper): usa valores OBSERVADOS
            # para quebrar o loop nome-vs-valor (L4 real).
            _we = _secret_worked_example(messages, prompt)
            if _we:
                messages.append({"role": "system", "content": _we})

            if _note:
                # Havia calls válidos (executados acima) + problema
                # (malformed/truncado): nota no fim do turno, após results.
                messages.append({"role": "user", "content": _note})

            # RUN-WHAT-YOU-WROTE (ver helper): script escrito sem execução
            # vira ordem de EXECUTE — victory bias não conclui sem rodar.
            _rw = _unexecuted_script_note(messages)
            if _rw:
                messages.append({"role": "user", "content": _rw})

            # READ-BEFORE-WRITE (ver helper): script referencia arquivos
            # nunca lidos → ordem de LER antes de corrigir (map-before-code).
            _rbw = _unread_refs_note(messages)
            if _rbw:
                messages.append({"role": "user", "content": _rbw})

            # PLACEHOLDER-DETECTOR: script dummy com exit 0 mas sem lógica
            # real (L8 bonsai placeholder trap).
            _ph = _placeholder_script_note(messages)
            if _ph:
                messages.append({"role": "user", "content": _ph})

            # PROGRESS-CHECK periódico (L8v38: 15 turns só na parte 1, parte
            # 2 nunca começada; o miss de deliverable só aparecia no fim).
            # A cada ~6 turns, nomeia deliverables ainda ausentes (mesma
            # extração do veredito). Genérico, limitado, sem ensinar solução.
            if turn in (5, 11):
                try:
                    from jarvis.core.completion import missing_deliverables
                    from jarvis.core.devtools import resolve_base as _rb3
                    try:
                        _proot = _rb3()
                    except Exception:
                        from pathlib import Path as _P4
                        _proot = _P4(".")
                    _pdm = missing_deliverables(messages, _proot)
                except Exception:
                    _pdm = []
                if _pdm:
                    messages.append({
                        "role": "system",
                        "content": (
                            f"PROGRESS-CHECK (turn {turn + 1}): still "
                            f"missing: {'; '.join(_pdm[:3])}. If the current "
                            f"part works, START the next deliverable now "
                            f"instead of perfecting this one."),
                    })

            if _sanitized and not _stuck_abort:
                # sanitize_secrets já concluiu (determinístico): para.
                messages.append({
                    "role": "system",
                    "content": ("DONE_SANITIZE: todos os segredos conhecidos "
                                "foram trocados por placeholders. Reporte "
                                "isso e PARE — não edite mais nenhum arquivo "
                                "nem substitua literais de padrão."),
                })
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

        if (result.verdict == "unknown" and result.turns >= max_turns
                and not (result.final_response or "").strip()):
            # Esgotou turns sem declarar nada: silêncio ≠ conclusão (L8v9
            # real: 18 turns só de tool-calls, final vazio → VERIFIED vácuo
            # sobre trabalho parcial). STUCK forçado com motivo; evidência
            # do que existe vai p/ evidence/missing normalmente.
            result.final_response = (
                "STUCK: turnos esgotados sem declaração de conclusão.")
            self._finalize(result, messages, forced="STUCK")
        elif result.verdict == "unknown":
            # Saídas sem veredito (overflow, max_turns): verifica o que há.
            self._finalize(result, messages)
        result.messages = messages
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

    def _try_api_cascade(self, prompt: str,
                           system_content: str) -> str | None:
        """Fallback API UMA vez por run, SÓ no teto local comprovado.

        Anti-preguiça (dono 17/09): (1) só chamado nos 3 caminhos STUCK
        (loop abortado, warnings ignorados 2x, mesmo erro 3x) — nunca na
        primeira dificuldade; (2) 1x por run (flag resetada por prompt);
        (3) só se houver key (sem key = sem chamada, segue STUCK);
        (4) tentativa FRESCA (system+prompt, sem trajetória envenenada);
        (5) telemetria (api_fallback/api_model no result + evento).
        Retorna conteúdo ou None. v1: sem trajectory shipping, sem cost
        caps (tiers free), sem tuning por camada.
        """
        if getattr(self, "_api_fallback_used", False):
            return None
        try:
            from jarvis.core.model_policy import cascade_for
            from jarvis.providers.llm_remote import RemoteBackend
        except Exception:
            return None
        layer = _api_layer_for(prompt)
        for provider, model, base_url, env_key in cascade_for(layer):
            key = os.environ.get(env_key, "")
            if not key:
                continue
            try:
                resp = RemoteBackend(
                    base_url=base_url, model=model,
                    api_key=key, provider=provider).chat(
                    [{"role": "system", "content": system_content},
                     {"role": "user", "content": prompt}],
                    temperature=0.0, max_tokens=1024)
                if resp and (resp.content or "").strip():
                    self._api_fallback_used = True
                    self._last_api_provider = provider
                    self._last_api_model = model
                    try:
                        self.logger.emit("api_fallback", detail={
                            "layer": layer, "provider": provider,
                            "model": model})
                    except Exception:
                        pass
                    return resp.content
            except Exception:
                continue
        return None

    def _stuck_or_cascade(self, result: "AgentResult",
                          messages: list[dict[str, Any]],
                          prompt: str, system_content: str) -> bool:
        """STUCK ou cascata: tenta API 1x antes de declarar STUCK.

        Retorna True se resolveu via cascata (caller faz break);
        False se segue STUCK normal.
        """
        fb = self._try_api_cascade(prompt, system_content)
        if fb:
            result.final_response = fb
            result.api_fallback = True
            try:
                result.api_model = f"{self._last_api_provider}/{self._last_api_model}"
            except Exception:
                pass
            self._finalize(result, messages)
            return True
        self._finalize(result, messages, forced="STUCK")
        return False

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
        # Consciência de contexto (dono 16/09): após swap, o ctx do modelo
        # novo pode diferir — budget re-criado (auto-detect fresh do /props
        # ou registry). Budget stale subestimava/estourava silencioso.
        if report.switched:
            try:
                self.context_budget = ContextBudget()
            except Exception:
                pass

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
                            tool_calls=calls,
                            finish_reason=resp.finish_reason or "")

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
        if "not found" in str(res.get("error", "")).lower():
            # Auto-relocate em candidato ÚNICO (L8r real: modelo ignorou o
            # path exato dado no warning 3x seguidas → STUCK). Doutrina
            # absorver-imprecisão (precedente: redirect container→base):
            # rglob do basename no CWD; 1 arquivo → serve direto com nota.
            # 0 ou 2+ → erro normal (ambíguo não se adivinha).
            from pathlib import Path as _P
            _name = _P(str(args.get("path", ""))).name.strip()
            _hits: list = []
            if _name:
                try:
                    for _p in _P.cwd().rglob(_name):
                        if _p.is_file():
                            _hits.append(_p)
                            if len(_hits) > 1:
                                break
                except Exception:
                    _hits = []
            if len(_hits) == 1:
                try:
                    # Decoys vazios NÃO servem (L8v12: script quebrado criou
                    # auth.json vazio e o relocate o serviu, confirmando a
                    # alucinação). Dado real nunca tem 0 bytes.
                    if _hits[0].stat().st_size == 0:
                        _hits = []
                except OSError:
                    _hits = []
            if len(_hits) == 1:
                try:
                    res2 = _canonical_read(str(_hits[0]), offset=offset,
                                           limit=limit)
                except Exception:
                    res2 = None
                if res2 and res2.get("ok"):
                    return (f"# {res2.get('path', '')} "
                            f"({res2.get('total_lines', 0)} linhas) "
                            f"[auto-relocated from {args.get('path', '')}]\n"
                            f"{res2.get('content', '')}")
        return f"ERROR: {res.get('error', 'read failed')}"

    @staticmethod
    def _exec_list(args: dict[str, Any]) -> str:
        """list_directory canônico (devtools, read-only, sem aprovação)."""
        from jarvis.core.devtools import list_directory as _canonical_ls
        try:
            res = _canonical_ls(str(args.get("path", ".") or "."))
        except Exception as e:
            return f"ERROR: list failed: {e}"
        if res.get("ok"):
            names = [f"{e.get('name', '')}/" if e.get("type") == "dir" else str(e.get("name", ""))
                     for e in res.get("entries", [])]
            extra = ""
            if res.get("truncated"):
                try:
                    _omit = int(res.get("total_found", 0)) - int(res.get("count", 0))
                except (TypeError, ValueError):
                    _omit = 0
                extra = f" (+{_omit} omitidos)"
            return f"# {res.get('path', '')} ({res.get('count', 0)} itens{extra}): " + ", ".join(names[:100])
        err = str(res.get("error", "list failed"))
        hint = str(res.get("hint", ""))
        return f"ERROR: {err}" + (f" [{hint}]" if hint else "")

    def _grammar_json_rewrite(self, content: str) -> str | None:
        """Reescreve conteúdo como JSON estrito sob gramática do servidor.

        C1 (dono 19/09, Portão do Caractere): `response_format: json_object`
        remove o livre-arbítrio sobre caracteres de controle no decode —
        aspas simples/formas inválidas viram impossíveis. VALORES continuam
        100% do modelo (sintaxe ≠ semântica); world check e completion
        julgam o conteúdo depois (sem maquiar benchmark: a camada é
        explícita e logada). UMA tentativa por call (custo limitado);
        None = mantém o erro original.
        """
        try:
            profile = detect_profile(self.config.llm_model or "")
            resp = self.llm.chat_with_tools(
                [{"role": "user", "content": (
                    "Rewrite the following as STRICT valid JSON, preserving "
                    "all keys and values exactly (only fix quoting/syntax):\n"
                    + content[:4000])}],
                tools=None,
                temperature=0.0,
                max_tokens=min(profile.get("max_tokens", 2048),
                               len(content) + 512),
                extra={"response_format": {"type": "json_object"}},
                role="orchestrator",
            )
            out = (resp.content or "").strip()
            if not out.startswith(("{", "[")):
                import re as _re9
                _m = _re9.search(r"(\{.*\}|\[.*\])", out, re.DOTALL)
                out = _m.group(1) if _m else out
            json.loads(out)
            return out
        except Exception:
            return None

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
                                      str(args.get("new", "")),
                                      bool(args.get("allow_multiple", False)))
        except Exception as e:
            return f"ERROR: write failed: {e}"
        if res.get("ok"):
            _x = " (executable, no chmod needed)" if res.get("executable") else ""
            return f"ok: {name} {res.get('path', args.get('path', ''))}{_x}"
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

    def _get_llm_response(self, messages: list[dict[str, Any]],
                            reasoning_effort: str | None = None,
                            review_focus: str | None = None) -> dict[str, Any]:
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
                "name": "list_directory",
                "description": "List a directory (names + dir/file, capped). ALWAYS call on CWD first when a task references files — paths in prompts may be container paths that don't exist here.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory (absolute or relative to CWD, default .)"},
                    },
                    "required": [],
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
                        "allow_multiple": {"type": "boolean", "description": "Replace all occurrences when old matches N times"},
                    },
                    "required": ["path", "old", "new"],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "build_json_dataset",
                "description": ("Deterministic schema-driven CSV->JSON: reads "
                                "schema.json + CSVs in the dir, joins by FK, "
                                "builds nested structure + statistics. Use for "
                                "'transform CSVs into a JSON file per schema'."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "schema": {"type": "string"},
                        "out": {"type": "string"},
                    },
                    "required": [],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "sanitize_secrets",
                "description": ("Deterministic secret sanitizer: replace ALL "
                                "known secret VALUES (AWS AKIA..., ghp_ GitHub, "
                                "hf_ HuggingFace) with placeholders across the "
                                "repo. Use for 'clean/remove/sanitize API keys'. "
                                "Reports files changed, never the values."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "root": {"type": "string", "description": "Repo root (default cwd)"},
                        "dry_run": {"type": "boolean", "description": "Preview only"},
                    },
                    "required": [],
                },
            },
        }, {
            "type": "function",
            "function": {
                "name": "book_search",
                "description": "Search the AUDIOBOOK library only (spoken books). NEVER for code, files, keys or repo content — for code use semantic_search/code_search/grep via execute_shell. 'book' must be a book title, never a project name.",
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
            }, {
            "type": "function",
            "function": {
                "name": "synthesize_command",
                "description": ("Generate ONE shell command under a grammar mask (server-enforced syntax). Use ONLY after a syntax bar, picking the family: count/search lines=grep, read JSON=jqread, timestamp=date, chmod file=chmod. Returns the bare command; execute it via execute_shell afterwards."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "desc": {"type": "string", "description": "What the command must do"},
                        "grammar": {"type": "string", "description": "Mask id: grep, jqread, date, chmod"},
                    },
                    "required": ["desc", "grammar"],
                },
            },
        }]
        if not getattr(self, "_book_tools_offered", True):
            tools = [t for t in tools
                     if t.get("function", {}).get("name")
                     not in ("book_search", "book_resume")]        # build_json_dataset: só em task de transformação de dados.
        if not getattr(self, "_data_task_offered", False):
            tools = [t for t in tools
                     if t.get("function", {}).get("name")
                     != "build_json_dataset"]
        # sanitize_secrets: só em task de segredo (progressive disclosure).
        if not getattr(self, "_secret_task_offered", False):
            tools = [t for t in tools
                     if t.get("function", {}).get("name")
                     != "sanitize_secrets"]
        # synthesize_command: só pós-bar de sintaxe/serialização (mesmo
        # padrão — L8g1: no schema desde o turno 1 virou distração).
        if not _synth_offered(
                getattr(self, "_bar_repeat", None),
                getattr(self, "_artifact_repeat", None),
                getattr(self, "_json_echo_banned", False)):
            tools = [t for t in tools
                     if t.get("function", {}).get("name")
                     != "synthesize_command"]
        if self.mcp_servers:
            tools.append({
                "type": "function",
                "function": {
                "name": "execute_shell",
                "description": ("Execute a shell command. Code blocks in prose "
                                "DO NOT execute — to run anything, call this "
                                "tool (never paste the command for the user). "
                                "For JSON output or computation prefer "
                                "`python3 -c` with json.dumps (stdlib, always "
                                "valid) over echo/jq pipelines."),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "cmd": {"type": "string", "description": "Command to execute"}
                        },
                        "required": ["cmd"]
                    }
                }
            })
            # NUNCA anunciar `{server}_query`: o loop não despacha MCP
            # (caía em "Unknown tool" — L8 real: nixos_query queimou turno).
            # Schema-gating: invisível > quebrado. Reanunciar quando houver
            # dispatch real p/ MCPClient no loop.
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
            reasoning_effort=reasoning_effort,
            review_focus=review_focus,
            extra=self._strict_extra(tools) if need_call else None,
            # Placement explícito: este é o loop do orquestrador — único
            # ponto onde review loops são admitidos. Chamadas worker/
            # subagente devem usar role="worker" (effort forçado low).
            role="orchestrator",
        )
        # Donkey observável: composição do payload desta call (chars por
        # segmento, espelhando o que foi ENVIADO: tools=None no modo
        # constrained também manda []). Best-effort, nunca quebra a call.
        try:
            _tel = self.llm.session_telemetry
            _last = _tel.last if _tel is not None else None
            if _last is not None:
                import json as _pj
                _last.stage = "llm"
                _last.sys_chars = len(str((messages[0].get("content", "")
                                           if messages else "")))
                _last.tools_chars = len(_pj.dumps(
                    [] if need_call else tools, default=str))
                _last.msgs_chars = sum(
                    len(str(m.get("content", ""))) for m in messages[1:])
        except Exception:
            pass
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
            # finish_reason ancora detecção de truncamento no loop
            # (ironclaw/2026: length → descarta + escala; servidor ignora
            # o campo extra no histórico — verificado E2E).
            "finish_reason": resp.finish_reason or "",
        }
        
        # Fallback: raise not implemented
        raise NotImplementedError("LLM provider not configured")