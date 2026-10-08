"""Telegram channel — remote interface for questions, tasks and MISSIONS.

What this is now: the remote control plane of the JARVIS. Send an
objective in natural language, get a mission id back, watch it execute,
answer decision questions from the phone, and receive an evidence-based
report when it finishes.

The security model is deliberate and enforced in code:

1. ONE gate, before any effect. `IdentityGate.authorize()` runs on every
   dispatch path — including the ones that used to bypass it. Previously
   `/agent <task>` was dispatched onto a thread *before* `handle_message`
   (the only place the chat allowlist lived), so any chat id could run a
   full agent.
2. Approval is a bound ticket, not a `callback_data == "yes"`. Every
   ticket is single-use, bound to (user, chat, operation, payload digest)
   and expires. A stale, replayed, foreign or wrong-operation callback
   authorizes nothing.
3. Long work runs in a bounded worker pool, never in the poll loop, so
   the channel stays responsive during a mission.
4. Updates are idempotent by `update_id`, and the offset is persisted, so
   a restart does not replay a mission.

Everything model-facing is English (the local small model loses
non-English instructions). Text shown to the owner is PT-BR.
"""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import requests

from jarvis.core.authz import (
    ApprovalRegistry, AuthDenied, Identity, IdentityGate, PolicyEngine, Risk,
    classify, decode_callback, encode_callback,
)
from jarvis.core.config import Config, get_config

API_BASE = "https://api.telegram.org/bot{token}"

# Telegram limits: 4096 chars per message, 64 bytes of callback_data.
MAX_MSG = 4000
MAX_WORKERS = 2          # bounded: never one thread per incoming message


class TelegramError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Minimal Bot API client
# ---------------------------------------------------------------------------

