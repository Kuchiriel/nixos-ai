"""Harbor custom agent — JARVIS Kernel (F10/ADR-005).

Calibração externa: o runtime atrás da interface `BaseAgent` do Harbor
(`--agent jarvis_harbor_agent:JarvisHarborAgent --agent-import-path ...`).
Imports do Harbor GUARDED (este módulo importa sem harbor instalado; os
testes usam stubs). Trajetória ATIF a partir da AgentSession.

NUNCA adaptar o runtime p/ passar numa task (otimizar o instrumento).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

try:  # Harbor instalado (job real)
    from harbor.agents.base import BaseAgent
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext
    _HARBOR = True
except Exception:  # sem harbor: stubs p/ teste local
    _HARBOR = False

    class BaseAgent:  # type: ignore[no-redef]
        def __init__(self, *a: Any, **k: Any) -> None:
            self.logs_dir = Path(k.get("logs_dir", "/tmp"))

    class BaseEnvironment:  # type: ignore[no-redef]
        pass

    class AgentContext:  # type: ignore[no-redef]
        """Espelho dos campos reais (harbor 0.23.0) p/ teste local fiel."""

        def __init__(self) -> None:
            self.n_input_tokens = 0
            self.n_cache_tokens = 0
            self.n_output_tokens = 0
            self.cost_usd = 0.0
            self.model_usage: dict = {}
            self.rollout_details: dict = {}
            self.metadata: dict = {}


class _ContainerBridge:
    """Roteia file/shell p/ dentro do container do trial (env.exec/upload).

    28/09 (A-cell): sem isso o agente lia /app/src.txt no HOST (inexistente)
    e o jail do devtools bloqueava write em /app/o.txt — 0.0 garantido.
    O container É o jail (sandbox Harbor) — roteamento é contrato do
    harness, não tuning de task.

    Threading: o Harbor awaita agent.run() NA thread do loop dele; o Agent
    (sync) roda nessa mesma thread. Bloquear nela esperando o próprio loop
    = deadlock (pago 28/09: 3x AgentTimeoutError, zero tools). Por isso a
    bridge tem loop PRÓPRIO em thread dedicada — env.exec é só I/O, sem
    afinidade com o loop do Harbor.
    """

    def __init__(self, env: Any) -> None:
        import asyncio as _aio
        import threading as _th
        self._env = env
        self._seen: set[str] = set()
        self._reads: set[str] = set()
        self._out_bases: set[str] = set()
        # Grounding da completion (29/09): "done" sem nenhuma observação
        # do container é prosa, não trabalho. Contadores alimentam o gate
        # pós-run (COMPLETED com zero exec → UNVERIFIED honesto).
        self.n_exec = 0
        self.n_writes = 0
        self.written: list[str] = []
        self._loop = _aio.new_event_loop()
        self._thread = _th.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def sh(self, cmd: str, timeout: int = 60) -> Any:
        import asyncio as _aio
        import re as _re
        from types import SimpleNamespace as _NS
        # Read-gate bloqueante (29/09: a nota de aviso não converteu —
        # task3 0/4 com aviso). Redirect p/ arquivo de DADOS nunca lido,
        # num cmd que não lê nada = RECUSADO (lê primeiro). Scripts
        # (.sh/.py) isentos (criação é legítima). Só existe na ponte
        # (trials); host nunca passa aqui.
        _SCRIPT_EXT = (".sh", ".py", ".js", ".ts", ".json")
        # 29/09 (4ª, princípio): MENÇÃO ≠ LEITURA. `_reads` só recebe o que
        # foi efetivamente OBSERVADO (exec rc 0 / bridge.read ok). Mencionar
        # o output num cmd falho (`| write_file /app/line2.txt`, exit 127)
        # envenenava o set e recusava a transferência legítima seguinte.
        # `cur` (menções deste cmd) vale p/ o gate de intenção; proteção de
        # fonte usa só o committed.
        cur: set[str] = set()
        try:
            # 29/09 (2ª): o regex capturava FLAGS como paths (`grep -n '2'
            # /app/data.txt registrava "-n", não o fonte — clobber passava).
            # Só conta o que parece path (ignora -flags); além do operando
            # imediato, qualquer token com `/` (cobre `cmd -flag ... /path`).
            cur = {m.group(1).split("/")[-1] for m in _re.finditer(
                r"(?:cat|grep|sed|awk|head|tail|less|xxd|base64|cmp|diff)\s+([/\w.\-]+)", cmd)
                if not m.group(1).startswith("-")}
            _outs = {o.split("/")[-1]
                     for o in _re.findall(r">{1,2}\s*([/\w.\-]+)", cmd)}
            cur |= {t.strip("'\"").split("/")[-1]
                    for t in _re.findall(r"[\"']?(/[-\w./]+)[\"']?", cmd)}
            cur.discard("")
            # Alvo de redirect é OUTPUT, nunca fonte (senão toda primeira
            # escrita seria recusada).
            cur -= _outs
            for o in _re.findall(r">{1,2}\s*([/\w.\-]+)", cmd):
                base = o.split("/")[-1]
                # Fonte OBSERVADA primeiro: read-only p/ redirect. Exceção:
                # output PRÓPRIO (retry legítimo — 7GzVSVq turn 7).
                if (base in self._reads and o not in self.written
                        and base not in self._out_bases
                        and not o.endswith(_SCRIPT_EXT)):
                    return _NS(return_code=1, stdout="",
                               stderr=(f"harness: '{o}' is a SOURCE file you "
                                       f"read — read-only. Write the OUTPUT "
                                       f"to its own path, never overwrite "
                                       f"the source."))
                if (base in self._seen or base in cur
                        or o.endswith(_SCRIPT_EXT)):
                    self._seen.add(base)
                    self._out_bases.add(base)
                    continue
                # task3 29/09: modelo lia data.txt e depois o SOBRESCREVIA
                # (echo invented > data.txt) p/ "extrair" da própria
                # fabricação. Higiene genérica de sandbox: input observado e
                # nunca criado pelo agente é read-only p/ redirect —
                # escreva no OUTPUT, não no fonte. (write_file segue
                # permitido p/ edição cirúrgica com old-string.)
                if not cur and base not in self._reads:
                    return _NS(return_code=1, stdout="",
                               stderr=(f"harness: write to '{o}' refused — "
                                       f"you never read it. Read the source "
                                       f"file first (cat/head), then transfer "
                                       f"with ONE shell command (cp A B, "
                                       f"sed -n Np A > B). Never re-type "
                                       f"bytes — re-typing corrupts."))
                self._seen.add(base)
                self._out_bases.add(base)
        except Exception:
            pass
        self.n_exec += 1
        fut = _aio.run_coroutine_threadsafe(
            self._env.exec(cmd, timeout_sec=timeout), self._loop)
        r = fut.result(timeout + 20)
        try:
            # Commit pós-sucesso: só observação efetiva vira fonte protegida.
            if getattr(r, "return_code", 1) == 0:
                self._seen.update(cur)
                self._reads.update(cur)
        except Exception:
            pass
        return r

    def read(self, path: str) -> tuple[Any, str]:
        self._seen.add(path.split("/")[-1])
        # 29/09 (3ª): leitura via TOOL não alimentava _reads — modelo lia
        # com read_file e o redirect seguinte caía no "never read it".
        # Leitura é leitura, qualquer que seja a interface. (4ª: só conta
        # se OBSERVOU — falha não protege nada.)
        import base64 as _b64
        import shlex as _shlex
        r = self.sh("base64 -- " + _shlex.quote(path))
        if r.return_code != 0:
            return None, (r.stderr or "not found").strip()[:160]
        self._reads.add(path.split("/")[-1])
        try:
            return _b64.b64decode(r.stdout), ""
        except Exception as exc:
            return None, f"base64 decode failed: {exc}"

    def write(self, path: str, content: bytes) -> str:
        import os as _os
        import tempfile as _tf
        self.n_writes += 1
        self.written.append(path)
        fd, tmp = _tf.mkstemp(prefix="hjarvis-")
        try:
            with _os.fdopen(fd, "wb") as f:
                f.write(content)
            fut = self._run_coro(self._env.upload_file(tmp, path))
            fut.result(60)
        finally:
            try:
                _os.unlink(tmp)
            except OSError:
                pass
        return f"wrote {len(content)} bytes to {path}"

    def _run_coro(self, coro: Any) -> Any:
        import asyncio as _aio
        return _aio.run_coroutine_threadsafe(coro, self._loop)


def _container_agent_class(environment: Any) -> Any:
    """Agent com tools roteadas p/ o container; None env = Agent canônico."""
    if environment is None:
        from jarvis.core.agent import Agent
        return Agent
    from jarvis.core.agent import Agent

    class ContainerAgent(Agent):
        """Mesmo loop, tools no container (override de @staticmethods)."""

        _bridge: Any = None

        @staticmethod
        def _exec_read_file(args: dict) -> str:
            bridge = ContainerAgent._bridge
            path = str(args.get("path", ""))
            try:
                offset = int(args.get("offset", 0) or 0)
            except (TypeError, ValueError):
                offset = 0
            try:
                limit = int(args.get("limit", 200) or 200)
            except (TypeError, ValueError):
                limit = 200
            raw, err = bridge.read(path)
            if raw is None:
                return f"ERROR: File not found: {path} ({err})"
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                # task2-bin 29/09: 256 bytes binários viraram "trailer" e o
                # modelo copiou o único token legível 5x. Informação verdadeira
                # sobre o ambiente (não dica de task): binário não passa por
                # ferramenta de texto — shell (cp/xxd/base64/cmp) resolve.
                # Texto p/ o modelo em EN (bonsai rende mal em PT-BR).
                return (f"# {path} ({len(raw)} bytes, BINARY — not valid UTF-8)\n"
                        f"Text tools (read/write) CORRUPT this file. "
                        f"Use execute_shell: `cp`, `xxd`, `base64`, `cmp`. "
                        f"Transfer with ONE command (cp A B) — "
                        f"never re-type bytes.")
            lines = text.split("\n")
            chunk = "\n".join(lines[offset:offset + limit])
            # Trailer anti-vazamento (B-cell 28/09: o MoE copiou o cabeçalho
            # "# path (N linhas)" p/ DENTRO do o.txt 3/3 — target-agnóstico,
            # só marca o que é anotação do harness). Texto p/ o MODELO em EN
            # (bonsai rende mal em PT-BR — 29/09).
            return (f"# {path} ({len(lines)} lines)\n{chunk}\n"
                    f"--- (harness note: the '# ...' line above is an annotation, "
                    f"not part of the file)")

        @staticmethod
        def _exec_list(args: dict) -> str:
            import shlex as _shlex
            bridge = ContainerAgent._bridge
            path = str(args.get("path", ".") or ".")
            r = bridge.sh("ls -la -- " + _shlex.quote(path))
            if r.return_code != 0:
                return f"ERROR: {(r.stderr or 'list failed').strip()[:200]}"
            return (r.stdout or "").strip()[:4000]

        @staticmethod
        def _exec_write(name: str, args: dict) -> str:
            bridge = ContainerAgent._bridge
            path = str(args.get("path", ""))
            if name == "write_file":
                content = str(args.get("content", "")).encode("utf-8")
            else:
                raw, _err = bridge.read(path)
                if raw is None:
                    return f"ERROR: File not found: {path}"
                old, new = str(args.get("old", "")), str(args.get("new", ""))
                text = raw.decode("utf-8", "replace")
                if old not in text:
                    return "ERROR: old string not found in content"
                content = text.replace(old, new, 1).encode("utf-8")
            try:
                return bridge.write(path, content)
            except Exception as exc:
                return f"ERROR: write failed: {exc}"

    return ContainerAgent


def _direct_config() -> Any:
    """Config apontando p/ um servidor single-model (bypass do router).

    JARVIS_BASE_URL=http://127.0.0.1:8084: lê o id ativo em /v1/models e
    fixa llm_model/llm_base_url (sem model_requirements não há roteamento
    nem ensure — o servidor serve um arquivo fixo). Sem env → None
    (comportamento padrão via router :8080).
    E-cell (29/09): JARVIS_LLM_BACKEND=remote + JARVIS_LLM_MODEL p/ cérebro
    cloud OpenAI-compatible (Groq); key via JARVIS_REMOTE_API_KEY (env,
    nunca código). Mesmo harness, outro cérebro.
    """
    import os as _os
    base = _os.environ.get("JARVIS_BASE_URL", "").strip().rstrip("/")
    backend = _os.environ.get("JARVIS_LLM_BACKEND", "").strip()
    from dataclasses import replace
    from jarvis.core.config import get_config
    if backend:
        model = _os.environ.get("JARVIS_LLM_MODEL", "").strip() or "default"
        return replace(get_config(), llm_backend=backend,
                       llm_base_url=base or "https://api.groq.com/openai",
                       llm_model=model)
    if not base:
        return None
    import json as _json
    import urllib.request as _url
    try:
        with _url.urlopen(base + "/v1/models", timeout=15) as r:
            data = _json.load(r).get("data", [])
        mid = data[0].get("id", "default") if data else "default"
    except Exception:
        mid = "default"
    from dataclasses import replace as _replace2
    from jarvis.core.config import get_config as _get_config
    return _replace2(_get_config(), llm_model=mid, llm_base_url=base)


class JarvisHarborAgent(BaseAgent):
    """AgentRuntime como custom agent do Harbor. Modelo via AgentRuntime."""

    SUPPORTS_ATIF = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._model_requirements: dict = kwargs.get("model_requirements") or {}
        if not self._model_requirements:
            # B-cell e rotina: tier via env (ex: {"tier":"reasoning"}).
            import os as _os
            import json as _json
            raw = _os.environ.get("JARVIS_MODEL_REQUIREMENTS", "")
            if raw.strip():
                try:
                    self._model_requirements = _json.loads(raw)
                except ValueError:
                    pass

    @staticmethod
    def name() -> str:
        return "jarvis-kernel"

    def version(self) -> str | None:
        return "1.0.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        return None

    async def run(self, instruction: str, environment: BaseEnvironment,
                   context: AgentContext) -> None:
        """Roda o runtime e devolve o veredito no metadata.

        28/09 (A-cell real): o AgentContext do Harbor 0.23.0 NÃO tem
        commands_executed/exit_code/error_message (só tokens/custo/
        metadata) — escrever neles dava ValueError e matava o trial
        antes do verifier. Agora: só campos reais + metadata; UNVERIFIED
        NÃO levanta (o verifier decide; autoridade é dele, não nossa).
        """
        from jarvis.runtime.agent_runtime import AgentRuntime

        started = time.time()
        cls = _container_agent_class(environment)
        import subprocess as _sp
        import jarvis.core.agent as _agent_mod

        real_sh = _agent_mod.run_shell
        real_chain = _agent_mod.has_chaining_operators
        real_allowed = _agent_mod.command_allowed
        bridge = None
        if environment is not None:
            bridge = _ContainerBridge(environment)
            if hasattr(cls, "_bridge"):
                cls._bridge = bridge

            def _routed(cmd: str, timeout: int = 60) -> _sp.CompletedProcess:
                if bridge is None:
                    return real_sh(cmd, timeout)
                r = bridge.sh(cmd, timeout)
                return _sp.CompletedProcess(cmd, r.return_code,
                                            r.stdout or "", r.stderr or "")
            _agent_mod.run_shell = _routed
            if os.environ.get("JARVIS_TRIAL_TOOLS", "") == "bash-first":
                # Sandbox = container: chaining e allowlist liberados SÓ aqui
                # (host mantém as travas; restore no finally).
                _agent_mod.has_chaining_operators = lambda cmd: False
                _agent_mod.command_allowed = lambda cmd: True
        try:
            cfg = _direct_config()
            # Com config direta NÃO passa model_requirements (se passar, o
            # Agent roteia e o ensure quebra no single-model — pago 28/09).
            akw = {} if cfg is not None else (
                {"model_requirements": self._model_requirements}
                if self._model_requirements else {})
            # F-cell (29/09, tese mini-SWE-agent): JARVIS_TRIAL_TOOLS=bash-first
            # reduz a superfície a execute_shell (container É o sandbox:
            # chaining + allowlist liberados só aqui, com restore).
            if os.environ.get("JARVIS_TRIAL_TOOLS", "") == "bash-first":
                akw["tool_class"] = "shell"
                # Gramática constrained quebra com superfície reduzida
                # (parser do server rejeita); texto livre + parser de texto
                # (tese mini-SWE: sem interface de tool-calling).
                akw["strict_tools"] = False
            rt = AgentRuntime(agent_class=cls, config=cfg, agent_kwargs=akw)
            result = rt.run(instruction,
                            approve=True, approval_callback=lambda cmd: True)
        finally:
            _agent_mod.run_shell = real_sh
            _agent_mod.has_chaining_operators = real_chain
            _agent_mod.command_allowed = real_allowed
        sess = result.session
        # Completion container-aware (29/09): "done" precisa estar ancorado
        # em observação do container. COMPLETED com zero exec = prosa, não
        # trabalho → UNVERIFIED honesto (o verifier continua decidindo o
        # score; aqui só não se declara feito sem ter tocado o ambiente).
        # Genérico (contadores, zero conhecimento de task).
        grounding = {
            "n_exec": getattr(bridge, "n_exec", 0) if bridge else 0,
            "n_writes": getattr(bridge, "n_writes", 0) if bridge else 0,
        }
        verdict = getattr(sess, "termination", "?")
        if verdict == "COMPLETED" and grounding["n_exec"] == 0:
            verdict = "UNVERIFIED"
            grounding["downgraded"] = "completed-without-container-exec"
        self._fill_context(context, sess, time.time() - started,
                           grounding=grounding, verdict=verdict)
        # ATIF-ish: trajetória + sessão serializada no logs_dir
        try:
            logs = Path(getattr(self, "logs_dir", "/tmp"))
            logs.mkdir(parents=True, exist_ok=True)
            (logs / "trajectory.json").write_text(json.dumps({
                "agent": self.name(), "version": self.version(),
                "instruction": instruction,
                "verdict": sess.termination, "turns": sess.turns,
                "model": sess.model_id,
                "duration_s": round(time.time() - started, 1),
                "grounding": grounding,
                "steps": sess.steps,
                "evidence": sess.evidence, "missing": sess.missing,
            }, ensure_ascii=False, default=str)[:200000], encoding="utf-8")
            (logs / "session.json").write_text(json.dumps(
                sess.to_dict(), ensure_ascii=False, default=str)[:200000],
                encoding="utf-8")
        except Exception:
            pass

    @staticmethod
    def _fill_context(context: Any, sess: Any, duration_s: float,
                      grounding: dict | None = None,
                      verdict: str | None = None) -> None:
        """Preenche SÓ campos que existem no context (duck-typing).

        Funciona no AgentContext real (pydantic, harbor instalado) e no
        stub local. Campos desconhecidos são ignorados, nunca erro.
        """
        meta = {
            "verdict": verdict if verdict is not None else getattr(
                sess, "termination", "?"),
            "turns": getattr(sess, "turns", 0),
            "model": getattr(sess, "model_id", "?"),
            "verified": getattr(sess, "verified", False),
            "missing": list(getattr(sess, "missing", []) or [])[:3],
            "duration_s": round(duration_s, 1),
        }
        if grounding:
            meta["grounding"] = grounding
        if hasattr(context, "metadata"):
            try:
                if isinstance(context.metadata, dict):
                    context.metadata.update(meta)
                else:
                    context.metadata = meta
            except Exception:
                pass
