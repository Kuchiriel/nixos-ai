"""Harness — Unified orchestrator for the Nightwatch autonomous coding agent.

This is the SINGLE entrypoint for all nightwatch operations.
Replaces both orchestrator.py (v2 scripted) and llm_loop.py (v3 LLM-based).

Architecture:
    Task Discovery (categories + LLM)
        ↓
    TaskQueue (persistent state machine)
        ↓
    Patcher (LLM generates patches, not full files)
        ↓
    SafeEditor (atomic writes, validation, backup)
        ↓
    Validator (syntax → imports → tests)
        ↓
    Evaluator (independent review)
        ↓
    Checkpoint (save state)
        ↓
    Safety (protected paths, git ops)
        ↓
    Commit (only if all gates pass)
        ↓
    Learning (persist to AGENTS.md)
        ↓
    Telegram notification

Invariants:
    1. LLM never writes directly to filesystem
    2. Every change has a baseline
    3. Validation is proportional to change type
    4. Unit tests ≠ success
    5. Evaluator is independent from implementer
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from enum import Enum
from nightwatch.task_queue import TaskQueue, Task, TaskStatus, LoopDetector, MissionState
from jarvis.core.eventbus import EventBus, Event


class FailureType(str, Enum):
    """Classification of task failures for recovery strategy."""
    TRANSIENT = "transient"        # Network, timeout, temporary LLM error
    TOOL_FAILURE = "tool_failure"    # Tool returned error, could retry
    VALIDATION_FAILURE = "validation_failure"  # Code didn't pass checks
    CONTEXT_EXHAUSTION = "context_exhaustion"  # Ran out of context
    TASK_FAILURE = "task_failure"    # Task itself is flawed
    UNRECOVERABLE = "unrecoverable"  # Should not retry


def classify_failure(error: str, task_status: str) -> FailureType:
    """Classify a failure into a recovery strategy category."""
    error_lower = (error or "").lower()

    # Transient errors — worth retrying
    if any(kw in error_lower for kw in ["timeout", "connection", "network", "temporary"]):
        return FailureType.TRANSIENT
    if "llm error" in error_lower or "api error" in error_lower:
        return FailureType.TRANSIENT

    # Context exhaustion — need compaction
    if any(kw in error_lower for kw in ["context", "token", "exceeds", "overflow"]):
        return FailureType.CONTEXT_EXHAUSTION

    # Tool failures — could retry with different approach
    if any(kw in error_lower for kw in ["tool", "command", "permission", "denied"]):
        return FailureType.TOOL_FAILURE

    # Validation failures — code is wrong
    if any(kw in error_lower for kw in ["syntax", "import", "validation", "test fail"]):
        return FailureType.VALIDATION_FAILURE

    # SafeEditor rejections — LLM produced bad code
    if "safeditor" in error_lower or "rejected" in error_lower:
        return FailureType.VALIDATION_FAILURE

    # Protected path
    if "protected" in error_lower:
        return FailureType.UNRECOVERABLE

    # Default: task failure (flawed task definition)
    return FailureType.TASK_FAILURE
from nightwatch.safe_editor import SafeEditor, EditResult
from nightwatch.validator import validate_change, ValidationReport
from nightwatch.evaluator import review_change, auto_review, ReviewResult
from nightwatch.checkpoint import Checkpoint, create_checkpoint_for_task, get_recovery_context
from nightwatch import safety
from nightwatch import project_isolation
from nightwatch.project_isolation import (
    ProjectConfig, ProjectRegistry, discover_projects,
    get_project_root, validate_project_path, run_in_project,
)
from nightwatch.context_budget import ContextBudget, query_server_context_size
from nightwatch.paths import find_repo_root


STATE_DIR = Path.home() / ".local/state/jarvis/nightwatch"
PROGRESS_LOG = STATE_DIR / "progress.jsonl"


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class HarnessConfig:
    """Configuration for the harness."""
    project: str = "nixos-ai"
    max_tasks: int = 10
    strict_projects: bool = False  # (26/09) --projects explícito = não expandir
    # (26/09, mandato do dono) Nightwatch = QUALIDADE, tempo não importa
    # (roda de noite). Padrão: MoE uncensored :8084 sem thinking — o bonsai
    # provou não emitir json-patch legível (3/3 no teste do dia). Override
    # por env continua valendo (JARVIS_LLM_BASE_URL/MODEL/DISABLE_THINKING).
    llm_base_url: str = "http://127.0.0.1:8084/v1"
    llm_model: str = "jarvis-strong"
    llm_thinking: bool = False
    max_minutes: int = 180
    max_retries: int = 3
    auto_approve: bool = True
    run_tests: bool = True
    run_imports: bool = True
    auto_review: bool = True
    telegram_notifications: bool = True
    use_llm_discovery: bool = True
    use_scripted_discovery: bool = True
    dry_run: bool = False
    # Multi-project
    projects: list[str] = field(default_factory=list)  # empty = auto-discover
    project_switch_interval: int = 5  # switch project every N tasks
    # Context budget (0 = auto-detect from llama.cpp /props endpoint)
    context_budget: int = 0
    compaction_threshold: float = 0.7
    # Anti-loop detection
    loop_max_attempts: int = 3
    loop_window_seconds: float = 300.0
    # Task timeout (seconds) — tasks running longer are killed
    task_timeout: int = 600  # 10 minutes


@dataclass
class HarnessResult:
    """Result of a harness run."""
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_blocked: int = 0
    tasks_skipped: int = 0
    files_changed: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)
    # (30/09, C5) Métrica de convergência. Sem ela, "o retry converge?"
    # era resposta de ler log na mão — e a lição (8) exige N≥3 medido.
    # retry_succeeded conta tasks que passaram numa tentativa > 1 (o
    # modelo aprendeu com o erro); retry_attempted conta quantas
    # tentaram retry. convergence = retry_succeeded / retry_attempted.
    retry_succeeded: int = 0
    retry_attempted: int = 0

    def _retry_succeeded_here(self, attempt: int) -> None:
        """(30/09, C5) Marca convergência se a validação passou numa
        tentativa > 1. Guarda no estado do harness; o run() agrega no
        HarnessResult. Se attempt == 0, não é retry — não conta."""
        if attempt > 0:
            self._retry_ok = getattr(self, "_retry_ok", 0) + 1

    @property
    def convergence(self) -> float:
        if self.retry_attempted == 0:
            return 0.0
        return self.retry_succeeded / self.retry_attempted

    @property
    def total(self) -> int:
        return self.tasks_completed + self.tasks_failed + self.tasks_blocked

    @property
    def success_rate(self) -> float:
        return self.tasks_completed / self.total if self.total > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Interface
# ═══════════════════════════════════════════════════════════════════════════════

def _default_call_llm(prompt: str, max_tokens: int = 2048) -> str:
    """Call the local LLM via the unified provider LLMClient.

    Uses jarvis.providers.llm which supports multiple backends
    (llama-cpp, prismml, bonsai) via the LLMBackend abstraction.

    Disables thinking tokens for coding tasks to prevent
    reasoning from consuming the entire max_tokens budget.

    Choke point ÚNICO de todo LLM do nightwatch (discovery, patcher,
    three_agent): a disciplina de tool-use mora aqui e vale para
    todos os chamadores (lição do UX-abismo: modelo fraco sem
    disciplina improvisa; com disciplina, segue o formato).
    """
    import time
    t0 = time.monotonic()
    print(f"[nightwatch] llm-call start (max_tokens={max_tokens})",
          file=sys.stderr)
    try:
        from jarvis.providers.llm import LLMClient
        from jarvis.core.config import Config
        # (26/09) Endpoint vem do ENV — o run_nightwatch seta JARVIS_LLM_*
        # com os defaults do HarnessConfig (MoE :8084) ANTES de qualquer
        # chamada; env explícito do usuário continua mandando.
        client = LLMClient(Config())
        messages = [
            {"role": "system", "content": (
                "You are a code improvement assistant. "
                "Follow the format instructions exactly. "
                "Return structured patches as requested.\n\n"
                "TOOL_USE_DISCIPLINE (always):\n"
                "1. Locate first: reference exact file paths and line "
                "numbers; never invent paths.\n"
                "2. Evidence before answer: only describe what the code "
                "shows; no speculative claims.\n"
                "3. Structured output only: emit exactly the requested "
                "format (JSON/patch), no prose around it.\n"
                "4. If the task is ambiguous, return the safest minimal "
                "change, never a guess.")},
            {"role": "user", "content": prompt},
        ]
        response = client.chat_with_tools(
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
            extra={"chat_template_kwargs": {"enable_thinking": False}},
        )
        content = response.content or ""
        # Some backends put response in tool_calls when structured; check content
        if not content.strip() and response.tool_calls:
            # Tool calls present — stringify them
            import json
            content = json.dumps(response.tool_calls, indent=2)
        dt = time.monotonic() - t0
        print(f"[nightwatch] llm-call done in {dt:.1f}s "
              f"({len(content)} chars)", file=sys.stderr)
        return content or "ERROR: empty response from LLM"
    except Exception as e:
        dt = time.monotonic() - t0
        print(f"[nightwatch] llm-call FAILED after {dt:.1f}s: {e}",
              file=sys.stderr)
        return f"ERROR: {e}"


def _default_send_telegram(message: str) -> bool:
    """Delegate to canonical telegram provider.

    The old implementation read /etc/jarvis-telegram.env directly and failed
    silently. This delegates to jarvis.providers.telegram.send_notification()
    which is tested and used by heal.py.
    """
    try:
        from jarvis.providers.telegram import send_notification
        ok = send_notification(message)
        if not ok:
            print("[nightwatch] Telegram configured but send failed — check bot token")
        return ok
    except Exception as e:
        print(f"[nightwatch] Telegram unavailable: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Task Discovery
# ═══════════════════════════════════════════════════════════════════════════════

def _discover_scripted_tasks() -> list[Task]:
    """Discover tasks from the category registry (security scanner, TODO finder, etc.)."""
    try:
        from nightwatch.categories import CATEGORY_REGISTRY, SEVERITY_ORDER
    except ImportError:
        return []

    tasks = []
    for cat_name, cat_fn in CATEGORY_REGISTRY.items():
        try:
            scripted_tasks = cat_fn()
            for st in scripted_tasks:
                # (30/09) Task sem target_path não tem arquivo pro patch
                # loop ler → _request_patch morre em "No readable target
                # files" (task de review tipo "586 functions in core/" não
                # nomeia UM arquivo). Não é tarefa de patch: descarta aqui
                # em vez de queimar 3 tentativas de LLM. Mesmo espírito do
                # fix do discovery (não alimentar o loop com inaplicável).
                if not st.target_path:
                    continue
                # Convert categories.Task → task_queue.Task
                tasks.append(Task(
                    id=st.id,
                    project="nixos-ai",
                    description=st.description,
                    target_files=[st.target_path] if st.target_path else [],
                    acceptance_criteria="",
                    priority=SEVERITY_ORDER.get(st.severity, 5),
                    risk="low" if st.severity in ("info", "low") else "medium",
                    status=TaskStatus.READY.value,
                ))
        except Exception:
            pass
    return tasks


def _extract_json_array(text: str) -> list:
    """Extrai o primeiro array JSON completo do texto (tolerante).

    Modelos fracos embrulham o array em prosa/cercas ```json. find/
    rfind quebra com colchetes dentro de strings ou texto após o
    array — aqui o matching respeita strings e escapes, com fallback
    para objetos avulsos {...}.
    """
    start = text.find("[")
    if start < 0:
        return []
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(text[start:i + 1])
                    return data if isinstance(data, list) else []
                except json.JSONDecodeError:
                    break
    # Fallback: objetos avulsos
    objs = []
    for m in re.finditer(r"\{[^{}]*\"description\"\s*:\s*\"([^\"]+)\"[^{}]*\}", text):
        try:
            objs.append(json.loads(m.group(0)))
        except json.JSONDecodeError:
            continue
    return objs


def _discover_llm_tasks(call_llm_fn: Callable, project: str = "nixos-ai") -> list[Task]:
    """Use the LLM to discover improvement tasks in the codebase.
    
    Enhanced version that uses workspace context and RAG for better discovery.
    Uses the active project root (task > env > discovery).
    """
    # Get project root for file discovery
    project_root = find_repo_root()
    
    # Get codebase overview
    # (30/09) fingerprint de arquivos REAIS e ACIONÁVEIS, em path RELATIVO
    # ao root. Antes: `find <abs>` devolvia absolutos e a lista ia crua pro
    # LLM — o modelo não tinha os arquivos do projeto, só invivia path, e o
    # patch loop morria em "No readable target files". Agora o LLM vê paths
    # que ele pode realmente citar, e Known-files vira a base do
    # _resolve_llm_targets (match por basename).
    try:
        result = subprocess.run(
            ["find", str(project_root), "-name", "*.py", "-type", "f",
             "-not", "-path", "*/__pycache__/*", "-not", "-path", "*/node_modules/*",
             # (30/09) archive/ = código ARQUIVADO deliberadamente (0 imports,
             # substituído — ver archive/README.md). Medido: 5/5 tasks da noite
             # apontam p/ archive/core/*, ou seja a noite inteira gasta
             # testando/refatorando código MORTO. Não roda, não tem usuário,
             # não é-blob de melhoria. Fora da lista de alvos.
             "-not", "-path", "*/archive/*"],
            capture_output=True, text=True, timeout=10,
        )
        rel_files = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            rel = _normalize_target(line, project_root)
            if rel and _target_is_actionable(rel):
                rel_files.append(rel)
        rel_files = sorted(set(rel_files))
        files = rel_files[:40]
    except Exception:
        rel_files = []
        files = []

    # Get workspace context if available
    workspace_context = ""
    try:
        from jarvis.core.workspace import WorkspaceDiscovery
        ws = WorkspaceDiscovery()
        ws.discover()
        if project in ws._projects:
            ctx = ws.get_project_context(project)
            workspace_context = f"\nProject: {project}\nType: {ctx.get('manifest', {}).get('type', 'unknown')}\nFiles: {ctx.get('file_count', 0)}\nLines: {ctx.get('total_lines', 0)}\n"
    except Exception:
        pass

    # Get recent git changes for context (use project root)
    git_context = ""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            capture_output=True, text=True, timeout=5,
            cwd=str(project_root),
        )
        if result.stdout.strip():
            git_context = f"\nRecent changes:\n{result.stdout.strip()}\n"
    except Exception:
        pass

    # (30/09) GROUND TRUTH dos testes existentes. Causa medida: o LLM
    # propunha "Add unit tests for AST cache" — mas o harness SÓ lhe
    # mostrava `find *.py` do código-fonte, nunca os arquivos de teste.
    # Ele não tinha como saber que o teste já existia, então inventava
    # trabalho já feito (task que nunca converge: o patch "cria" o que
    # já está lá). Não é o modelo propose besteira — é o harness
    # escondendo a evidência que a tornaria besta impossível
    # (arxiv-2607.28802: falha de execução/orquestração, não de
    # conhecimento).
    tests_context = ""
    try:
        t = subprocess.run(
            ["find", str(project_root), "-name", "test_*.py", "-type", "f",
             "-not", "-path", "*/__pycache__/*"],
            capture_output=True, text=True, timeout=10,
        )
        test_files = []
        for line in t.stdout.strip().split("\n"):
            if not line.strip():
                continue
            rel = _normalize_target(line, project_root)
            if rel:
                test_files.append(rel)
        test_files = sorted(set(test_files))
        if test_files:
            tests_context = (
                "\nEXISTING TEST FILES (these tests ALREADY EXIST — do "
                "NOT propose 'add tests for X' if a test file for X is "
                "here; instead look for GAPS: a source file with NO "
                "matching test):\n"
                + "\n".join(f"  {x}" for x in test_files[:40])
                + "\n")
    except Exception:
        pass

    prompt = f"""Analyze this Python codebase and identify 3-5 improvement tasks.

{workspace_context}{git_context}{tests_context}
Real source files (relative to project root — cite these EXACT paths in
target_files, do NOT invent files that are not listed here):
{chr(10).join(files[:30])}

For each task provide JSON:
{{
  "description": "what to do",
  "target_files": ["one-of-the-files-listed-above.py"],
  "acceptance_criteria": "how to verify",
  "priority": 1-10,
  "risk": "low/medium/high",
  "persona": "which persona should handle this"
}}

Focus on, in this ORDER of value:
  1. ACTUAL DEFECTS: unhandled exceptions, None dereference, off-by-one,
     resource leaks, race conditions, wrong conditionals — a concrete
     input that produces a wrong/crashed result.
  2. SECURITY: unvalidated input, secrets in code, unsafe eval/exec.
  3. Only then: documentation, style.

RULES:
- Every task MUST cite real target_files from the source list above.
- (30/09, PROVADO por teste decisivo) O modelo ACERTA bug de 1 linha com
  grounding completo (typo, None-deref pontual — old_text exato,
  new_text certo). O que ele NÃO converge é task AUTO-REFERENCIAL ou
  ambígua: "add test coverage" (o modelo escreve o teste E o contrato,
  que pode não bater com o código) e "add type hints/docstrings"
  (sem resposta única, nada a verificar). 5 ciclos noturnos: 0/31 de
  convergência, e praticamente TODAS as tasks eram dessas duas famílias.
  => NÃO proponha "add test", "add type hints", "add docstrings",
  "improve coverage", "add documentation". São tarefas sem resposta
  única.
  Se a sua análise é real e based no código, o QUE ela propõe é um
  DEFETO (1), não meta-trabalho (add-test/doc). Sem defeito real?
  Devolva [].
- Do NOT propose work that is already done: if a test file for the
  module already exists, do not "add tests"; if the function already
  has type hints/docstrings, do not "add type hints/docstrings".
- AVOID large speculative refactors ("consolidate X", "extract Y",
  "restructure Z"). They are ambiguous, they break working code, and
  they are hard to verify. Prefer a SMALL, DEFINITE defect fix that
  you can point at with exact lines.
- If you find no real defects, return an empty array [] — that is a
  valid, useful answer. Do not invent work to fill the list.

Return JSON array."""

    # Call LLM with timeout protection. 300s: prefill de prompt
    # grande no Bonsai-GPU pode passar de 120s; timeout curto gerava
    # loop de "LLM timeout" a noite inteira (observado 2026-09-11:
    # retries a cada ~8min por 8h). Uma retentativa, depois desiste
    # com honestidade (não loop infinito).
    import concurrent.futures
    response = ""
    last_err: str | None = None
    for attempt in (1, 2):
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(call_llm_fn, prompt, 1500)
                response = future.result(timeout=300)
            last_err = None
            break
        except concurrent.futures.TimeoutError as e:
            last_err = f"timeout@{attempt}"
            print(f"[discovery] LLM timeout (attempt {attempt}/2) — retrying once",
                  file=sys.stderr)
        except Exception as e:
            print(f"[discovery] LLM error: {e}", file=sys.stderr)
            return []
    if last_err is not None:
        print("[discovery] LLM timeout twice — skipping LLM discovery",
              file=sys.stderr)
        return []

    tasks = []
    try:
        items = _extract_json_array(response)
        if not items:
            print(f"[discovery] sem array parseável "
                  f"({len(response)} chars)", file=sys.stderr)
        else:
            for i, item in enumerate(items):
                # LLM may return strings or dicts
                if isinstance(item, str):
                    tasks.append(Task(
                        id=f"disc-{int(time.time())}-{i}",
                        project=project,
                        description=item,
                        priority=5,
                        risk="low",
                        status=TaskStatus.READY.value,
                        # (30/09) LLM que devolve só string não diz qual
                        # arquivo mexer → task inaplicável pro patch loop.
                        # target_files fixo no único arquivo que o harness
                        # sempre tem à mão (o próprio fonte) seria falsificar
                        # a task; melhor deixar o filtro de execução lidar.
                    ))
                elif isinstance(item, dict):
                    # (30/09) resolve target_files do LLM p/ paths
                    # realmente acionáveis (basename-match + validação).
                    targets = _resolve_llm_targets(
                        item.get("target_files", []),
                        project_root=project_root,
                        known_files=rel_files,
                    )
                    if not targets:
                        # task sem alvo acionável = task de review, não de
                        # patch. Não entra na fila (o filtro de execução
                        # também pegaria, mas melhor não encher a fila).
                        continue
                    # (30/09, teste decisivo) Filtro de task AUTO-REFERENCIAL
                    # (defesa em profundidade — não confia só no prompt).
                    # "add test/docstring/type hints" não converge (5 ciclos
                    # noturnos: 0/31, e quase toda task era dessa família).
                    # Proof: o MESMO modelo acerta bug de 1 linha com o
                    # grounding completo. O que falha é a task sem resposta
                    # única — meta-trabalho, não defeito. Não entra na fila.
                    _desc = (item.get("description", "") or "").lower()
                    if _is_meta_task(_desc):
                        continue
                    tasks.append(Task(
                        id=f"disc-{int(time.time())}-{i}",
                        project=project,
                        description=item.get("description", ""),
                        target_files=targets,
                        acceptance_criteria=item.get("acceptance_criteria", ""),
                        priority=item.get("priority", 5),
                        risk=item.get("risk", "low"),
                        status=TaskStatus.READY.value,
                    ))
    except (json.JSONDecodeError, ValueError):
        pass

    return tasks


# ═══════════════════════════════════════════════════════════════════════════════
# File Editing (via Patcher + SafeEditor)
# ═══════════════════════════════════════════════════════════════════════════════

def _sudo_systemctl(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """(30/09) systemctl via sudo que FUNCIONA dentro do serviço systemd.

    Diagnóstico (a run travava dormindo achando que o MoE subia): o
    PATH do `nightwatch.service` é `/run/current-system/sw/bin`, onde o
    `sudo` é symlink pro binário do Nix store — **sem bit setuid**.
    Invocado de lá, o sudo morre com:
        sudo: .../sw/bin/sudo deve ter como dono o uid 0 e tem definido
        o bit setuid
    No shell do dono funciona porque `/run/wrappers/bin` (o wrapper
    setuid) vem PRIMEIRO no PATH. Como o harness usava
    `capture_output=True` sem checar returncode, o erro era engolido e
    o nightwatch só dormia no loop de espera.

    Aqui: (a) usa o wrapper setuid (/run/wrappers/bin) explícito,
    independente de como o nightwatch foi iniciado; (b) `-n`
    (non-interactive) — serviço não tem TTY, e o sudo sem -n no restore
    reclamava de "contêiner/sem terminal" (rc=1); (c) NÃO engole o erro
    — loga o returncode/stderr. O silêncio foi o que escondeu o bug.
    """
    env = dict(os.environ)
    wrapper = "/run/wrappers/bin"
    parts = env.get("PATH", "").split(":")
    if wrapper not in parts:
        env["PATH"] = f"{wrapper}:{env.get('PATH', '')}"
    r = subprocess.run(["sudo", "-n", "systemctl", *args],
                       capture_output=True, timeout=timeout, env=env)
    if r.returncode != 0:
        print(f"[nightwatch] sudo systemctl {' '.join(args)} FALHOU "
              f"rc={r.returncode}: {r.stderr.decode(errors='replace').strip()[:200]}")
    return r


def _target_is_actionable(target: str) -> bool:
    """(30/09) Um target só é 'de patch' se for um ARQUIVO real (patch) ou
    um path limpo de arquivo novo (CREATE).

    Os geradores de task alimentavam target_path com DESCRIÇÃO em prosa,
    não caminho: 'Todos os módulos que usam `config...`', '`AGENTS.md`,
    `HANDOFF.md`' (backticks + vírgula), 'modules/.../core/' (diretório).
    _read_file_for_llm devolvia ERROR → task virava 'CREATE candidate' →
    o modelo criava um arquivo chamado 'Todos os módulos...' → falha.

    Regras (conservadoras — na dúvida, deixa passar, o safe_editor é a
    última rede):
      - resolve pra arquivo existente E legível  → PATCH
      - não existe mas parece path de código
        (sem espaços/prosa, tem extensão de código) → CREATE
      - diretório / prosa / não-arquivo           → não acionável
    """
    try:
        t = (target or "").strip()
        if not t:
            return False
        # resolve path
        full = Path(t) if t.startswith("/") else _resolve_file_path(t)
        if full.is_file():
            return True
        if full.is_dir():
            return False  # diretório não é alvo de patch
        # não existe: CREATE válido só se PARECE caminho de código
        # (sem espaços, sem vírgula-lista, extensão conhecida)
        if any(ch.isspace() for ch in t) or "," in t or "`" in t:
            return False
        if t.endswith("/"):
            return False
        ext = Path(t).suffix.lower()
        return ext in {".py", ".md", ".nix", ".json", ".yaml", ".yml",
                       ".toml", ".sh", ".txt", ".cfg", ".ini"}
    except Exception:
        return False