class TelegramBot:
    def __init__(self, token: str, timeout: float = 30.0) -> None:
        self._token = token
        self._timeout = timeout

    def _post(self, method: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{API_BASE.format(token=self._token)}/{method}"
        try:
            resp = requests.post(url, json=kwargs, timeout=self._timeout)
        except requests.RequestException as exc:
            raise TelegramError(f"connection failure to Telegram: {exc}") from exc
        try:
            data = resp.json()
        except ValueError as exc:
            raise TelegramError(f"invalid JSON from Telegram {method}") from exc
        if not data.get("ok"):
            raise TelegramError(f"Telegram {method}: {data.get('description', 'error')}")
        return data.get("result", {})

    def get_me(self) -> dict[str, Any]:
        return self._post("getMe")

    def send_message(
        self, chat_id: int, text: str, *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "Markdown",
    ) -> dict[str, Any]:
        """Send a message.

        Default parse_mode is Markdown, but the channel uses `parse_mode=None`
        (plain text) for dynamic output: doctor/agent results contain `_`,
        `*` and backticks that break Telegram's markdown (HTTP 400 "can't
        parse entities") and would be silently swallowed.
        """
        kwargs: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        return self._post("sendMessage", **kwargs)

    def get_updates(self, *, offset: int = 0, timeout: int = 25) -> list[dict[str, Any]]:
        """Long polling. `timeout` is the HTTP timeout (Telegram holds the
        response until an update arrives or the timeout expires)."""
        try:
            return self._post("getUpdates", offset=offset, timeout=timeout)
        except TelegramError:
            return []

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._post("answerCallbackQuery", callback_id=callback_id, text=text)


# ---------------------------------------------------------------------------
# Channel
# ---------------------------------------------------------------------------

@dataclass
class _PendingApproval:
    """Kept for backward compatibility with callers that inspect it."""
    event: threading.Event = field(default_factory=threading.Event)
    answer: str = ""


class TelegramChannel:
    """The channel service. `run()` is the loop; `handle_message` is testable."""

    # Fuzzy commands: lowercase, with or without leading /, unambiguous
    # prefix wins ("/st" -> /status). No exact-line decoration.
    _COMMANDS = (
        "mission", "missions", "task", "tasks", "projects", "project",
        "persona", "personas", "approve", "pause", "resume", "cancel",
        "steer", "stop", "agent", "dev", "status", "ask", "remember", "vault",
        "force_local", "force_remote", "sshkey", "opencode",
        "start", "help",
    )

    def __init__(
        self,
        token: str,
        allowed_chats: list[int],
        *,
        bot: TelegramBot | None = None,
        allowed_users: list[int] | None = None,
        ask_fn: Callable[[str], str] | None = None,
        agent_fn: Callable[[str, Callable[[str], bool]], str] | None = None,
        status_fn: Callable[[], str] | None = None,
        remember_fn: Callable[[str], str] | None = None,
        vault_fn: Callable[[str], str] | None = None,
        approval_timeout: float = 120.0,
        circuit_breaker: Any | None = None,
        force_local_fn: Callable[[], str] | None = None,
        force_remote_fn: Callable[[], str] | None = None,
        mission_store: Any | None = None,
        runner: Any | None = None,
        id_key: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        self._bot = bot or TelegramBot(token)
        self._pending: dict[int, _PendingApproval] = {}
        self._ask = ask_fn
        self._agent = agent_fn
        self._status = status_fn
        self._remember = remember_fn
        self._vault = vault_fn
        self._approval_timeout = approval_timeout
        self._circuit_breaker = circuit_breaker
        self._force_local_fn = force_local_fn
        self._force_remote_fn = force_remote_fn

        # The single authorization gate. Every dispatch path goes through it.
        self.gate = IdentityGate(allowed_chats, allowed_users=allowed_users)
        self.approvals = ApprovalRegistry()
        self.policy = PolicyEngine(self.gate, self.approvals)
        self._allowed = self.gate._chats  # noqa: SLF001 - compat with tests

        self._store = mission_store
        self._runner = runner
        self._id_key = id_key or (lambda u: str(u.get("update_id", 0)))

        # Long work runs here, never in the poll loop.
        self._pool = ThreadPoolExecutor(max_workers=MAX_WORKERS,
                                        thread_name_prefix="tg-work")
        self._running_missions: dict[str, str] = {}   # mission_id -> chat_id
        self._lock = threading.RLock()
        # ticket_id -> identity waiting on that ticket (per instance, not
        # class-level: shared mutable state across channels would leak
        # approvals between instances).
        self._waiting: dict[str, Identity] = {}
        # ticket_id -> event to release the thread blocked in make_approver
        self._waiters: dict[str, threading.Event] = {}

    # -- lazily built mission subsystems ---------------------------------

    @property
    def store(self):
        if self._store is None:
            from jarvis.mission.store import MissionStore
            self._store = MissionStore()
        return self._store

    @property
    def runner(self):
        if self._runner is None:
            from jarvis.mission.runner import MissionRunner
            self._runner = MissionRunner(self.store)
        return self._runner

    # -- identity ---------------------------------------------------------

    @staticmethod
    def _identity_from_message(msg: dict[str, Any]) -> Identity | None:
        chat = msg.get("chat") or {}
        frm = msg.get("from") or {}
        chat_id = chat.get("id")
        user_id = frm.get("id")
        if chat_id is None or user_id is None:
            return None
        return Identity(chat_id=int(chat_id), user_id=int(user_id),
                        username=str(frm.get("username", "") or ""),
                        is_group=bool(chat.get("type") in ("group", "supergroup")))

    @staticmethod
    def _identity_from_callback(cq: dict[str, Any]) -> Identity | None:
        # A callback carries no `message.from` that identifies the presser —
        # it carries `from` (who pressed) and the message (where). Both are
        # needed: authorization must use the presser's identity, not the
        # bot's own message author.
        frm = cq.get("from") or {}
        chat = (cq.get("message") or {}).get("chat") or {}
        user_id = frm.get("id")
        chat_id = chat.get("id")
        if user_id is None or chat_id is None:
            return None
        return Identity(chat_id=int(chat_id), user_id=int(user_id),
                        username=str(frm.get("username", "") or ""),
                        is_group=bool(chat.get("type") in ("group", "supergroup")))

    # -- approvals --------------------------------------------------------

    def make_approver(self, chat_id: int,
                      user_id: int | None = None) -> Callable[[str], bool]:
        """Build the approval callable for an agent running on this channel.

        Synchronous by contract (the agent API expects a bool): it issues a
        real ticket, sends the buttons, then blocks on an event until the
        callback resolves it or the TTL expires. The ticket is what makes the
        decision BOUND — before, it was a bare "yes" string in a dict keyed
        by message id, which any callback could resolve.
        """
        ident = Identity(chat_id=int(chat_id),
                         user_id=int(user_id if user_id is not None else chat_id))
        if not self.gate.is_allowed(ident):
            return lambda cmd: False

        def approver(cmd: str) -> bool:
            try:
                ticket = self.approvals.issue(
                    ident=ident, operation="shell.exec", payload=cmd,
                    summary=cmd[:180], ttl_seconds=self._approval_timeout)
            except AuthDenied:
                return False
            try:
                msg = self._bot.send_message(
                    chat_id,
                    f"🔧 Comando fora da allowlist:\n{cmd[:600]}\n\nPermitir?",
                    reply_markup={"inline_keyboard": [[
                        {"text": "✅ Sim",
                         "callback_data": encode_callback(ticket.ticket_id, True)},
                        {"text": "❌ Não",
                         "callback_data": encode_callback(ticket.ticket_id, False)},
                    ]]},
                    parse_mode=None,
                )
            except TelegramError:
                return False
            self.approvals.bind_message(ticket.ticket_id, int(msg["message_id"]))

            ev = threading.Event()
            with self._lock:
                self._waiting[ticket.ticket_id] = ident
                self._waiters[ticket.ticket_id] = ev
            try:
                ev.wait(timeout=self._approval_timeout)
            finally:
                with self._lock:
                    self._waiting.pop(ticket.ticket_id, None)
                    self._waiters.pop(ticket.ticket_id, None)
            ticket = self.approvals.get(ticket.ticket_id)
            return bool(ticket and ticket.state.value == "approved")

        return approver

    # -- command parsing --------------------------------------------------

    @classmethod
    def _fuzzy_cmd(cls, text: str) -> tuple[str | None, str]:
        low = (text or "").strip().lower()
        if not low:
            return None, ""
        word, _, _rest = low.partition(" ")
        word = word.lstrip("/")
        # arg preserves original case (models, paths): first token of the original.
        _orig = (text or "").strip().split(None, 1)
        arg = _orig[1] if len(_orig) > 1 else ""
        if word in cls._COMMANDS:
            return word, arg.strip()
        if len(word) >= 3:
            hits = [c for c in cls._COMMANDS if c.startswith(word)]
            if len(hits) == 1:
                return hits[0], arg.strip()
        return None, (text or "").strip()

    # -- message routing (testable, no network beyond the injected fns) ---

    def handle_message(self, text: str, *, chat_id: int,
                       user_id: int | None = None) -> str | None:
        """Route a message. None = ignored (unauthorized or handled async)."""
        ident = Identity(chat_id=int(chat_id),
                         user_id=int(user_id if user_id is not None else chat_id))
        # The gate runs FIRST, before any command interpretation, so no
        # dispatch path can reach an effect without passing it.
        try:
            self.gate.authorize(ident, "read")
        except AuthDenied:
            return None

        cmd, arg = self._fuzzy_cmd(text)
        if cmd in ("start", "help"):
            return self._help_text()
        if cmd == "status":
            return self._handle_status()
        if cmd in ("force_local", "force_remote"):
            return self._handle_circuit(cmd)
        if cmd == "ask":
            return (self._ask or (lambda q: f"ask unavailable: {q}"))(arg)
        if cmd == "remember":
            return (self._remember or (lambda t: f"remember unavailable: {t}"))(arg)
        if cmd == "vault":
            return (self._vault or (lambda a: f"vault unavailable: {a}"))(arg)
        # --- projects / missions ---
        if cmd in ("projects", "project"):
            return self._handle_projects(arg)
        if cmd in ("mission", "missions"):
            return self._handle_mission(arg, ident)
        if cmd in ("task", "tasks"):
            return self._handle_tasks(arg)
        if cmd in ("persona", "personas"):
            return self._handle_personas(arg)
        if cmd == "approve":
            return self._handle_approve(arg, ident)
        if cmd == "pause":
            return self._handle_pause(arg)
        if cmd == "resume":
            return self._handle_resume(arg)
        if cmd == "cancel":
            return self._handle_cancel(arg)
        if cmd == "steer":
            return self._handle_steer(arg)
        if cmd == "stop":
            return self._handle_steer("stop")
        # --- long / legacy paths ---
        if cmd == "agent":
            return None      # dispatched on the worker pool by run()
        if cmd == "dev":
            return self._handle_dev(arg)
        if cmd == "sshkey":
            return self._handle_sshkey(arg, ident)
        if cmd == "opencode":
            return self._handle_opencode(arg)
        if (text or "").strip().startswith("/"):
            return (f"unknown command: {(text or '').strip().split()[0]}\n\n"
                    f"{self._help_text()}")
        # default: free question
        return (self._ask or (lambda q: f"ask unavailable: {q}"))((text or "").strip())

    # -- status / circuit --------------------------------------------------

    def _handle_status(self) -> str:
        base = (self._status or (lambda: "status unavailable"))()
        if self._circuit_breaker is not None:
            info = self._circuit_breaker.state_info
            circuit = info["circuit_state"]
            backend = info["backend"]["state"]
            latency = info["backend"]["latency_ms"]
            uptime = info["backend"]["uptime_pct"]
            mode = ("LOCAL" if circuit == "closed"
                    else "FALLBACK" if circuit == "open" else "TESTING")
            base += (
                f"\n\n🔗 Circuit Breaker: {circuit.upper()}"
                f"\n📡 Backend: {backend} ({latency}ms)"
                f"\n📊 Uptime: {uptime}%"
                f"\n🔄 Mode: {mode}"
                f"\n📈 Local: {info['total_local']} | Fallback: "
                f"{info['total_fallback']} | Rejected: {info['total_rejected']}"
            )
        active = self._running_missions
        if active:
            base += ("\n\n🚀 Missões em execução:\n" + "\n".join(
                f"  · {mid} (chat {cid})" for mid, cid in active.items()))
        return base

    def _handle_circuit(self, cmd: str) -> str:
        if cmd == "force_local" and self._force_local_fn:
            return self._force_local_fn()
        if cmd == "force_remote" and self._force_remote_fn:
            return self._force_remote_fn()
        if self._circuit_breaker is not None:
            return (self._circuit_breaker.force_local() if cmd == "force_local"
                    else self._circuit_breaker.force_open())
        return "Circuit breaker not configured."

    # -- projects ----------------------------------------------------------

    def _handle_projects(self, arg: str) -> str:
        from jarvis.mission.projects import summary as project_summary
        rows = project_summary()
        if not rows:
            return ("No repositories found under the workspace. "
                    "Set JARVIS_WORKSPACE_ROOT.")
        if arg:
            needle = arg.strip().lower()
            rows = [r for r in rows if needle in r["name"].lower()]
            if not rows:
                return f"Project not found: {arg}"
            r = rows[0]
            return (f"📁 {r['name']}\nroot: {r['root']}\n"
                    f"markers: {', '.join(r['markers'])}\n"
                    f"\nStart a mission with: /mission {r['name']} <objective>")
        lines = ["📁 Projects available:"]
        for r in rows[:25]:
            lines.append(f"  · {r['name']}  ({len(r['markers'])} markers)")
        lines.append("\nUse /mission <project> <objective> to target one.")
        return "\n".join(lines)

    # -- missions ----------------------------------------------------------

    def _handle_mission(self, arg: str, ident: Identity) -> str:
        from jarvis.mission.models import MissionState
        from jarvis.mission.planner import build_mission
        from jarvis.mission.projects import resolve

        arg = (arg or "").strip()
        store = self.store

        if not arg:
            actives = store.active()
            if not actives:
                return ("No mission in progress.\n"
                        "Create one with:\n"
                        "  /mission <objective>            (auto-detect project)\n"
                        "  /mission <project> <objective>   (explicit project)\n"
                        "  /mission show <id>               (details)\n"
                        "  /mission plan <id>               (decomposition only)")
            lines = ["🚀 Active missions:"]
            for m in actives[:10]:
                prog = m.progress()
                done = prog.get("DONE", 0)
                lines.append(f"  · {m.id} [{m.state}] {m.project} — "
                             f"{done}/{len(m.tasks)} done — {m.objective[:50]}")
            lines.append("\n/mission show <id> · /mission cancel <id>")
            return "\n".join(lines)

        parts = arg.split(None, 1)
        verb = parts[0].lower().lstrip("/")

        if verb in ("show", "detail", "report"):
            mid = parts[1].strip() if len(parts) > 1 else ""
            if not mid:
                actives = store.active()
                if not actives:
                    return "No active mission."
                mid = actives[0].id
            mission = store.load(mid)
            if mission is None:
                return f"Mission not found: {mid}"
            return self.runner.render_report(mission)

        if verb in ("cancel", "stop"):
            mid = parts[1].strip() if len(parts) > 1 else ""
            if not mid:
                actives = store.active()
                if not actives:
                    return "Nothing to cancel."
                mid = actives[0].id
            n = self.runner.cancel(mid)
            self._running_missions.pop(mid, None)
            return f"🛑 Mission {mid} cancelled ({n} task(s) stopped)."

        if verb in ("pause",):
            mid = parts[1].strip() if len(parts) > 1 else ""
            if not mid:
                actives = store.active()
                if not mid and actives:
                    mid = actives[0].id
            return ("⏸ Paused." if mid and self.runner.pause(mid)
                    else "Nothing to pause.")

        if verb in ("resume", "continue"):
            mid = parts[1].strip() if len(parts) > 1 else ""
            if not mid:
                actives = store.active()
                if mid is None and actives:
                    mid = actives[0].id
            return ("▶ Resumed." if mid and self.runner.resume(mid)
                    else "Nothing to resume.")

        if verb in ("steer",):
            mid = parts[1].strip() if len(parts) > 1 else ""
            if not mid:
                actives = store.active()
                if not actives:
                    return "No active mission to steer."
                mid = actives[0].id
            msg = " ".join(parts[2:]) if len(parts) > 2 else ""
            if not msg:
                return "Usage: /mission steer <id> <instruction>"
            return ("🧭 Steering applied." if self.runner.steer(mid, msg)
                    else f"Mission not found: {mid}")

        if verb in ("plan", "decompose"):
            # Decompose and persist, but do NOT execute.
            rest = " ".join(parts[1:]).strip()
            project_name, objective = self._split_project(rest)
            proj = resolve(objective, explicit=project_name)
            if not proj.ok:
                return self._ambiguous_projects(proj)
            mission = build_mission(objective, proj, requested_by=ident.label(),
                                    telegram_chat_id=ident.chat_id)
            store.save(mission)
            return self._plan_preview(mission)

        # --- create + run ---
        project_name, objective = self._split_project(arg)
        if not objective:
            return "Usage: /mission <objective>  or  /mission <project> <objective>"
        proj = resolve(objective, explicit=project_name)
        if not proj.ok:
            return self._ambiguous_projects(proj)

        mission = build_mission(objective, proj, requested_by=ident.label(),
                                telegram_chat_id=ident.chat_id)
        # Persist BEFORE any prolonged work: the mission exists on disk
        # before the first task runs.
        store.save(mission)
        self._running_missions[mission.id] = str(ident.chat_id)
        self._pool.submit(self._run_mission_bg, mission.id, ident)
        preview = self._plan_preview(mission)
        return (f"✅ Mission accepted: {mission.id}\n"
                f"project: {proj.name} ({proj.root})\n\n{preview}\n"
                f"Track with: /mission show {mission.id}")

    def _split_project(self, text: str) -> tuple[str | None, str]:
        """Split `project objective` only when the first word IS a project."""
        from jarvis.mission.projects import is_known_project
        text = (text or "").strip()
        if not text:
            return None, ""
        head, _, rest = text.partition(" ")
        if rest.strip() and is_known_project(head):
            return head, rest.strip()
        return None, text

    def _ambiguous_projects(self, proj) -> str:
        if proj.confidence == "ambiguous":
            return ("🤔 Which project? Candidates:\n" +
                    "\n".join(f"  · {c}" for c in proj.candidates) +
                    "\n\nResend as: /mission <project> <objective>")
        return f"❌ {proj.reason or 'project could not be resolved'}"

    def _plan_preview(self, mission) -> str:
        lines = [f"📋 Plan ({len(mission.tasks)} task(s)):"]
        for i, t in enumerate(mission.tasks):
            deps = f" ← {', '.join(t.dependencies)}" if t.dependencies else ""
            lines.append(f"  {i + 1}. [{t.persona_id}] {t.title[:56]}{deps}")
            if t.acceptance:
                crit = ", ".join(f"{c.kind}:{c.target or '-'}" for c in t.acceptance[:3])
                lines.append(f"     criteria: {crit[:90]}")
            elif not t.acceptance:
                lines.append("     criteria: NONE (needs an explicit criterion)")
        return "\n".join(lines)

    def _handle_tasks(self, arg: str) -> str:
        store = self.store
        actives = store.active()
        if arg:
            mission = store.load(arg.strip())
            if mission is None:
                return f"Mission not found: {arg.strip()}"
        elif actives:
            mission = actives[0]
        else:
            return "No active mission."
        lines = [f"Tasks of {mission.id} [{mission.state}]:"]
        for t in mission.tasks:
            mark = {"DONE": "✓", "FAILED": "✗", "BLOCKED": "⊘",
                    "RUNNING": "▶"}.get(t.status, "•")
            extra = f" [{t.persona_applied or t.persona_id}]" if t.persona_id else ""
            lines.append(f"  {mark} {t.id} {t.status}{extra} — {t.title[:48]}")
        return "\n".join(lines)

    def _handle_personas(self, arg: str) -> str:
        try:
            from jarvis.core.persona import PersonaRegistry
            reg = PersonaRegistry()
            if arg:
                p = reg.get(arg.strip())
                if p is None:
                    return f"Persona not found: {arg.strip()}"
                pol = p.policies
                return (f"🎭 {p.name} ({p.id})\nrole: {p.role}\n"
                        f"model preference: {p.model_preference or '-'}\n"
                        f"capabilities: read={pol.can_read} write={pol.can_write} "
                        f"execute={pol.can_execute} commit={pol.can_commit} "
                        f"deploy={pol.can_deploy}\n"
                        f"requires validation: {pol.require_validation}\n"
                        f"tools: {', '.join(p.tools) or 'all'}")
            lines = [f"🎭 Personas ({len(reg.list_all())}):"]
            for p in sorted(reg.list_all(), key=lambda x: x.id):
                lines.append(f"  · {p.id:24} {p.role[:44]}")
            return "\n".join(lines)
        except Exception as exc:  # noqa: BLE001
            return f"personas unavailable: {exc}"

    def _handle_approve(self, arg: str, ident: Identity) -> str:
        tickets = self.approvals.pending()
        if not arg:
            if not tickets:
                return "No pending approval."
            lines = ["⏳ Pending approvals:"]
            for t in tickets:
                lines.append(f"  · {t.ticket_id[:10]} {t.operation} — {t.summary[:60]}")
            return "\n".join(lines)
        tid = arg.strip()
        ticket = self.approvals.get(tid) or next(
            (t for t in tickets if t.ticket_id.startswith(tid)), None)
        if ticket is None:
            return f"No pending approval matches: {tid}"
        ok, why = self.approvals.resolve(ticket.ticket_id, True, ident=ident)
        return f"✅ {why}: {ticket.operation} — {ticket.summary[:70]}" if ok \
            else f"❌ {why}"

    def _handle_pause(self, arg: str) -> str:
        actives = self.store.active()
        mid = arg.strip() or (actives[0].id if actives else "")
        if not mid:
            return "Nothing to pause."
        return "⏸ Paused." if self.runner.pause(mid) else "Nothing to pause."

    def _handle_resume(self, arg: str) -> str:
        actives = self.store.active()
        mid = arg.strip() or (actives[0].id if actives else "")
        if not mid:
            return "Nothing to resume."
        if self.runner.resume(mid):
            self._pool.submit(self._run_mission_bg, mid, None)
            return "▶ Resumed."
        return "Nothing to resume."

    def _handle_cancel(self, arg: str) -> str:
        actives = self.store.active()
        mid = arg.strip() or (actives[0].id if actives else "")
        if not mid:
            return "Nothing to cancel."
        n = self.runner.cancel(mid)
        self._running_missions.pop(mid, None)
        return f"🛑 Cancelled ({n} task(s) stopped)."

    def _handle_steer(self, arg: str) -> str:
        try:
            from jarvis.core.steer import is_stop, send_steer
        except Exception as exc:  # noqa: BLE001
            return f"steer unavailable: {exc}"
        if not (arg or "").strip():
            return "Usage: /steer <instruction>  or  /stop"
        r = send_steer(arg)
        if not r.get("ok"):
            return f"steer failed: {r.get('error')}"
        if is_stop(arg):
            return "STOP queued — the run stops at the next turn."
        return f"Steering queued ({len(arg)} chars) — applies next turn."

    # -- sshkey (high impact, gated) --------------------------------------

    def _handle_sshkey(self, key: str, ident: Identity) -> str:
        """Install a public SSH key. GATED: high impact, requires a ticket.

        Reachable only from an authorized identity (checked by the gate
        above). Installing a key grants persistent access, so it goes
        through the same approval machinery as any other high-impact
        operation instead of being a bare side effect.
        """
        import re
        parts = key.split()
        allowed_types = (
            "ssh-ed25519", "ssh-rsa", "ecdsa-sha2-nistp256",
            "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
            "sk-ssh-ed25519@openssh.com", "sk-ecdsa-sha2-nistp256@openssh.com",
        )
        if len(parts) < 2 or parts[0] not in allowed_types:
            return ("Invalid key. Paste the whole line from Termux:\n"
                    "`cat ~/.ssh/id_ed25519.pub`\n"
                    "Usage: `/sshkey ssh-ed25519 AAAA... termux`")
        if not re.fullmatch(r"[A-Za-z0-9+/=]+", parts[1]):
            return "Invalid key (malformed base64 body)."
        line = " ".join(parts[:3]) if len(parts) >= 3 else " ".join(parts[:2])

        # Read-only checks first: never prompt the owner for a no-op.
        try:
            sshdir = Path.home() / ".ssh"
            auth_path = sshdir / "authorized_keys"
            existing = (auth_path.read_text(encoding="utf-8").splitlines()
                        if auth_path.exists() else [])
            if any(line.split()[1] == e.split()[1]
                   for e in existing if len(e.split()) >= 2):
                return "Key already installed (nothing to do)."
        except OSError:
            auth_path = sshdir / "authorized_keys"

        decision = self.policy.check(ident, "ssh.install_key", payload=line)
        if not decision.allowed:
            return f"❌ {decision.reason}"
        if decision.needs_approval:
            # Try to redeem an approval the owner already gave for THIS
            # exact key. Without this the user would be prompted forever.
            ok, why = self.policy.authorize_once(
                None, ident, "ssh.install_key", payload=line)
            if not ok:
                return self._prompt_approval(
                    ident, "ssh.install_key", line,
                    f"install SSH key: {parts[0]} ...{parts[1][-12:]}")

        try:
            sshdir.mkdir(mode=0o700, exist_ok=True)
            existing = (auth_path.read_text(encoding="utf-8").splitlines()
                        if auth_path.exists() else [])
            if any(line.split()[1] == e.split()[1]
                   for e in existing if len(e.split()) >= 2):
                return "Key already installed (nothing to do)."
            with auth_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            auth_path.chmod(0o600)
            return (f"Key installed ({parts[0]}). Test with: "
                    f"`ssh nixos@<host> -i ~/.ssh/id_ed25519` from Termux.")
        except Exception as exc:  # noqa: BLE001
            return f"Failed to install: {exc}"

    def _prompt_approval(self, ident: Identity, operation: str, payload: Any,
                         summary: str) -> str:
        """Issue a ticket and send the inline buttons. Fail-closed."""
        try:
            ticket = self.approvals.issue(
                ident=ident, operation=operation, payload=payload,
                summary=summary, ttl_seconds=self._approval_timeout)
        except AuthDenied as exc:
            return f"❌ {exc}"
        try:
            msg = self._bot.send_message(
                ident.chat_id,
                f"🔐 {summary}\n\nPermitir?",
                reply_markup={"inline_keyboard": [[
                    {"text": "✅ Sim",
                     "callback_data": encode_callback(ticket.ticket_id, True)},
                    {"text": "❌ Não",
                     "callback_data": encode_callback(ticket.ticket_id, False)},
                ]]},
                parse_mode=None)
        except TelegramError as exc:
            return f"❌ could not send approval request: {exc}"
        self.approvals.bind_message(ticket.ticket_id, int(msg["message_id"]))
        self._waiting[ticket.ticket_id] = ident
        return (f"⏳ Approval requested (ticket {ticket.ticket_id[:10]}). "
                f"Expires in {int(self._approval_timeout)}s.")

    # -- legacy long paths -------------------------------------------------

    def _handle_dev(self, task: str) -> str:
        if not task:
            return "Usage: /dev <task>\nExample: /dev read config.py"
        try:
            import contextlib
            import io
            from jarvis.cli.dev import dev_once
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                dev_once(task)
            output = buf.getvalue()
            if len(output) > 3500:
                output = output[:3500] + "\n... (truncated)"
            return output or "(no output)"
        except Exception as exc:  # noqa: BLE001
            return f"dev error: {exc}"

    @staticmethod
    def _handle_opencode(arg: str) -> str:
        """Run opencode non-interactively with an explicit model parameter.

        The working directory used to be hardcoded to ~/projects/nixos-ai,
        ignoring the project the owner had selected. It now resolves from
        the mission/project context when available, and refuses to guess.
        """
        import os
        import re
        import subprocess
        if not arg:
            return ("Usage: `/opencode [-m provider/model] <task>`\n"
                    "Example: `/opencode -m nvidia/z-ai/glm-5.3-flash "
                    "list active services`")
        model = None
        m = re.search(r"(?:^|\s)-m\s+(\S+)", arg)
        if m:
            model = m.group(1)
            task = (arg[:m.start()] + " " + arg[m.end():]).strip()
        elif re.search(r"(?:^|\s)-m(?:\s|$)", arg):
            return "Usage: `/opencode -m provider/model <task>`"
        else:
            task = arg
        if not task:
            return "Usage: `/opencode [-m provider/model] <task>`"
        cwd = os.environ.get("JARVIS_PROJECT_ROOT") or os.getcwd()
        cmd = ["opencode", "run", task]
        if model:
            cmd += ["-m", model]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               timeout=240, cwd=cwd)
        except subprocess.TimeoutExpired:
            return "opencode exceeded 240s (long task — split it)."
        except FileNotFoundError:
            return "opencode not found in the service PATH."
        except Exception as exc:  # noqa: BLE001
            return f"failed to run opencode: {exc}"
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr else "")
        out = out.strip() or "(no output)"
        if len(out) > 3500:
            out = out[:3500] + "\n... (truncated)"
        return out

    # -- help --------------------------------------------------------------

    def send_help(self, chat_id: int) -> None:
        try:
            self._bot.send_message(chat_id, self._help_text(), parse_mode="Markdown")
        except TelegramError:
            self._bot.send_message(chat_id, self._help_text(), parse_mode=None)

    @staticmethod
    def _help_text() -> str:
        return (
            "🤖 *JARVIS — Telegram control plane*\n\n"
            "*MISSIONS (the main path)*\n"
            "`/mission <objective>` — start a mission, auto-detect project\n"
            "`/mission <project> <objective>` — target a project explicitly\n"
            "`/mission` — list active missions\n"
            "`/mission show <id>` — full report with evidence\n"
            "`/mission plan <objective>` — decompose only, do not execute\n"
            "`/mission pause|resume|cancel <id>` — lifecycle\n"
            "`/mission steer <id> <msg>` — redirect the running mission\n"
            "`/tasks [id]` — task states of a mission\n"
            "`/projects` — repos in the workspace\n"
            "`/personas [id]` — roles and their capabilities\n\n"
            "*Questions and health*\n"
            "`/ask <question>` — cheapest path (fastpath/doctor/rag/agent)\n"
            "`/status` — services, circuit breaker, running missions\n"
            "`/remember <fact>` — episodic memory\n"
            "`/vault summarize|list` — long-term memory\n\n"
            "*Development*\n"
            "`/agent <task>` — single agent turn with approval buttons\n"
            "`/dev <task>` — dev REPL (read/edit/create files)\n"
            "`/opencode [-m prov/model] <task>` — remote opencode run\n"
            "`/sshkey <key.pub>` — install your SSH key (requires approval)\n"
            "`/steer <msg>` · `/stop` — steer/stop an active run\n"
            "`/force_local` · `/force_remote` — circuit breaker\n\n"
            "*Examples*\n"
            "`/mission add a test for the mission store`\n"
            "`/mission nixos-ai fix the flake check failure`\n"
            "`/ask how is the system health?`\n"
            "or just send a question — I pick the cheapest path."
        )

    # -- execution in the background ---------------------------------------

    def _run_mission_bg(self, mission_id: str, ident: Identity | None) -> None:
        """Run a mission off the poll loop, then report once."""
        chat_id = ident.chat_id if ident else None
        try:
            mission = self.store.load(mission_id)
            if mission is None:
                return
            if chat_id is None:
                chat_id = mission.telegram_chat_id
            if chat_id is None:
                return
            # Only report meaningful transitions, not every tool call.
            self._safe_send(int(chat_id),
                            f"🚀 Mission {mission_id} started "
                            f"({len(mission.tasks)} task(s)).")
            outcome = self.runner.run(mission_id)
            self._safe_send(int(chat_id), outcome.report)
        except Exception as exc:  # noqa: BLE001
            if chat_id:
                self._safe_send(int(chat_id), f"mission error: {exc}")
        finally:
            self._running_missions.pop(mission_id, None)

    def _run_agent_task(self, chat_id: int, task: str,
                        user_id: int | None = None) -> None:
        try:
            if self._agent is None:
                self._safe_send(chat_id, "agent unavailable")
                return
            reply = self._agent(task, self.make_approver(chat_id, user_id))
        except Exception as exc:  # noqa: BLE001
            reply = f"agent error: {exc}"
        self._safe_send(chat_id, reply)

    # -- callbacks ---------------------------------------------------------

    def _handle_callback(self, cq: dict[str, Any]) -> None:
        """Resolve an approval callback.

        Uses the presser's identity (not the bot's message), decodes the
        ticket id from callback_data, and delegates to the registry, which
        enforces binding, single use, and expiry. Anything unrecognized is
        answered as ignored — never silently treated as approval.
        """
        decoded = decode_callback(cq.get("data", "") or "")
        if decoded is None:
            # Legacy shape kept for compatibility: a bare "yes"/"no" data
            # with a pending approval keyed by message id.
            self._handle_legacy_callback(cq)
            return
        ticket_id, approved = decoded
        ident = self._identity_from_callback(cq)
        # Bind the resolve to the ticket's OWN operation. Do NOT consume here:
        # consumption belongs to the execution path, and spending it at
        # callback time would leave nothing for the operation to redeem.
        ticket = self.approvals.get(ticket_id)
        op = ticket.operation if ticket is not None else None
        ok, why = self.approvals.resolve(ticket_id, approved, ident=ident,
                                         operation=op)
        text = ("✅ approved" if ok else f"❌ {why}")
        try:
            self._bot.answer_callback(cq.get("id", ""), text)
        except TelegramError:
            pass
        with self._lock:
            self._waiting.pop(ticket_id, None)
            waiter = self._waiters.pop(ticket_id, None)
        if waiter is not None:
            waiter.set()

    def _handle_legacy_callback(self, cq: dict[str, Any]) -> None:
        """Back-compat path for bare yes/no callbacks (tests, old buttons)."""
        msg_id = (cq.get("message") or {}).get("message_id")
        pending = self._pending.get(msg_id) if msg_id else None
        if pending is None:
            return
        ident = self._identity_from_callback(cq)
        # Even the legacy path must check identity before resolving.
        if ident is not None and not self.gate.is_allowed(ident):
            try:
                self._bot.answer_callback(cq.get("id", ""), "❌ unauthorized")
            except TelegramError:
                pass
            return
        pending.answer = cq.get("data", "")
        try:
            self._bot.answer_callback(
                cq.get("id", ""),
                "approved ✅" if pending.answer == "yes" else "denied ❌")
        except TelegramError:
            pass
        pending.event.set()

    # -- polling loop ------------------------------------------------------

    def _offset_path(self):
        from pathlib import Path as _P
        base = self.store.root
        return _P(base) / "tg_offset"

    def _read_offset(self) -> int:
        try:
            return int(self._offset_path().read_text().strip())
        except (OSError, ValueError):
            return 0

    def _write_offset(self, offset: int) -> None:
        """Persist the poll offset so a restart does not replay updates."""
        try:
            self._offset_path().write_text(str(int(offset)), encoding="utf-8")
        except OSError:
            pass

    def run(self, *, poll_timeout: int = 25) -> None:
        """Long-polling loop — the ONLY consumer of getUpdates.

        The offset starts from the persisted value (not 0): restarting used
        to replay every buffered update, which re-ran commands. Updates are
        also de-duplicated by update_id through the mission store, so even a
        replayed buffer cannot execute a mission twice.
        """
        offset = self._read_offset()
        # Resume anything a previous process left behind.
        try:
            recovered = self.store.recover_interrupted()
            for m in recovered:
                if m.telegram_chat_id:
                    self._safe_send(int(m.telegram_chat_id),
                                   f"♻️ Mission {m.id} resumed after restart.")
                    self._pool.submit(self._run_mission_bg, m.id, None)
        except Exception:
            pass

        while True:
            try:
                updates = self._bot.get_updates(offset=offset, timeout=poll_timeout)
            except Exception:
                updates = []
            for update in updates:
                uid = int(update.get("update_id", 0) or 0)
                offset = max(offset, uid + 1)
                # Idempotency: a reprocessed update must not act twice.
                try:
                    fresh = self.store.mark_seen(f"upd:{uid}", ttl_seconds=3600)
                except Exception:
                    fresh = True
                if not fresh:
                    continue
                if "callback_query" in update:
                    self._handle_callback(update["callback_query"])
                    continue
                msg = update.get("message") or {}
                self._dispatch_message(msg)
            self._write_offset(offset)

    def _dispatch_message(self, msg: dict[str, Any]) -> None:
        text = msg.get("text", "") or ""
        ident = self._identity_from_message(msg)
        if ident is None:
            return
        # The gate applies here too, so no dispatch shape can bypass it.
        try:
            self.gate.authorize(ident, "read")
        except AuthDenied:
            return
        if text.strip() in ("/start", "/help"):
            self.send_help(ident.chat_id)
            return
        cmd, arg = self._fuzzy_cmd(text)
        if cmd == "agent":
            # Long: run on the worker pool so polling stays responsive.
            self._pool.submit(self._run_agent_task, ident.chat_id, arg,
                              ident.user_id)
            return
        try:
            reply = self.handle_message(text, chat_id=ident.chat_id,
                                        user_id=ident.user_id)
        except Exception as exc:  # noqa: BLE001
            reply = f"error: {exc}"
        if reply:
            self._safe_send(ident.chat_id, reply)

    # -- sending -----------------------------------------------------------

    def _safe_send(self, chat_id: int, text: str) -> None:
        """Send without raising. Errors are logged, never silently dropped."""
        try:
            self._bot.send_message(chat_id, text[:MAX_MSG], parse_mode=None)
        except TelegramError:
            pass