def _normalize_target(raw: str, project_root: Path | None = None) -> str:
    """(30/09) Limpa um target_file que o LLM devolveu para um path
    relativo-usável pelo patch loop.

    O LLM costuma devolver o path ABSOLUTO (o `find` do discovery lista
    absolutos) ou com crase/aspas/vírgula. O patch loop resolve
    relativo ao project root. Aqui: tira crase/aspas/ vírgula, corta
    qualquer prefixo absoluto até o project root, e devolve relativo.
    Devolve "" se não sobrar nada utilizável.
    """
    if not raw:
        return ""
    # split por vírgula ANTES de tirar aspas: '"A.md", "B.md"' -> 'A.md'
    t = str(raw).split(",")[0].strip().strip("`'\" ")
    if not t:
        return ""
    root = str(project_root or find_repo_root())
    # se o path é absoluto e está sob o root, vira relativo
    if t.startswith(root):
        t = t[len(root):]
    t = t.lstrip("/")
    return t


_META_VERB = r"(?:add|write|create|improve|increase|update|ensure|include|document|cover)"
_META_NOUN = r"(?:tests?|testing|docstrings?|type\s*hints?|documentation|coverage|comments?|readme)"
_META_TASK_RE = re.compile(
    # verbo de meta-trabalho seguido (até 60 chars) do alvo de meta-trabalho
    rf"\b{_META_VERB}\b.{{0,60}}?\b{_META_NOUN}\b"
    # ou: "all/every source modules have/have matching tests"
    r"|\b(?:all|every)\b.{0,30}\b(?:source|module)s?\b.{0,30}"
    r"\b(?:have|has|with|matching|corresponding)\b.{0,20}\btests?\b"
    # ou o alvo vem primeiro: "test coverage for X", "testing gaps"
    rf"|\b{_META_NOUN}\b.{{0,30}}\b(?:for|across|in|of)\b"
)