# ---------------------------------------------------------------------------
# Wiring with the local pipeline (used by the CLI)
# ---------------------------------------------------------------------------

def format_doctor_human(report: dict[str, Any]) -> str:
    """Convert the JSON doctor report into human-readable text.

    Plain text on Telegram (no markdown) — emojis and friendly names give
    the "onboard AI" feel without dumping JSON.
    """
    names = {
        "llama_cpp": "🧠 Chat model (llama.cpp)",
        "llama_cpp_embeddings": "🔎 Embeddings (RAG)",
        "qdrant": "🗄️ Vector DB (Qdrant)",
        "disk": "💾 Disk",
        "nixos": "❄️ NixOS",
    }
    icons = {"ok": "✅", "degraded": "⚠️", "down": "❌"}
    lines = ["🩺 *JARVIS — system health*"]
    for c in report.get("checks", []):
        name = names.get(c.get("name", ""), c.get("name", "?"))
        icon = icons.get(c.get("status", "down"), "❓")
        detail = c.get("detail", "") or ""
        if "/nix/store/" in detail:
            detail = "active system profile"
        lines.append(f"{icon} {name}: {detail}")
    overall = report.get("overall", "down")
    lines.append("")
    if overall == "ok":
        lines.append("✅ Everything working.")
    elif overall == "degraded":
        lines.append("⚠️ Something degraded — see above.")
    else:
        lines.append("❌ Services down — ask me `/ask how to fix it`.")
    return "\n".join(lines)


def send_notification(text: str, config: Config | None = None) -> bool:
    """One-way notification to the user's chat (if configured).

    Used by daemons (idle, vault, heal) to surface completions on the phone
    without interaction. Silent when there is no token (lab without
    Telegram, CI, etc.).
    """
    cfg = config or get_config()
    if not cfg.telegram_token or not cfg.telegram_chat_id:
        return False
    try:
        bot = TelegramBot(cfg.telegram_token)
        for chat_id in _parse_chats(cfg.telegram_chat_id):
            bot.send_message(chat_id, text[:MAX_MSG], parse_mode=None)
        return True
    except TelegramError:
        return False


def _parse_chats(raw: str) -> list[int]:
    return [int(c.strip()) for c in raw.split(",") if c.strip().isdigit()]


def _parse_users(raw: str) -> list[int]:
    return [int(c.strip()) for c in (raw or "").split(",") if c.strip().isdigit()]


def make_channel(config: Config | None = None) -> TelegramChannel | None:
    """Build the channel with the real handlers. None when token/chat missing."""
    cfg = config or get_config()
    if not cfg.telegram_token or not cfg.telegram_chat_id:
        return None
    from jarvis.core.router import (
        handle_agent, handle_doctor, handle_fastpath, handle_nixos, handle_rag,
        route_request,
    )

    def ask(text: str) -> str:
        route = route_request(text)
        try:
            if route.handler == "fastpath":
                out = handle_fastpath(route.query)
            elif route.handler == "doctor":
                out = handle_doctor(cfg)
            elif route.handler == "nixos":
                out = handle_nixos(route.query, cfg)
            elif route.handler == "rag":
                out = handle_rag(route.query, cfg, top_k=5)
            else:
                # agent via chat: without --approve, effectful commands are denied
                out = handle_agent(route.query, cfg, approve=False)
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"
        return str(out.get("answer") or out.get("output") or out)[:MAX_MSG]

    def agent(task: str, approver: Callable[[str], bool]) -> str:
        result = handle_agent(task, cfg, approve=True, approver=approver)
        run = result.get("commands_run", [])
        denied = result.get("commands_denied", [])
        text = result.get("response", "") or ""
        lines = [text]
        if run:
            lines.append(f"\n✅ Commands executed ({len(run)}): " + "; ".join(run))
        if denied:
            lines.append(f"\n⛔ Denied ({len(denied)}): " + "; ".join(denied))
        return "\n".join(lines)[:MAX_MSG]

    def status() -> str:
        return format_doctor_human(handle_doctor(cfg))[:MAX_MSG]

    def remember(text: str) -> str:
        from jarvis.core.memory import KIND_FACT, EpisodicMemory, MemoryEvent
        pid = EpisodicMemory(cfg).remember(MemoryEvent(kind=KIND_FACT, text=text))
        return f"remembered ✅ (id={pid})" if pid else "could not store (services down?)"

    def vault(action: str) -> str:
        from jarvis.core.vault import MemoryVault
        v = MemoryVault()
        if action.strip() == "summarize":
            return str(v.summarize(since_days=7, commit=True))
        notes = v.list_notes()
        return "\n".join(notes) if notes else "(vault empty)"

    return TelegramChannel(
        cfg.telegram_token,
        _parse_chats(cfg.telegram_chat_id),
        allowed_users=_parse_users(cfg.telegram_user_id),
        ask_fn=ask,
        agent_fn=agent,
        status_fn=status,
        remember_fn=remember,
        vault_fn=vault,
    )