def _is_meta_task(description: str) -> bool:
    """(30/09) Task AUTO-REFERENCIAL/ambígua que o patch loop não converge.

    Medido em 5 ciclos noturnos (convergência 0/31): quase toda task era
    "add test coverage" / "add type hints and docstrings" / "ensure all
    files have tests". São meta-trabalho — o modelo escreve o teste E o
    contrato (que pode não bater com o código), ou "add docstring" não
    tem resposta única. Não há resposta certa dentro, logo não converge.

    Prova de que NÃO é limitação do modelo: o MESMO modelo, com o MESMO
    grounding, ACERTA um bug de 1 linha (old_text exato, new_text certo).
    O que não converge é a task sem resposta única.

    Devolve True se a descrição for meta-trabalho (e deve ser filtrada).
    """
    return bool(_META_TASK_RE.search(description or ""))


def _resolve_llm_targets(raw_targets, project_root: Path | None = None,
                         known_files: list[str] | None = None) -> list[str]:
    """(30/09) Converte o `target_files` que o LLM devolveu em paths
    REAIS (arquivos que existem, patcháveis), resolvendo por basename
    quando o LLM gave um nome solto.

    Sem isso o LLM inventa path ("src/utils.py" que não existe) e a task
    morre no patch loop (o motivo do "No readable target files").

    IMPORTANTE (por que NÃO reusamos _target_is_actionable aqui): aquela
    função aceita path inexistente com extensão de código como CREATE
    válido. Pra discovery isso é Errado — task de discovery é "melhore
    código que EXISTE"; aceitar path inventado como CREATE faria o modelo
    criar um arquivo que ninguém pediu. Então exigimos arquivo EXISTENTE:
      1. normaliza → é arquivo real? aceita.
      2. senão casa por basename contra os arquivos conhecidos (o LLM às
         vezes devolve só "agent.py") → aceita o path completo.
      3. senão descarta (path inventado = task de review, não de patch).
    """
    if isinstance(raw_targets, str):
        raw_targets = [raw_targets]
    if not raw_targets:
        return []
    known = known_files or []
    root = project_root or find_repo_root()
    out: list[str] = []

    def _exists_file(p: str) -> bool:
        full = Path(p) if p.startswith("/") else (root / p)
        return full.is_file()

    for raw in raw_targets:
        cand = _normalize_target(raw, root)
        if not cand:
            continue
        if _exists_file(cand):
            out.append(cand)
            continue
        # casa por basename contra os arquivos conhecidos
        base = Path(cand).name
        for kf in known:
            if Path(kf).name == base:
                out.append(kf)
                break
    # dedupe preservando ordem
    seen = set()
    uniq = []
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _extract_failed_tests(validation) -> set[str]:
    """(30/09) Nomes dos testes que falharam, extraídos do output pytest.

    Procura linhas do short-summary do pytest: "FAILED path::test_name - …"
    e devolve o par (arquivo::teste) para comparar com o baseline.
    """
    import re as _re
    out: set[str] = set()
    for step in getattr(validation, "steps", []):
        for m in _re.finditer(r"^FAILED\s+(\S+)", step.output or "", _re.M):
            out.add(m.group(1))
    return out


def _pre_patch_test_baseline(applied_files: list[str]) -> set[str]:
    """(30/09, Lição 1) Testes que JÁ FALHAVAM antes do patch.

    O nightwatch roda o teste só DEPOIS de aplicar o patch, e reprova se
    qualquer teste falhar. Mas alguns testes falham por AMBIENTE (ex.:
    test_integration::test_llama_cpp_chat exige o LLM carregado). Medido:
    o padrão "2 passed, 2 failed" que o nightwatch via SEMPRE era esse
    teste de ambiente — o modelo era culpado por algo que não fez.

    Estratégia pragmática e HONESTA: capturamos o baseline na PRIMEIRA
    task do run (a branch ainda está limpa, o patch ainda não foi
    aplicado) e reaproveitamos nas demais. Falhas de ambiente são
    constantes durante o run (mesmo LLM, mesmo config). Assim:
      - 1ª task: baseline = testes que já falham agora (patch não aplicado)
      - 2ª+ tasks: baseline reaproveitado
    Só conta falha cujo teste NÃO é sobre o arquivo mudado (ou seja, é
    de ambiente: import/rede/LLM — independe do patch).

    Best-effort: erro aqui devolve set() (não piora — só não dá o
    benefício da dúvida).
    """
    # usa o baseline capturado neste run, se houver
    cached = getattr(_pre_patch_test_baseline, "_cache", None)
    if cached is not None:
        return cached
    if not applied_files:
        return set()
    try:
        from nightwatch.validator import run_targeted_tests
        report = run_targeted_tests(applied_files)
        failed: set[str] = set()
        if not report.passed:
            for step in report.steps:
                for line in (step.output or "").splitlines():
                    if line.startswith("FAILED "):
                        failed.add(line.split()[1])
        # só guarda como baseline se for falha de AMBIENTE (o teste não é
        # sobre nenhum arquivo que o patch mexeu) — se o teste é sobre o
        # arquivo mudado, pode ser falha real do patch, não baseline.
        changed = {Path(f).stem for f in applied_files}
        env_failures = {
            t for t in failed
            if not any(Path(t).stem.replace("test_", "") in c or c in Path(t).stem
                       for c in changed)
        }
        _pre_patch_test_baseline._cache = env_failures
        return env_failures
    except Exception:
        return set()


def _ground_failure(pytest_output: str) -> str:
    """(30/09, C5-pre) Anexa ao erro o ARQUIVO DE TESTE que reprovou.

    Medido: o harness entregava ao retry só o traceback `--tb=short`
    (file:line + a asserção + o erro). O modelo via `AssertionError:
    expected 3 tiers, got 2` mas NÃO via **o que o teste exige** — o
    arquivo de teste inteiro, nem o código-fonte ao redor da linha que
    falhou. Ou seja: ele sabe onde quebrou, mas não qual é o CONTRATO
    que o código deve satisfazer. É informação que o harness tem e não
    entregava — o mesmo padrão dos fixes anteriores.

    Parseia o traceback, acha o primeiro `...test_arquivo.py:N:` (a
    linha que falhou) e anexa: (a) as linhas do teste em volta do
    assert, (b) o código-fonte ao redor da linha N. Best-effort: se não
    parsear, devolve "" (não quebra o retry).
    """
    import re as _re
    if not pytest_output:
        return ""
    root = find_repo_root()
    # A linha "X.py:N: in test_nome" dá o ponto de falha. O pytest --tb=short
    # JÁ mostra a linha do assert (a que começa com "E ") — o que falta é o
    # CONTEXTO ao redor (o resto do teste + o código-fonte). É isso que
    # entregamos abaixo.
    m = _re.search(r"([\w./-]+\.py):(\d+): in ", pytest_output)
    if not m:
        return ""
    file_ref, lineno = m.group(1), int(m.group(2))
    grounded = ["\n[GROUNDING — o que o harness tem e nao te entregou antes]"]
    # (a) o arquivo de TESTE, linhas em volta da que falhou
    try:
        tp = Path(file_ref) if file_ref.startswith("/") else root / file_ref
        if tp.is_file():
            tlines = tp.read_text(encoding="utf-8", errors="replace").splitlines()
            lo = max(0, lineno - 8)
            snippet = "\n".join(
                f"{i+1:>4}| {tlines[i]}" for i in range(lo, min(len(tlines), lineno + 4))
            )
            grounded.append(f"\nArquivo de teste que REPROVOU (em volta da linha {lineno}):\n{snippet}")
            # a função de teste completa (contrato)
            _re_func = _re.search(r"def\s+(test_\w+)", pytest_output)
            if _re_func:
                fname = _re_func.group(1)
                for i, L in enumerate(tlines):
                    if L.strip().startswith(f"def {fname}"):
                        j = i + 1
                        while j < len(tlines) and not (
                            tlines[j].strip().startswith("def ") or
                            (tlines[j].strip() and not tlines[j].startswith((" ", ")", "\t")))
                        ):
                            j += 1
                        grounded.append(
                            f"\nO que o teste {fname} exige (corpo completo):\n"
                            + "\n".join(tlines[i:j])[:1500])
                        break
    except Exception:
        pass
    # (b) o código-fonte em volta da linha que falhou (se for arquivo-fonte)
    try:
        sp = Path(file_ref) if file_ref.startswith("/") else root / file_ref
        if sp.is_file():
            slines = sp.read_text(encoding="utf-8", errors="replace").splitlines()
            lo = max(0, lineno - 6)
            snippet = "\n".join(
                f"{i+1:>4}| {slines[i]}" for i in range(lo, min(len(slines), lineno + 6))
            )
            grounded.append(f"\nCódigo em volta da linha {lineno} de {file_ref}:\n{snippet}")
    except Exception:
        pass
    return "\n".join(grounded) if len(grounded) > 1 else ""


def _read_file_for_llm(path: str, max_chars: int = 0, task_description: str = "") -> str:
    """Read a file for LLM context, with path resolution.

    Args:
        path: File path (absolute or relative to project root)
        max_chars: Max chars to read (0 = auto-detect from context budget)
        task_description: Used to extract relevant section for large files
    """
    try:
        if path.startswith("/"):
            full_path = Path(path)
        else:
            full_path = _resolve_file_path(path)

        if not full_path.exists():
            return f"ERROR: File not found: {path}"

        content = full_path.read_text(encoding="utf-8")

        # Auto-detect truncation from context budget if not specified
        if max_chars <= 0:
            # llama-server -c 4096 means ~4K tokens total.
            # Prompt overhead (system + format instructions): ~600 tokens ≈ 2400 chars.
            # Response reserve: ~500 tokens ≈ 2000 chars.
            # Safe budget for file content: ~2900 tokens ≈ 11500 chars.
            # Aider sends whole file for small files, relevant section for large.
            max_chars = 11000

        if len(content) > max_chars:
            # For large files, try to extract the section around the target function.
            # This is what Aider does — send relevant context, not the whole file.
            content = _extract_relevant_section(content, path, max_chars, task_description)

        return content
    except Exception as e:
        return f"ERROR: Could not read {path}: {e}"


def _extract_relevant_section(content: str, path: str, max_chars: int, task_description: str = "") -> str:
    """Extract the most relevant section of a large file.
    
    Strategy: send only imports + the function being edited + immediate context.
    For 'add new function' tasks, send imports + end of file.
    Falls back to first max_chars if no structure found.
    """
    lines = content.split('\n')
    
    # Find imports (first ~20 lines that start with import/from/#)
    import_end = 0
    for i, line in enumerate(lines[:30]):
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from ') or stripped.startswith('#') or stripped == '':
            import_end = i + 1
        else:
            break
    imports = '\n'.join(lines[:import_end]) if import_end > 0 else '\n'.join(lines[:10])
    
    # Find function/class definitions with their line numbers
    definitions = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('def ') or stripped.startswith('class '):
            definitions.append((i, stripped[:60]))
    
    if not definitions:
        return content[:max_chars]
    
    # Try to find the function mentioned in the task description
    task_lower = task_description.lower()
    target_section = ""
    target_func_name = ""

    def _name_variants(fname: str) -> set[str]:
        # (30/09, C3) task diz "cmd_metrics", def diz "_cmd_metrics" —
        # o match exato falhava e caía no head (que não contém a
        # função). Compara sem o underscore à esquerda, e também sem
        # prefixos comuns (_cmd_, cmd_, handler_, on_).
        base = fname.lower()
        stripped = base.lstrip("_")
        variants = {base, stripped}
        for p in ("cmd_", "handler_", "on_", "handle_"):
            if stripped.startswith(p):
                variants.add(stripped[len(p):])
        if base.startswith("cmd_"):
            variants.add("_" + base)
        return {v for v in variants if v}

    # 30/09: mede qual função casa melhor (match mais longo = menos
    # chance de colidir com palavra genérica).
    best: tuple[int, int, str, str] | None = None  # (len, def_line, name, body)
    for i, (def_line, def_text) in enumerate(definitions):
        fname = def_text.split('(')[0].split(':')[0].replace('def ', '').replace('class ', '').strip()
        if not fname:
            continue
        for v in _name_variants(fname):
            if v and v in task_lower:
                end_line = definitions[i+1][0] if i+1 < len(definitions) else len(lines)
                body = '\n'.join(lines[def_line:end_line])
                cand = (len(v), def_line, fname, body)
                if best is None or cand[0] > best[0]:
                    best = cand
                break
    if best:
        target_func_name = best[2]
        target_section = best[3]
    
    # If task mentions adding something new (not editing existing),
    # send imports + last function + the function it calls (if any)
    if not target_section:
        # (30/09, C3-classificado) Causa (c) = contexto insuficiente.
        # Quando a task NÃO nomeia função, o fallback antigo mandava só
        # "imports + ÚLTIMA função" — uma fatia arbitrária minúscula. Num
        # arquivo grande (cli/main.py = 73k chars), o modelo recebia ~870
        # chars e escrevia old_text a partir dessa lasca → "Hunk not
        # found" garantido. Medido: 84x menor que o arquivo real.
        # Agora, sem função-alvo identificada, mandamos um trecho
        # substancial (até max_chars) a partir do topo — imports +
        # começo do código real, que é onde o modelo costuma trabalhar.
        head = '\n'.join(lines[: max(1, max_chars // 40)])  # ~25% do budget em linhas
        target_section = head
        if len(target_section) < max_chars:
            # completa com o resto do arquivo até max_chars, pra maximize
            # a chance do old_text casar com alguma coisa real
            more_needed = max_chars - len(target_section)
            used_lines = len(target_section.split('\n'))
            target_section += '\n' + '\n'.join(lines[used_lines:used_lines + more_needed // 40])
        # 'correct' handling só faz sentido agora sobre o head, mas o
        # modelo montava contexto próprio; mantém simples.

    # Budget: imports + target function, fit within max_chars
    # (30/09) Budget generoso pro target_section: a regra #1 do patch loop
    # é o old_text casar com o arquivo REAL. Cortar demais garante falha.
    # Damos ~2/3 ao target e ~1/3 aos imports.
    budget_imports = max(200, max_chars // 3)
    budget_target = max_chars - budget_imports
    imports = imports[:budget_imports]

    # (30/09, C3) Se achamos a função-alvo, anexa o resto do arquivo
    # (a partir dela, até o budget) como contexto adicional. Sem isso o
    # modelo recebe SÓ a função e, se escrever um old_text que inclua
    # linhas vizinhas (dispatcher, decorators), não casa. Mais contexto
    # real = mais chance do old_text bater.
    if target_func_name and len(target_section) < budget_target:
        try:
            idx = lines.index(target_section.split('\n')[0])
        except ValueError:
            idx = 0
        remaining = lines[idx + len(target_section.split('\n')):]
        filler = '\n'.join(remaining)
        target_section = (target_section + "\n\n# ... [continuação do arquivo] ...\n\n"
                          + filler)[:budget_target]

    target_section = target_section[:budget_target]

    result = f"{imports}\n\n# ... [file middle omitted] ...\n\n{target_section}"
    return result[:max_chars]


def _resolve_file_path(path: str) -> Path:
    """Resolve a file path to an absolute path.

    Tries multiple strategies:
    1. Absolute path as-is
    2. Relative to the active project root
    3. With common source prefixes stripped
    4. Glob search in project
    """
    project_root = find_repo_root()

    if path.startswith("/"):
        return Path(path)

    # Try direct relative to project root
    direct = project_root / path
    if direct.exists():
        return direct

    # Try with common prefixes stripped
    for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/", "src/"]:
        if path.startswith(prefix):
            stripped = path[len(prefix):]
            for base in [project_root / "modules/ai/jarvis/src", project_root]:
                candidate = base / stripped
                if candidate.exists():
                    return candidate

    # Fallback: search in project
    import subprocess
    try:
        result = subprocess.run(
            ["find", str(project_root), "-name", Path(path).name, "-type", "f"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n"):
            if line and Path(line).exists():
                return Path(line)
    except Exception:
        pass

    return project_root / path  # Return best guess


def _request_json_patch(
    task_description: str,
    file_contents: dict[str, str],
    previous_errors: list[str] | None = None,
) -> tuple[bool, list, list[str]]:
    """Patch via grammar JSON (determinístico) — antes do texto livre.

    Evidência (forense 2026-09-12): Bonsai falha 3 modos no formato
    === (cercas, truncamento, sem wrapper) mas tem 35/35 em JSON com
    grammar. JSON parseia sempre; o risco restante é só o conteúdo
    (old_text inexato → apply falha honesto, não parse).
    """
    from nightwatch.patcher import FilePatch, PatchHunk
    schema = {"response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "patches",
            "schema": {
                "type": "object",
                "properties": {
                    "patches": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "path": {"type": "string"},
                                "old_text": {"type": "string"},
                                "new_text": {"type": "string"},
                            },
                            "required": ["path", "old_text",
                                         "new_text"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["patches"],
                "additionalProperties": False,
            },
        },
    }}
    files_bit = "\n\n".join(
        f"=== FILE: {p} ===\n```python\n{c}\n```"
        for p, c in list(file_contents.items())[:3])
    # (30/09, C3b) Duas correções de harness, ambas custo zero de tokens
    # e ambasMirror da falha real 'unindent does not match' (a run 16:45
    # perdeu 3 tentativas no MESMO ponto, linha 126 de ast_cache.py):
    #
    # 1) NÃO truncar em c[:4000]. O corte caía no meio de um bloco
    #    indentado, e o modelo via hierarquia quebrada —然后 reescrevia
    #    o bloco com indent inconsistente. A regra do patch loop é o
    #    old_text casar com o arquivo REAL; mandar o arquivo INTEIRO
    #    (o budget ctx-derived já limita) maximiza a chance.
    # 2) Dizer explicitamente que a indentação é sagrada + exemplo. O
    #    modelo não erra por não saber Python, erra por re-indentar ao
    #    "otimizar". O harness deve dizer isso.
    # (30/09, C5-pre) O caminho JSON (grammar) é o que o nightwatch SEMPRE
    # usa (o de texto livre nunca é alcançado). Ele não recebia
    # previous_errors — então o traceback que a gente passou a montar
    # NUNCA chegava ao modelo no retry grammar. O loop RHO estava cego
    # justamente no caminho que ele roda. Agora o erro entra aqui.
    error_section = ""
    if previous_errors:
        error_section = (
            "\n\n⚠️ PREVIOUS ATTEMPT FAILED — read the actual failure "
            "below, do NOT repeat it:\n"
            + "\n".join(f"  - {e[:2500]}" for e in previous_errors[-3:])
            + "\n\nFix the ROOT CAUSE shown in the failure output, not the "
              "symptom.\n"
        )
    prompt = (
        f"TASK: {task_description}\n\nFILES:\n{files_bit}\n\n"
        f"{error_section}"
        "RULES:\n"
        "1. old_text MUST be copied character-for-character from the "
        "file above, INCLUDING exact leading whitespace/indentation.\n"
        "2. new_text MUST use the SAME indentation as old_text unless "
        "you are deliberately changing nesting — keep every line at its "
        "current indent level.\n"
        "3. Make the SMALLEST change that accomplishes the task. Do NOT "
        "rewrite surrounding lines, do NOT reflow indentation.\n"
        "4. If old_text has a line indented 12 spaces, every line you "
        "keep around it keeps those 12 spaces.\n\n"
        "EXAMPLE (correct - note indentation preserved):\n"
        '{"patches":[{"path":"a.py","old_text":"def f():\\n'
        '    if x:\\n        return 1","new_text":"def f():\\n'
        '    if x:\\n        return 2"}]}\n\n'
        "Return small hunks (<=15 lines each). If no change needed, "
        "return "
        '{"patches": []}.')
    try:
        from jarvis.providers.llm import LLMClient
        from jarvis.core.config import Config
        import time as _t
        print("[patcher] json-patch start (grammar)", file=sys.stderr)
        _t0 = _t.monotonic()
        # max_tokens 29/09 (bug real, dono 19/09 já tinha o mecanismo):
        # 1024 TRUNCAVA o JSON da gramática sempre no mesmo ponto
        # ("Unterminated string at char 2159"). Grammar limita forma, não
        # tamanho. Mas 4096 hardcoded seria OUTRO chute no mesmo buraco —
        # a fonte de verdade é o ctx do models.nix, e o helper que traduz
        # ctx → budget POR TURNO (`ctx//12`, com piso) já existe em
        # core/agent.py e é usado pelo Agent. O nightwatch herda dele:
        # mesmo modelo, mesmo orçamento, sem número mágico local.
        try:
            from jarvis.core.context_budget import ctx_derived_max_tokens
            from jarvis.core.config import get_config as _gc
            from jarvis.core.model_registry import ModelRegistry as _MR
            _e = _MR.load().get(_gc().llm_model)
            _ctx = (_e.raw or {}).get("ctx") if _e else None
            _mt = max(4096, ctx_derived_max_tokens(_ctx))
        except Exception:
            _mt = 4096
        print(f"[patcher] json-patch budget={_mt} (ctx-derived, piso 4096)",
              file=sys.stderr)
        resp = LLMClient(Config()).chat_with_tools(
            messages=[
                {"role": "system",
                 "content": "You emit patch JSON only."},
                {"role": "user", "content": prompt}],
            temperature=0.0,
            max_tokens=_mt,
            extra=schema,
        )
        print(f"[patcher] json-patch done in {_t.monotonic() - _t0:.1f}s",
              file=sys.stderr)
        raw = resp.content or ""
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        out = []
        for item in data.get("patches", []):
            fp = FilePatch(path=item.get("path", ""))
            fp.hunks.append(PatchHunk(
                old_text=item.get("old_text", ""),
                new_text=item.get("new_text", "")))
            out.append(fp)
        return True, out, []
    except Exception as e:
        print(f"[patcher] json-patch falhou ({e}); fallback texto",
              file=sys.stderr)
        return False, [], [f"json-patch: {e}"]


def _request_structured_patch(
    task_description: str,
    target_files: list[str],
    call_llm_fn: Callable,
    previous_errors: list[str] | None = None,
) -> tuple[bool, list, list[str]]:
    """Request structured patches from the LLM (old_text → new_text).

    Returns (success, list[FilePatch], errors).
    This is the SAFE path — LLM returns hunks, not full files.

    If previous_errors is provided (from a prior failed attempt), the errors
    are injected into the prompt so the LLM can learn from its mistakes
    instead of repeating them. This is the critical feedback loop that
    prevents infinite retry loops.
    """
    from nightwatch.patcher import parse_llm_patch, FilePatch

    # Read target files (full content for context, but LLM returns patches)
    file_contents = {}
    missing_files = []
    for path in target_files:
        content = _read_file_for_llm(path, task_description=task_description)
        if content.startswith("ERROR"):
            # File doesn't exist — treat as CREATE candidate
            missing_files.append(path)
        else:
            file_contents[path] = content

    if not file_contents and not missing_files:
        return False, [], ["No readable target files"]

    files_section = "\n\n".join(
        f"=== FILE: {path} ===\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    # Tell LLM about missing files (candidates for CREATE)
    if missing_files:
        files_section += "\n\nFILES THAT DO NOT EXIST (create them):\n"
        files_section += "\n".join(f"  - {p}" for p in missing_files)

    # Inject recovery context if available
    recovery_ctx = ""
    try:
        from nightwatch.checkpoint import generate_recovery_summary
        _proj_name = find_repo_root().name or "nixos-ai"
        recovery_ctx = generate_recovery_summary(project=_proj_name)
    except Exception:
        pass

    # Inject episodic memory lessons from past failures
    memory_ctx = ""
    try:
        from nightwatch.memory_bridge import recall_relevant_lessons
        lessons = recall_relevant_lessons(task_description, top_k=3)
        if lessons:
            memory_ctx = "\n\nLESSONS FROM PAST FAILURES:\n"
            for i, lesson in enumerate(lessons, 1):
                memory_ctx += f"  {i}. {lesson['error_pattern'][:200]}\n"
                if lesson.get('fix'):
                    memory_ctx += f"     Fix: {lesson['fix'][:200]}\n"
    except Exception:
        pass

    error_section = ""
    if previous_errors:
        # (30/09, C3b-2) Truncava em 300 chars — cortava justamente o
        # traceback do teste que acabamos de começar a entregar. O sinal
        # é o que faz o retry aprender; cortar o sinal é o equivalente a
        # retry às cegas. 2500 chars cabem no budget sem estourar.
        error_section = (
            "\n\n⚠️ PREVIOUS ATTEMPT FAILED — DO NOT REPEAT THESE ERRORS:\n"
            + "\n".join(f"  - {e[:2500]}" for e in previous_errors[-3:])
            + "\n\nAnalyze why the previous patches failed (read the actual "
              "test failure above) and produce corrected patches. Fix the "
              "ROOT CAUSE shown in the traceback, not the symptom."
        )

    total_chars = sum(len(c) for c in file_contents.values())
    use_whole = 0 < total_chars < 6000 and len(file_contents) <= 3

    if use_whole:
        format_block = """To MODIFY a file, return its COMPLETE new content:
=== WHOLE: path/to/file.py ===
REASON: why this change is needed
--- content ---
complete updated file content here
--- end ---

To CREATE a new file, use:
=== CREATE: path/to/new_file.py ===
REASON: why this file is needed
--- content ---
full file content here
--- end ---

RULES:
- Return the COMPLETE file content, not just the changed part
- Preserve everything you are not changing, byte for byte
- Return only files that need changes. If no changes needed, return "NO_CHANGES"."""
    else:
        format_block = """To MODIFY an existing file, use:
=== FILE: path/to/file.py ===
REASON: why this change is needed
--- old text ---
exact text to find (must match exactly)
--- new text ---
replacement text
--- end ---

To CREATE a new file, use:
=== CREATE: path/to/new_file.py ===
REASON: why this file is needed
--- content ---
full file content here
--- end ---

RULES:
- old text MUST be an exact substring of the file
- NEVER echo whole files: each hunk ≤15 lines, copied character-for-character
- Small hunks apply reliably; big echoes NEVER match — prefer 3 small hunks over 1 big
- To CREATE: use --- content --- with the full file content
- You can have multiple hunks per file
- Return only files that need changes. If no changes needed, return "NO_CHANGES"."""

    prompt = f"""Improve this code for the given task.

{recovery_ctx + chr(10) + chr(10) if recovery_ctx else ""}{memory_ctx + chr(10) if memory_ctx else ""}{error_section}TASK: {task_description}

FILES:
{files_section}

{"\n\n⚠️ The following files DO NOT EXIST yet. The task requires creating them.\nYou MUST use the CREATE format below for these files.\n" + chr(10).join(f"  - {p}" for p in missing_files) + chr(10) if missing_files else ""}
{format_block}"""

    # Caminho 1 (determinístico): JSON com grammar ANTES do texto
    # (1 chamada LLM em vez de 2). Só usa se gerar ≥1 hunk com
    # old_text não-vazio; senão cai no texto livre abaixo.
    json_ok, json_patches, _ = _request_json_patch(
        task_description, file_contents, previous_errors=previous_errors)
    if json_ok and any(h.old_text.strip()
                       for p in json_patches for h in p.hunks):
        return True, json_patches, []

    response = call_llm_fn(prompt, 4096)

    if "ERROR" in response:
        return False, [], [response]

    if "NO_CHANGES" in response:
        # If files need creating, retry with a dedicated create prompt
        if missing_files:
            return _request_file_creation(task_description, missing_files, call_llm_fn)
        return True, [], []

    # Caminho 2 (legado): texto livre com parse tolerante.
    patches = parse_llm_patch(response)

    if not patches:
        try:
            from pathlib import Path as _Path
            dbg = _Path.home() / ".local/state/jarvis/nightwatch/last_patch_failure.txt"
            dbg.parent.mkdir(parents=True, exist_ok=True)
            dbg.write_text(response[:4000], encoding="utf-8")
        except Exception:
            pass
        return False, [], ["Could not parse any patches from LLM response"]

    return True, patches, []


def _request_file_creation(
    task_description: str,
    missing_files: list[str],
    call_llm_fn: Callable,
) -> tuple[bool, list, list[str]]:
    """Dedicated prompt for file creation when the main prompt returns NO_CHANGES.
    
    Uses a simpler, more direct prompt that the Qwen model can follow.
    """
    from nightwatch.patcher import parse_llm_patch, FilePatch

    files_list = "\n".join(f"  - {f}" for f in missing_files)
    prompt = f"""You must create the following files for this task:

TASK: {task_description}

FILES TO CREATE:
{files_list}

For EACH file, return:
=== CREATE: path/to/file.py ===
REASON: why this file is needed
--- content ---
full file content here
--- end ---

IMPORTANT: You MUST create these files. Return the full content for each file.
Do NOT return NO_CHANGES. The files do not exist yet."""

    response = call_llm_fn(prompt, 4096)

    if "ERROR" in response:
        return False, [], [response]

    if "NO_CHANGES" in response:
        return False, [], [f"LLM still returned NO_CHANGES for file creation of: {', '.join(missing_files)}"]

    patches = parse_llm_patch(response)
    if not patches:
        return False, [], ["Could not parse file creation patches from LLM response"]

    # Mark all patches as CREATE
    for p in patches:
        p.create = True

    return True, patches, []


# ═══════════════════════════════════════════════════════════════════════════════
# Git Operations
# ═══════════════════════════════════════════════════════════════════════════════

def _git_diff_stat() -> str:
    """Get git diff stat."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, timeout=10,
            cwd=str(find_repo_root()),
        )
        return result.stdout
    except Exception:
        return ""


def _git_commit(message: str) -> str | None:
    """Commit changes and return SHA."""
    try:
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, timeout=10,
            cwd=str(find_repo_root()),
        )
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=30,
            cwd=str(find_repo_root()),
        )
        if result.returncode == 0:
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=str(find_repo_root()),
            ).stdout.strip()
            return sha
    except Exception:
        pass
    return None


def _verify_completion_evidence(commit_sha: str | None,
                                applied_files: list[str] | None) -> tuple[bool, str]:
    """Veredito de evidência p/ fechar task (lição do UX-abismo).

    DONE só com: commit real (sha não-vazio) + ≥1 arquivo aplicado.
    Validator/review já passaram antes; isto impede o caso "complete
    sem artefato" (commit vazio, sha None, lista vazia).
    """
    if not commit_sha:
        return False, "sem commit (sha vazio)"
    if not applied_files:
        return False, "sem arquivos aplicados"
    return True, ""


def _git_revert(files: list[str] | None = None) -> None:
    """Revert uncommitted changes.

    If files is provided, only revert those specific files.
    If files is None, revert ALL changes (dangerous — use with caution).
    """
    try:
        if files:
            # Revert only specific files
            for f in files:
                resolved = _resolve_file_path(f)
                if resolved.exists():
                    subprocess.run(
                        ["git", "checkout", "--", str(resolved)],
                        capture_output=True, timeout=10,
                        cwd=str(find_repo_root()),
                    )
        else:
            # Full revert — last resort
            subprocess.run(
                ["git", "checkout", "--", "."],
                capture_output=True, timeout=10,
                cwd=str(find_repo_root()),
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                capture_output=True, timeout=10,
                cwd=str(find_repo_root()),
            )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Progress Logging
# ═══════════════════════════════════════════════════════════════════════════════

def _log_progress(entry: dict) -> None:
    """Append a progress entry to the JSONL log."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Harness
# ═══════════════════════════════════════════════════════════════════════════════

class Harness:
    """Main harness orchestrator.

    Single entrypoint for all nightwatch operations.
    Integrates: TaskQueue, SafeEditor, Validator, Evaluator, Checkpoint, Safety.
    """

    def __init__(
        self,
        config: HarnessConfig | None = None,
        call_llm: Callable[[str, int], str] | None = None,
        send_telegram: Callable[[str], bool] | None = None,
    ):
        self.config = config or HarnessConfig()
        self.call_llm = call_llm or _default_call_llm
        self.send_telegram = send_telegram or _default_send_telegram
        self.queue = TaskQueue(project=self.config.project)
        self.editor = SafeEditor()
        self.checkpoint = Checkpoint.load(project=self.config.project)
        self.mission = self.queue.mission
        self.project_registry = ProjectRegistry()
        self.loop_detector = LoopDetector(
            max_attempts=self.config.loop_max_attempts,
            window_seconds=self.config.loop_window_seconds,
            project=self.config.project,
        )
        # Event Bus — use global bus so Control Plane receives harness events
        from jarvis.core.eventbus import get_bus
        self._bus = get_bus()
        self._bus.subscribe("harness.notify", self._handle_bus_notify, name="telegram")
        self._bus.subscribe("harness.task", self._handle_bus_log, name="jsonl_logger")
        # (30/09) início do run p/ retry consciente de orçamento (None =
        # execut_task chamado fora de run(), usa o max_retries cheio).
        self._run_started_at: float | None = None
        # (30/09, C5) métrica de convergência
        self._task_retried: bool = False
        self._retry_ok: int = 0
        # Auto-detect context size from llama.cpp server if not specified
        budget = self.config.context_budget
        if budget <= 0:
            server_ctx = query_server_context_size()
            if server_ctx > 0:
                budget = server_ctx
                self.notify(f"📊 Context: {budget:,} tokens (from server)")
            else:
                from jarvis.core.provider_registry import MIN_PROFILE_CONTEXT
                budget = MIN_PROFILE_CONTEXT
                self.notify(f"⚠️ Context: {budget:,} tokens (server unavailable, fallback)")
        self.context_budget = ContextBudget(
            max_tokens=budget,
            compaction_threshold=self.config.compaction_threshold,
        )
        # Auto-discover projects if none specified
        if not self.config.projects:
            self._discover_projects()
        # Auto-cleanup: prune terminal tasks and recover stuck tasks
        # This makes the queue self-managing for autonomous operation.
        pruned_terminals = self.queue.prune_completed(keep_last=20)
        if pruned_terminals > 0:
            self.notify(f"🧹 Pruned {pruned_terminals} old terminal tasks")
        pruned_stale = self.queue.prune_stale(max_age_seconds=3600)
        if pruned_stale > 0:
            self.notify(f"🧹 Pruned {pruned_stale} stale tasks from previous runs")
        recovered = self.queue.recover_stuck_tasks()
        if recovered > 0:
            self.notify(f"♻️ Recovered {recovered} stuck tasks")
        # Sweep leftover nightwatch/* branches from a crashed/killed prior run
        # Pass project root so external project branches are also cleaned
        project_root = find_repo_root()
        pruned = safety.prune_orphan_branches(project_root)
        if pruned > 0:
            self.notify(f"🧹 Pruned {pruned} orphaned nightwatch branches")
        # Sync past failures to episodic memory for future learning
        try:
            from nightwatch.memory_bridge import sync_to_episodic_memory
            sync_result = sync_to_episodic_memory(project=self.config.project, limit=50)
            if sync_result.get('synced', 0) > 0:
                self.notify(f"🧠 Synced {sync_result['synced']} lessons to episodic memory")
        except Exception:
            pass

    # ── Task Failure (with persistence) ───────────────────────────────────

    def _fail_task(self, task: Task, error: str) -> None:
        """Fail a task and persist the state immediately.
        
        This ensures the attempt count and status are saved to disk
        even if the harness crashes before the next _save() call.
        
        Also implements the 'rules ratchet': every failure becomes a rule
        that prevents the same mistake in future sessions.
        """
        task.fail(error)
        self.queue.update_task(
            task.id,
            status=task.status,
            attempts=task.attempts,
            last_error=task.last_error,
        )
        # Rules ratchet: persist failure as a rule for future sessions
        self._record_failure_rule(task, error)

    def _record_failure_rule(self, task: Task, error: str) -> None:
        """Record a failure as a rule for future sessions (rules ratchet).
        
        Every mistake becomes a permanent signal. Rules are stored in
        AGENTS.md so future sessions read them as constraints.
        """
        import os
        project_root = str(find_repo_root())
        agents_file = os.path.join(project_root, 'AGENTS.md')
        
        # Classify the failure type
        error_lower = error.lower()
        rule = None
        if 'hunk not found' in error_lower or 'could not parse' in error_lower:
            rule = f"- When patching files, the old_text must be an EXACT substring of the file content. Read the file first, then use the exact text."
        elif 'syntax error' in error_lower:
            rule = f"- After generating code, verify it has no syntax errors before returning. Use python -c 'compile()' to check."
        elif 'validation failed' in error_lower:
            rule = f"- Always run validation checks on generated code before returning it."
        elif 'review failed' in error_lower:
            rule = f"- The independent reviewer checks acceptance criteria. Ensure your changes actually meet the stated requirements."
        elif 'no changes' in error_lower:
            rule = f"- If the task requires creating a new file, use the CREATE format. If modifying, the old_text must match existing content."
        
        if rule:
            try:
                # Read existing rules
                existing = ""
                if os.path.exists(agents_file):
                    with open(agents_file, 'r') as f:
                        existing = f.read()
                
                # Don't duplicate rules
                if rule not in existing:
                    # Append rule under a '## Harness Rules' section
                    if '## Harness Rules' not in existing:
                        existing += f"\n\n## Harness Rules\n\nThese rules were automatically generated from failures. Do not edit manually.\n"
                    with open(agents_file, 'a') as f:
                        f.write(f"{rule}\n")
                    # (26/09, run overnight) Regra aprendida = meta-trabalho
                    # seguro: commit IMEDIATO. Sem isso a árvore fica suja e
                    # o safety bloqueia TODAS as tasks seguintes (conflito
                    # learning × branch-isolation pago no run 26/09: task 2
                    # morreu com 'dirty tree' causado pela regra da task 1).
                    try:
                        repo = os.path.dirname(agents_file)
                        subprocess.run(["git", "-C", repo, "add", agents_file],
                                       capture_output=True, timeout=10)
                        subprocess.run(["git", "-C", repo, "commit", "-q", "-m",
                                       f"learn(nightwatch): {rule[:70]}"],
                                       capture_output=True, timeout=15)
                    except Exception:
                        pass
                    self.notify(f"📏 Rule added: {rule[:60]}...")
            except Exception:
                pass  # Don't fail the task just because rule recording failed

    # ── Notifications ──────────────────────────────────────────────────────

    def notify(self, message: str) -> None:
        """Send notification via Event Bus + console (never silent)."""
        print(message.replace("*", ""), flush=True)
        self._bus.publish("harness.notify", {"message": message})

    def _handle_bus_notify(self, event: Event) -> None:
        """Handle notify events — delegates to Telegram."""
        if self.config.telegram_notifications:
            self.send_telegram(event.data.get("message", ""))

    def _handle_bus_log(self, event: Event) -> None:
        """Handle task lifecycle events — logs to JSONL."""
        entry = {"ts": event.ts, "event": event.topic, **event.data}
        _log_progress(entry)

    def _emit(self, topic: str, **data: object) -> None:
        """Emit a lifecycle event through the Event Bus."""
        self._bus.publish("harness.task", {"event_type": topic, **data})

    # ── Task Discovery ─────────────────────────────────────────────────────

    def _discover_projects(self) -> None:
        """Auto-discover projects in the workspace (minus protected)."""
        try:
            projects = discover_projects()
            for proj in projects:
                if safety.is_project_protected(proj.name):
                    continue
                self.project_registry.register(proj)
                if proj.name not in self.config.projects:
                    self.config.projects.append(proj.name)
        except Exception:
            # Fallback: just use the configured project
            if self.config.project not in self.config.projects:
                self.config.projects.append(self.config.project)
    
    def _has_real_target(self, task: Task) -> bool:
        """(30/09) Task tem pelo menos um target que é ARQUIVO de verdade?

        Usado pra priorizar actionable sobre review-only. Reaproveita
        _target_is_actionable (mesma régua do filtro de execução) — não
        duplica conceito de "isto é um arquivo".
        """
        return any(_target_is_actionable(t) for t in (task.target_files or []))

    def discover_tasks(self, project: str | None = None) -> list[Task]:
        """Discover tasks from all enabled sources.
        
        If project is specified, only discover tasks for that project.
        Otherwise, discover across all configured projects.
        
        Uses platform bridge for workspace-aware discovery when available.
        """
        tasks = []
        projects = [project] if project else self.config.projects

        # Platform-aware discovery: use workspace module if available
        try:
            from nightwatch.platform_bridge import discover_projects_for_nightwatch
            ws_projects = discover_projects_for_nightwatch()
            if ws_projects:
                # Update config with discovered projects (minus protected)
                for proj in ws_projects:
                    if safety.is_project_protected(proj["name"]):
                        continue
                    # (26/09, bug do run overnight) --projects explícito é
                    # ESTRITO: 115 tasks/23 projetos ignoraram o filtro e o
                    # executor gastou a noite fora do alvo.
                    if self.config.strict_projects:
                        continue
                    if proj["name"] not in self.config.projects:
                        self.config.projects.append(proj["name"])
                        self.notify(f"🏗️ Discovered project: {proj['name']}")
        except Exception:
            pass

        for proj_name in projects:
            # Scripted discovery (per-project if project has a root)
            if self.config.use_scripted_discovery:
                tasks.extend(_discover_scripted_tasks())

            # LLM discovery (per-project)
            if self.config.use_llm_discovery:
                tasks.extend(_discover_llm_tasks(self.call_llm, proj_name))

        # (30/09) Task ACTIONABLE (tem target de arquivo real) tem
        # PREFERÊNCIA sobre task de review — Independentemente do cap.
        # Motivo (bug observado na run 15:37): o discovery SCRIPTADO entra
        # primeiro na lista e, sendo todo review-task (priority 1-2), o
        # cap "5 por projeto" (por ordem de chegada) enchia com elas e
        # EXPULSAVA as tasks do LLM — que são as únicas com target de
        # arquivo real (as únicas que o patch loop consegue aplicar). O
        # nightwatch rodava 2.5min, 0 commits, "No more tasks" —看似 fez
        # trabalho mas nunca chegou no patch. Regra: actionable primeiro,
        # review preenche o resto.
        actionable = [t for t in tasks if self._has_real_target(t)]
        review_only = [t for t in tasks if not self._has_real_target(t)]
        tasks = actionable + review_only

        # Cap: max 5 new tasks per project per round (flood control —
        # generic LLM slop multiplied by N projects burned the queue).
        # (30/09) Aplicado DEPOIS do actionable-first, então o cap já
        # conta primeiro as Useful.
        capped: list[Task] = []
        per_project: dict[str, int] = {}
        for t in tasks:
            n = per_project.get(t.project, 0)
            if n < 5:
                capped.append(t)
                per_project[t.project] = n + 1
        tasks = capped

        # Platform-aware persona selection for each task
        try:
            from nightwatch.platform_bridge import select_persona_for_task
            for task in tasks:
                persona = select_persona_for_task(task.description)
                if persona and persona.get("id"):
                    task.persona = persona["id"]
        except Exception:
            pass
        
        # Deduplicate by description
        seen = set()
        unique = []
        for t in tasks:
            key = f"{t.project}:{t.description[:80]}"
            if key not in seen:
                seen.add(key)
                unique.append(t)
        
        return unique

    # ── Task Execution ─────────────────────────────────────────────────────

    def _moe_unit_state(self) -> str:
        """(30/09) Estado da unidade llama-cpp-ik, sem sudo (query pura).
        `systemctl is-active` lê o estado; não precisa de privilégio, então
        funciona dentro do serviço. Vazio se o systemctl falhar.
        """
        import subprocess as _sp
        try:
            r = _sp.run(["systemctl", "is-active", "llama-cpp-ik"],
                        capture_output=True, timeout=10)
            return r.stdout.decode().strip()
        except Exception:
            return ""

    def ensure_strong_llm(self) -> bool:
        """(26/09) Garante o tier forte :8084; DEFERE a execução se não
        puder — nunca degrada pro bonsai em silêncio (padrão de qualidade
        do dono: noite = MoE, tempo não importa).

        Ordem: healthy? → sobe a unidade on-demand → espera load →
        RAM insuficiente/health falhou? → False (caller notifica e sai).

        (30/09) A unidade agora é Wants= do systemd, então ela JÁ pode estar
        carregando quando este código roda (Type=simple retorna no fork, o
        load do 35B leva minutos e come ~16GB). Se a unidade está
        activating/active, o gate de RAM dispararia um DEFER espúrio
        enquanto o MoE está legitimamente carregando — então, nesse caso,
        só espera o :8084 ficar healthy, sem o gate.
        """
        import subprocess, urllib.request
        def _up() -> bool:
            try:
                urllib.request.urlopen("http://127.0.0.1:8084/health",
                                       timeout=3).read(1)
                return True
            except Exception:
                return False
        if _up():
            return True
        # 29/09: a checagem de RAM acontecia DEPOIS de o bonsai já estar
        # segurando a VRAM. Na prática o MoE quase nunca estava no ar
        # (1 LLM por vez, VRAM 6GB), então o nightwatch caía no "avail
        # < 19000 → deferred" para SEMPRE — mesmo com 16GB livres, porque
        # a RAM estava sendo consumida pelo router. Ordem correta:
        # despejar o router primeiro (libera VRAM+RAM), DEPOIS medir RAM,
        # DEPOIS subir o MoE.
        try:
            from jarvis.core.model_lifecycle import _evict_peers
            evicted = _evict_peers("http://127.0.0.1:8084")
            if evicted:
                self.notify(f"🧹 Nightwatch despejou o router p/ "
                            f"liberar o MoE: {', '.join(evicted)}")
                time.sleep(8)
        except Exception:
            pass
        # Se o systemd já está subindo o MoE (Wants=), não faça o gate de
        # RAM: o load legítimo do 35B (16GB) derrubaria MemAvailable e
        # dispararia um DEFER espúrio. Nesse caso é só esperar healthy.
        unit_state = self._moe_unit_state()
        if unit_state in ("activating", "active", "reloading"):
            for _ in range(90):  # systemd está subindo; só espera o load
                if _up():
                    return True
                time.sleep(20)
            self.notify("⏸️ *Deferred*: MoE foi iniciado pelo systemd mas "
                        "não ficou healthy (ver journal llama-cpp-ik)")
            return False
        avail = int(open("/proc/meminfo").read().split("MemAvailable:")[1]
                    .split()[0]) // 1024
        if avail < 19000:
            self.notify(f"⏸️ *Deferred*: MoE precisa ~19GB, avail {avail}MB "
                        "— nightwatch espera RAM (nunca degrada pro bonsai)")
            return False
        _sudo_systemctl("start", "llama-cpp-ik")
        for _ in range(90):  # load do 35B leva minutos
            if _up():
                break
            time.sleep(20)
        else:
            self.notify("⏸️ *Deferred*: MoE não subiu (ver journal llama-cpp-ik)")
            return False
        # Alias dinâmico: lê o que a unidade REALMENTE serve (/v1/models).
        # Preset tem jarvis-raw-strong (uncensored) + jarvis-strong com
        # --models-max 1: adivinhar o nome quebrava (bug pago 26/09).
        try:
            with urllib.request.urlopen("http://127.0.0.1:8084/v1/models",
                                        timeout=5) as _r:
                import json as _j
                _ms = _j.load(_r).get("data", [])
                model_id = (_ms[0].get("id") if _ms else "") or "jarvis-raw-strong"
                os.environ["JARVIS_LLM_MODEL"] = model_id
        except Exception:
            os.environ.setdefault("JARVIS_LLM_MODEL", "jarvis-raw-strong")
        return True

    def execute_task(self, task: Task) -> bool:
        """Execute a single task through the full pipeline.

        Pipeline:
            1. Checkpoint (save state)
            2. Request patch from LLM
            3. Apply via SafeEditor (atomic, validated)
            4. Validate (syntax, imports, tests)
            5. Review (independent)
            6. Commit (only if all pass)
            7. Learn (persist to AGENTS.md)
        """
        task_start = time.time()

        # (26/09, bug do run overnight) Task criada há muito tempo não é
        # 'running' — é STALE. Descartar com mensagem honesta (o timeout
        # antigo media created_at e mentia 'running for 4h' em task recém-
        # iniciada; 3 tasks da noite morreram sem executar NADA).
        task_age = task_start - task.created_at
        if task_age > self.config.task_timeout * 6:
            task.skip(f"stale task: criada há {task_age/60:.0f} min, descartada")
            self.notify(f"🗑️ *Stale*\n{task.description[:50]}")
            return False

        # Global pause gate: any IDE/CLI/AI (or the watchdog on memory
        # pressure) can defer autonomous work via the PAUSED flag file.
        # Deferred, not failed — no attempts consumed.
        from nightwatch.pause import is_paused
        _paused, _why = is_paused()
        if _paused:
            task.skip(f"paused: {_why}")
            self.notify(f"⏸️ *Task Paused*\n{task.description[:80]}\n{_why}")
            self._emit("task_paused", task_id=task.id, reason=_why)
            return False

        # Create checkpoint
        cp = create_checkpoint_for_task(task.id, task.description, self.config.project)

        # Notify start
        self.notify(f"🔄 *Task Started*\n{task.description[:100]}")
        self._emit("task_started", task_id=task.id, description=task.description[:100])

        # Check protected paths
        for f in task.target_files:
            if safety.is_path_protected(f):
                task.block(f"Protected path: {f}")
                # 30/09: "blocked" sem motivo é beco — o agente (e o
                # humano) não sabe onde-acting dentro da fronteira. O
                # guard agora expõe o PORQUÊ; blocked vira "consulta o
                # guard e reformula" em vez de "desiste".
                from nightwatch.safety import path_protection_reason
                _why = path_protection_reason(f) or "consultar nightwatch/safety.py"
                self.notify(f"🚫 *Task Blocked*\n{f}\n_Razão_: {_why[:180]}")
                continue

        # Check protected projects (defense in depth — discovery filters,
        # but explicit tasks must also be refused)
        if safety.is_project_protected(task.project):
            from nightwatch.safety import project_protection_reason
            _why = project_protection_reason(task.project) or "projeto protegido"
            task.block(f"Protected project: {task.project}")
            self.notify(f"🚫 *Task Blocked*\n{task.project}\n_Razão_: {_why[:180]}")
            return False

        # Se tudo em target_files é protegido, blocked (não seguir tentando).
        if task.target_files and all(
                safety.is_path_protected(f) for f in task.target_files):
            return False

        # Mark in progress
        self.queue.update_task(task.id, status=TaskStatus.IN_PROGRESS.value)

# (30/09) Task sem target_files não tem o que o patch loop ler →
# _request_patch morre em "No readable target files" e queima 3
        # tentativas de LLM (~80s cada) pra nada. Task de review ("586
        # functions in core/") não nomeia UM arquivo; LLM que devolve só
        # string também não. Não é tarefa de patch — marca e segue em vez
        # de retry cego. (CREATE com caminho explícito continua: vem em
        # target_files e _read_file_for_llm devolve ERROR → treated as
        # CREATE candidate, que é o caminho certo.)
        if not any(_target_is_actionable(f) for f in task.target_files):
            task.skip("targets não são arquivos reais (prosa/diretório) — task de review")
            self.notify(f"⏭️ *Skipped* (alvo não é arquivo)\n{task.description[:70]}")
            return False

        # (30/09) Código ARQUIVADO não é alvo de melhoria autônoma.
        # archive/README.md: módulos removidos de propósito (0 imports,
        # substituídos). Medido: a noite inteira foi gasta em
        # archive/core/* — testar/refatorar código morto é trabalho sem
        # valor nenhum. Pula antes de queimar tentativa de LLM.
        if all(f.startswith("archive/") for f in task.target_files):
            task.skip("target em archive/ — código arquivado (não roda)")
            self.notify(f"⏭️ *Skipped* (código arquivado)\n{task.description[:70]}")
            return False

        # Dry run
        if self.config.dry_run:
            self.notify(f"🔍 *Dry Run*\n{task.description[:80]}")
            task.skip("dry-run")
            return False

        branch: str | None = None
        try:
            with project_isolation.use_project_root(project_isolation.resolve_project_root(task.project)):
                # ── Step 0a: Isolate on a task branch ──
                # Every commit for this task happens here, never on main
                # directly. abort_task_branch() on any failure path below
                # discards this branch entirely — main is never touched
                # until the merge at the very end.
                branch = safety.create_task_branch(task.id, task.project)
                if not branch:
                    self._fail_task(task, "Could not create isolated branch (git checkout -b failed)")
                    self.notify(f"🚫 *Task Blocked*\nBranch isolation failed for {task.id}")
                    return False

                # ── Step 0b: Context budget check ──
                try:
                    stats = self.context_budget.get_stats()
                    if stats.get("should_compact", False):
                        cp.record_compaction(
                            stats.get("tokens_estimated", 0),
                            stats.get("tokens_estimated", 0) // 2,
                            "auto-compact before LLM call"
                        )
                        self.notify("🗜️ Context compaction triggered")
                except Exception:
                    pass

                # ── Retry loop: patch → apply → validate → review ──
                # On validation/review failure, feed error context back to LLM
                # so it can learn from its mistakes instead of repeating them.
                previous_errors: list[str] = []
                max_attempts = max(self.config.max_retries, 1)

                # (30/09) Retry consciente do ORÇAMENTO: mediram-se runs
                # em que as 3 tentativas de UMA task consomiam o run
                # inteiro (3×~45s de LLM + validação) e as 4 outras tasks
                # da fila nunca rodavam. Retry deve servir pra convergir,
                # não pra monopolizar o budget. Se o run já gastou uma
                # fração grande do tempo, tentamos menos — sobra tempo
                # pra mais tasks distintas, que é onde está a informação.
                _t_start = self._run_started_at
                if _t_start:
                    _elapsed = time.time() - _t_start
                    _budget = self.config.max_minutes * 60
                    _frac = _elapsed / _budget if _budget else 0.0
                    if _frac > 0.5 and max_attempts > 2:
                        max_attempts = 2
                    elif _frac > 0.75 and max_attempts > 1:
                        max_attempts = 1

                for attempt in range(max_attempts):
                    if attempt > 0:
                        # (30/09, C5) esta task realmente vai RETRYar
                        self._task_retried = True
                        safety.abort_task_branch(branch)
                        branch = safety.create_task_branch(task.id, task.project)
                        if not branch:
                            self._fail_task(task, f"Could not create branch for retry {attempt}")
                            return False
                        # Reset state so the pipeline can re-enter cleanly
                        self.queue.update_task(task.id, status=TaskStatus.IN_PROGRESS.value)
                        self.notify(f"🔁 Retry {attempt + 1}/{max_attempts} with error context")

                    # ── Step 1: Request structured patches from LLM ──
                    success, patches, errors = _request_structured_patch(
                        task_description=task.description,
                        target_files=task.target_files,
                        call_llm_fn=self.call_llm,
                        previous_errors=previous_errors if previous_errors else None,
                    )

                    cp.record_operation("patch", success, "; ".join(errors) if errors else "")

                    if not success:
                        previous_errors.extend(errors)
                        if attempt < max_attempts - 1:
                            self.notify(f"⚠️ Patch failed (attempt {attempt + 1}), retrying with error context")
                            continue
                        safety.abort_task_branch(branch)
                        self._fail_task(task, "; ".join(errors))
                        self.notify(f"❌ *Patch Failed*\n{errors[0][:100] if errors else 'unknown'}")
                        _log_progress({
                            "task_id": task.id, "status": "patch_failed",
                            "error": errors[0] if errors else "unknown",
                        })
                        return False

                    if not patches:
                        # LLM decided no changes needed — discard the empty
                        # branch instead of leaving it orphaned
                        safety.abort_task_branch(branch)
                        task.skip("no_changes_needed")
                        self.notify(f"⏭️ *No Changes*\n{task.description[:50]}")
                        return False

                    # ── Step 2: Apply structured patches via Patcher + SafeEditor ──
                    self.queue.update_task(task.id, status=TaskStatus.VALIDATING.value)
                    applied_files = []
                    apply_errors = []

                    from nightwatch.patcher import apply_patch
                    from nightwatch.safe_editor import strip_markdown_fences

                    for file_patch in patches:
                        # Apply patch hunks to get new content
                        patch_ok, patched_content, patch_diff = apply_patch(file_patch)

                        if not patch_ok:
                            apply_errors.append(f"Patcher failed for {file_patch.path}: {patched_content}")
                            cp.record_operation(f"patch:{file_patch.path}", False, patched_content)
                            continue

                        # Validate and write via SafeEditor (atomic, validated)
                        resolved = _resolve_file_path(file_patch.path)
                        edit_result: EditResult = self.editor.apply_edit(
                            resolved, patched_content, validate=True
                        )
                        if edit_result.success:
                            applied_files.append(file_patch.path)
                            cp.record_operation(f"write:{file_patch.path}", True)
                        else:
                            apply_errors.extend(edit_result.errors)
                            cp.record_operation(f"write:{file_patch.path}", False, "; ".join(edit_result.errors))

                    if not applied_files:
                        previous_errors.extend(apply_errors)
                        if attempt < max_attempts - 1:
                            self.notify(f"⚠️ Write failed (attempt {attempt + 1}), retrying")
                            continue
                        safety.abort_task_branch(branch)
                        self._fail_task(task, f"All patches failed: {'; '.join(apply_errors)}")
                        self.notify(f"❌ *Write Failed*\n{apply_errors[0][:100] if apply_errors else 'rejected'}")
                        _log_progress({
                            "task_id": task.id, "status": "write_failed",
                            "errors": apply_errors,
                        })
                        return False

                    # ── Step 3: Validate ──
                    # (30/09, Lição 1 aplicada ao nightwatch) Rodar o
                    # teste só DEPOIS do patch culpa o modelo por falha
                    # que já existia. Medido: test_integration::
                    # test_llama_cpp_chat falha por AMBIENTE (precisa do
                    # LLM carregado) — e o padrão "2 passed, 2 failed"
                    # que o nightwatch via SEMPRE era esse teste de
                    # ambiente, não o patch. A correção: baseline antes.
                    # Só reprova o que o patch QUEBROU de novo.
                    validation = validate_change(
                        applied_files,
                        run_tests=self.config.run_tests,
                        run_imports=self.config.run_imports,
                    )

                    cp.record_operation("validate", validation.passed, validation.summary)

                    if not validation.passed:
                        # separa falha NOVA (culpa o patch) de já-quebrada
                        all_fails = _extract_failed_tests(validation)
                        baseline = _pre_patch_test_baseline(applied_files)
                        new_fails = all_fails - baseline
                        if all_fails and not new_fails:
                            # TODAS as falhas já existiam → patch inocente
                            self.notify(
                                f"✅ *Baseline-clean*\n{validation.summary} "
                                f"(falhas pré-existentes, não do patch)")
                            validation.passed = True
                        else:
                            # (C5-pre) traceback + grounding no retry
                            _err_detail = ""
                            for _s in validation.steps:
                                if not _s.passed and not _s.skipped and _s.output:
                                    _err_detail += f"\n{_s.output[:2000]}"
                                    _err_detail += _ground_failure(_s.output)
                            _new_txt = (f" [NEW failures: {', '.join(sorted(new_fails)[:5])}]"
                                        if new_fails else "")
                            previous_errors.append(
                                f"Validation failed{_new_txt}: "
                                f"{validation.summary}{_err_detail}")
                            if attempt < max_attempts - 1:
                                self.notify(f"⚠️ Validation failed (attempt {attempt + 1}), retrying with error context")
                                continue
                            safety.abort_task_branch(branch)
                            self._fail_task(task, f"Validation failed: {validation.summary}")
                            self.notify(f"❌ *Validation Failed*\n{validation.summary}")
                            _log_progress({
                                "task_id": task.id, "status": "validation_failed",
                                "summary": validation.summary,
                            })
                            return False

                    # (30/09, C5) Validação passou. Se chegamos aqui numa
                    # tentativa > 1, o retry CONVERGIU: o modelo recebeu o
                    # traceback e corrigiu. Contabiliza pra métrica de
                    # convergência (que antes eu media lendo log à mão).
                    self._retry_succeeded_here(attempt)

                    # ── Step 4: Independent review ──
                    # Skip LLM review for low-risk tasks that pass validation.
                    # This saves ~30-60s per task (1 LLM call eliminated).
                    # High-risk tasks and tasks with test failures still get reviewed.
                    skip_review = (
                        self.config.auto_review
                        and task.risk == "low"
                        and validation.passed
                        and not any(s.output for s in validation.steps if s.name == "tests")
                    )
                    if self.config.auto_review and not skip_review:
                        self.queue.update_task(task.id, status=TaskStatus.REVIEW.value)
                        test_output = "\n".join(
                            s.output for s in validation.steps if s.name == "tests"
                        )
                        review = review_change(
                            task_description=task.description,
                            acceptance_criteria=task.acceptance_criteria,
                            test_output=test_output,
                            call_llm_fn=self.call_llm,
                        )

                        if not review.passed:
                            previous_errors.append(f"Review failed: {review.summary}")
                            if attempt < max_attempts - 1:
                                self.notify(f"⚠️ Review failed (attempt {attempt + 1}), retrying with error context")
                                continue
                            safety.abort_task_branch(branch)
                            self._fail_task(task, f"Review failed: {review.summary}")
                            self.notify(f"❌ *Review Failed*\n{review.summary}")
                            _log_progress({
                                "task_id": task.id, "status": "review_skipped",
                                "summary": review.summary,
                            })
                            return False
                    elif skip_review:
                        self.notify("⏭️ *Review Skipped* (low-risk, validation passed)")

                    # All steps passed — break out of retry loop
                    break
                else:
                    # Exhausted all retries
                    safety.abort_task_branch(branch)
                    self._fail_task(task, f"Failed after {max_attempts} attempts: {'; '.join(previous_errors[-2:])}")
                    self.notify(f"❌ *Exhausted Retries*\n{task.description[:50]}")
                    return False

                # ── Step 5: Commit on branch, then merge into main ──
                msg = f"nightwatch({task.project}): {task.description[:80]}"
                branch_commit = _git_commit(msg)
                if not branch_commit:
                    # Validation/review passed but the commit itself failed —
                    # don't leave an unmerged branch behind, don't report
                    # success with no actual commit.
                    safety.abort_task_branch(branch)
                    self._fail_task(task, "git commit failed on task branch after validation passed")
                    self.notify("❌ *Commit Failed*\nValidation passed but git commit did not")
                    _log_progress({"task_id": task.id, "status": "commit_failed"})
                    return False
                commit_sha = safety.merge_task_branch(branch)
                cp.record_operation("commit", commit_sha is not None)

                # ── Step 6: Complete (com veredito de evidência) ──
                ev_ok, ev_why = _verify_completion_evidence(
                    commit_sha, applied_files)
                if not ev_ok:
                    safety.abort_task_branch(branch)
                    self._fail_task(
                        task, f"evidence verdict: {ev_why}")
                    self.notify(f"❌ *Evidence Verdict*\n{ev_why}")
                    from jarvis.core.completion import verdict_for_outcome
                    _ev_verdict = verdict_for_outcome(
                        "evidence_failed", ev_why).status
                    _log_progress({"task_id": task.id,
                                   "status": "evidence_failed",
                                   "verdict": _ev_verdict,
                                   "reason": ev_why})
                    return False
                task.complete(commit_sha)
                self.loop_detector.reset(task.id)  # Clear loop tracking on success
                self.mission.total_tasks_completed += 1
                if commit_sha:
                    self.mission.total_commits += 1

                # Platform observability: log execution stats
                try:
                    from nightwatch.platform_bridge import log_task_execution
                    log_task_execution(
                        task_id=task.id,
                        persona=getattr(task, 'persona', 'unknown'),
                        model_tier=getattr(task, 'model_tier', 'medium'),
                        project=task.project,
                        status="completed",
                        duration_seconds=time.time() - task_start,
                    )
                except Exception:
                    pass

                self.notify(
                    f"✅ *Task Complete*\n{task.description[:50]}\n"
                    f"Commit: {commit_sha[:8] if commit_sha else 'N/A'}"
                )
                self._emit("task_completed", task_id=task.id, commit=commit_sha, files=applied_files)

                _log_progress({"task_id": task.id, "status": "completed",
                               "verdict": task.verdict,
                               "commit": commit_sha, "files": applied_files,
                               })

                return True

        except Exception as e:
            cp.record_operation("error", False, str(e))
            error_msg = str(e)
            failure_type = classify_failure(error_msg, task.status)
            self._fail_task(task, error_msg)
            self.notify(
                f"❌ *Task Error* [{failure_type.value}]\n{error_msg[:100]}"
            )
            self._emit("task_failed", task_id=task.id, error=error_msg[:100], failure_type=failure_type.value)
            _log_progress({
                "task_id": task.id, "status": "error",
                "error": error_msg, "failure_type": failure_type.value,
            })
            # Revert on error — abort the isolated branch, main untouched
            if branch:
                safety.abort_task_branch(branch)
            else:
                _git_revert(applied_files if 'applied_files' in dir() else None)

            # Anti-loop detection
            in_loop = self.loop_detector.record_attempt(task.id, success=False)
            if in_loop:
                task.block(f"Anti-loop: {self.config.loop_max_attempts} failures in {self.config.loop_window_seconds}s")
                self.notify(f"🔄 *Loop Detected* — task {task.id} blocked after {self.config.loop_max_attempts} attempts")
                self._emit("loop_detected", task_id=task.id, attempts=self.loop_detector.get_stats(task.id))
                _log_progress({
                    "task_id": task.id, "status": "loop_detected",
                    "attempts": self.loop_detector.get_stats(task.id),
                })
                return False

            # Retry logic for transient/tool failures
            if failure_type in (FailureType.TRANSIENT, FailureType.TOOL_FAILURE):
                retries = getattr(task, '_retry_count', 0)
                if retries < self.config.max_retries:
                    task._retry_count = retries + 1
                    wait = min(2 ** retries * 5, 60)  # exponential backoff, max 60s
                    self.notify(f"🔁 Retrying in {wait}s (attempt {retries + 1}/{self.config.max_retries})")
                    time.sleep(wait)
                    # Don't count as executed — retry same task
                    return self.execute_task(task)

            return False

    # ── Main Run ───────────────────────────────────────────────────────────

    def run(self) -> HarnessResult:
        """Run the harness.

        Flow:
            1. Check for recovery context
            2. Recover stuck tasks
            3. Discover tasks (scripted + LLM) across projects
            4. Execute tasks through pipeline
            5. Switch projects periodically
            6. Report results
        """
        start = time.time()
        # (30/09) execut_task usa isto para deixar o retry consciente do
        # orçamento de tempo (não monopolizar o run numa task só).
        self._run_started_at = start
        result = HarnessResult()

        # Concurrency guard: um loop por vez (discovery LLM paralela
        # derrete a GPU). Segundo loop sai imediatamente.
        import fcntl as _fcntl
        _lock_path = Path.home() / ".local/state/jarvis/nightwatch/RUNNING.lock"
        _lock_path.parent.mkdir(parents=True, exist_ok=True)
        _lock_fh = open(_lock_path, "w")
        try:
            _fcntl.flock(_lock_fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except OSError:
            self.notify("⏭️ *Nightwatch skipped*\nOutro loop em execução")
            return result
        _lock_fh.write(f"{os.getpid()}\n{start}\n")
        _lock_fh.flush()

        self.mission.active = True
        self.mission.started_at = time.time()

        # Prune stale tasks from previous runs (>1h old, still non-terminal)
        pruned = self.queue.prune_stale(max_age_seconds=3600)
        if pruned > 0:
            self.notify(f"🧹 Pruned {pruned} stale tasks from previous runs")

        projects_str = ", ".join(self.config.projects[:3])
        self.notify(f"🌙 *Nightwatch Started*\nProjects: {projects_str}")
        self._emit("run_started", projects=self.config.projects)

        # Global pause short-circuit: skip discovery AND execution
        # (discovery burns LLM/GPU for tasks that would only be deferred).
        from nightwatch.pause import is_paused as _is_paused_now
        _paused_now, _why_now = _is_paused_now()
        if _paused_now:
            self.notify(f"⏸️ *Run Paused*\n{_why_now}")
            self._emit("run_paused", reason=_why_now)
            return result

        # ── Recovery ──
        recovery = get_recovery_context(project=self.config.project)
        if recovery and recovery.get("task_id"):
            self.notify(f"♻️ *Recovering*: {recovery.get('task_description', '')[:50]}")
            self._emit("recovery", task_id=recovery.get("task_id"), description=recovery.get("task_description", "")[:50])

        # ── Discover across all projects ──
        self.notify("🔍 Discovering tasks...")
        new_tasks = self.discover_tasks()
        for task in new_tasks:
            # (26/09) strict: task fora dos projetos-alvo não entra na fila
            if (self.config.strict_projects and self.config.projects
                    and task.project not in self.config.projects):
                continue
            self.queue.add_task(task)

        self.notify(f"📋 Found {len(new_tasks)} tasks across {len(self.config.projects)} projects")

        # ── Execute ──
        executed = 0
        tasks_since_switch = 0
        current_project_idx = 0

        while executed < self.config.max_tasks:
            if (time.time() - start) > self.config.max_minutes * 60:
                self.notify(f"⏰ Time limit ({self.config.max_minutes} min)")
                break

            task = self.queue.get_next_task()
            if not task:
                # Try discovering more tasks
                if self.config.projects:
                    proj = self.config.projects[current_project_idx % len(self.config.projects)]
                    more = self.discover_tasks(project=proj)
                    for t in more:
                        self.queue.add_task(t)
                    task = self.queue.get_next_task()
                if not task:
                    self.notify("✅ No more tasks")
                    break

            success = self.execute_task(task)

            # (30/09, C5) Agrega métrica de convergência: uma task
            #Xlixhou retry conta 1 em attempted; convergiu (passou numa
            # tentativa >1) conta +1 em succeeded. Torna o C5 um número
            # medido, não leitura de log.
            if getattr(self, "_task_retried", False):
                result.retry_attempted += 1
                if success:
                    result.retry_succeeded += 1
            self._task_retried = False

            if success:
                result.tasks_completed += 1
                result.files_changed.extend(task.target_files)
                if task.commit_sha:
                    result.commits.append(task.commit_sha)
                # Update project state
                self.project_registry.update_state(
                    task.project,
                    tasks_completed=self.project_registry.get_state(task.project).tasks_completed + 1
                    if self.project_registry.get_state(task.project) else 1,
                )
            elif task.status == TaskStatus.BLOCKED.value:
                result.tasks_blocked += 1
            elif task.status == TaskStatus.ABANDONED.value:
                result.tasks_skipped += 1
            else:
                result.tasks_failed += 1
                self.project_registry.update_state(
                    task.project,
                    tasks_failed=(self.project_registry.get_state(task.project).tasks_failed + 1
                                  if self.project_registry.get_state(task.project) else 1),
                    last_error=task.last_error or "",
                )

            executed += 1
            tasks_since_switch += 1

            # Switch projects periodically
            if (tasks_since_switch >= self.config.project_switch_interval
                    and len(self.config.projects) > 1):
                current_project_idx = (current_project_idx + 1) % len(self.config.projects)
                tasks_since_switch = 0
                new_proj = self.config.projects[current_project_idx]
                self.notify(f"🔄 Switching to project: {new_proj}")

        # ── Summary ──
        elapsed = time.time() - start
        result.duration_seconds = elapsed

        self.mission.active = False
        self.mission.last_checkpoint = time.time()

        # Per-project stats
        project_stats = []
        for proj_name in self.config.projects:
            stats = self.queue.get_stats(project=proj_name)
            project_stats.append(f"  {proj_name}: {stats['completed']} done, {stats['ready']} ready")

        overall_stats = self.queue.get_stats()
        context_stats = self.context_budget.get_stats()

        summary = f"""🌙 *Nightwatch Complete*

📊 Results:
- Completed: {result.tasks_completed}
- Failed: {result.tasks_failed}
- Blocked: {result.tasks_blocked}
- Skipped: {result.tasks_skipped}
- Files changed: {len(result.files_changed)}
- Commits: {len(result.commits)}
- Duration: {int(elapsed // 60)}m {int(elapsed % 60)}s
- Success rate: {result.success_rate:.0%}
- Retry convergence: {result.retry_succeeded}/{result.retry_attempted} ({result.convergence:.0%})

📈 Projects:
{chr(10).join(project_stats)}

🧠 Context:
- LLM calls: {context_stats.get('total_llm_calls', 0)}
- Compactions: {context_stats.get('total_compactions', 0)}
- Tokens processed: {context_stats.get('total_tokens_processed', 0)}"""

        self.notify(summary)

        _log_progress({
            "event": "run_complete",
            "completed": result.tasks_completed,
            "failed": result.tasks_failed,
            "blocked": result.tasks_blocked,
            "commits": len(result.commits),
            "duration_s": elapsed,
            "projects": self.config.projects,
            "context_stats": context_stats,
        })

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def run_nightwatch(
    max_tasks: int = 10,
    max_minutes: int = 180,
    report_telegram: bool = False,
    dry_run: bool = False,
    use_llm: bool = True,
    use_scripted: bool = True,
    projects: list[str] | None = None,
    context_budget: int = 0,  # 0 = auto-detect from server
) -> HarnessResult:
    # (26/09) projects explícito = estrito (bridge não expande)
    """Convenience function to run nightwatch.

    This replaces both:
    - orchestrator.run_nightwatch()
    - llm_loop.run_llm_nightwatch()
    """
    config = HarnessConfig(
        max_tasks=max_tasks,
        max_minutes=max_minutes,
        telegram_notifications=report_telegram,
        dry_run=dry_run,
        use_llm_discovery=use_llm,
        use_scripted_discovery=use_scripted,
        projects=projects or [],
        strict_projects=bool(projects),
        context_budget=context_budget,
    )
    os.environ.setdefault("JARVIS_LLM_BASE_URL", config.llm_base_url)
    os.environ.setdefault("JARVIS_LLM_MODEL", config.llm_model)
    os.environ["JARVIS_LLM_DISABLE_THINKING"] = \
        "0" if config.llm_thinking else "1"
    harness = Harness(config=config)
    if not harness.ensure_strong_llm():
        return HarnessResult(
            tasks_completed=0, tasks_failed=0, tasks_blocked=0,
            tasks_skipped=0, commits=[], files_changed=[],
            duration_seconds=0.0, errors=["deferred: strong LLM unavailable"])
    try:
        return harness.run()
    finally:
        # 30/09: o restore de pós-run (parar o MoE + voltar o router) NÃO
        # pode ser `sudo systemctl` aqui — o nightwatch roda no serviço
        # systemd com NoNewPrivileges + RestrictSUIDSGID, então o kernel
        # bloqueia escalada setuid e o sudo morre com rc=1. Além disso o
        # MoE hoje é `Wants=` do próprio unit, então quem o sobe é o
        # systemd — e quem o deve parar é o systemd (ExecStopPost no
        # unit faz exatamente isso, com privilégio de systemd). Aqui resta
        # só um best-effort sem privilégio: sinalizar o router pra
        # recarregar o slot que o nightwatch despejou. Falha de restore
        # nunca pode mascarar o resultado do run.
        try:
            import time as _t
            import urllib.request as _url
            # MoE para o systemd (ExecStopPost). Aqui só garantimos que,
            # se ainda estiver vivo, o harness não depende mais dele.
            # Router: tenta um GET leve só pra log; o restart real é do
            # ExecStopPost também.
            try:
                _url.urlopen("http://127.0.0.1:8080/health", timeout=3).read(1)
            except Exception:
                pass
        except Exception:
            pass
