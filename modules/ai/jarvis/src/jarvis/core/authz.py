"""Authorization and bound approval — the single policy choke point.

Concrete problems this module solves (measured, not theoretical):

1. The Telegram polling loop dispatched `/agent <task>` onto a thread
   BEFORE `handle_message`, which is where the chat allowlist lived. Any
   chat_id could execute a full agent run.
2. Approval was an in-memory dict keyed by `message_id`, and callback_data
   was the bare string "yes"/"no". Nothing bound the decision to the
   operation, to the user, or to an expiry: a repeated, stale, or
   foreign-user callback resolved whatever approval happened to be pending.
3. Risk was not policy: either everything passed, or everything demanded a
   button.

What this module provides:

- `Identity` + `IdentityGate`: extract chat_id/user_id from an update and
  decide BEFORE any side effect. One single gate.
- `RiskPolicy` (`classify`): maps an operation to ROUTINE (auto),
  APPROVAL (owner ticket required), or DENY (never, even with a ticket).
- `ApprovalTicket` + `ApprovalRegistry`: single-use ticket bound to
  (user, chat, operation, payload digest) with real expiry. A stale,
  duplicated, foreign, or wrong-operation callback cannot authorize.

Nothing here knows about Telegram: it is pure policy, testable without
network. The provider adapts a Bot API update into `Identity` and a
callback into a ticket id.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Iterable


# ── Risk ──────────────────────────────────────────────────────────────────

class Risk(str, Enum):
    """Operation risk class. Policy maps operation -> risk."""

    ROUTINE = "routine"    # read, status, memory: proceeds automatically
    APPROVAL = "approval"  # world effect: requires an owner ticket
    DENY = "deny"          # never executable from this channel


# High-impact operation suffixes. Exact match or namespace prefix
# ("deploy.*", "git.push").
_HIGH_IMPACT: tuple[str, ...] = (
    "shell", "shell.exec", "write", "write_file", "str_replace",
    "git.commit", "git.push", "deploy", "nixos.rebuild",
    "sshkey", "ssh.install_key", "mission.exec",
)

# Operations NO remote channel may ever execute. Explicit list
# (fail-closed): a new capability does not land here by accident, it has
# to be declared.
_DENIED: frozenset[str] = frozenset({
    "sudo.elevate", "shell.sudo", "vault.keygen", "system.reboot",
    "system.shutdown", "store.purge",
})

# Declared explicitly; everything else falls through to APPROVAL.
_ROUTINE: frozenset[str] = frozenset({
    "status", "doctor", "read", "read_file", "list_directory",
    "memory.remember", "memory.recall", "vault.list", "rag.search",
    "mission.list", "mission.get", "persona.list", "persona.get",
    "project.list", "project.resolve", "task.list", "help",
})


def classify(operation: str) -> Risk:
    """Map an operation name to a risk class. Default = APPROVAL (fail-closed).

    Defaulting to approval instead of routine is deliberate: a new
    capability must not become "routine" by omission — it has to be listed
    in `_ROUTINE` to proceed automatically.
    """
    op = (operation or "").strip()
    if op in _DENIED:
        return Risk.DENY
    if op in _ROUTINE:
        return Risk.ROUTINE
    for suffix in _HIGH_IMPACT:
        if op == suffix or op.endswith("." + suffix) or op.endswith("." + suffix.split(".")[-1]):
            return Risk.APPROVAL
    return Risk.APPROVAL


# ── Identity ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Identity:
    """Who is speaking. Never optional — an update without identity is rejected."""

    chat_id: int
    user_id: int
    username: str = ""
    is_group: bool = False

    def label(self) -> str:
        who = self.username or str(self.user_id)
        return f"{who}@{self.chat_id}"


class AuthDenied(PermissionError):
    """Authorization failure. Carries an auditable reason (never a secret)."""


class IdentityGate:
    """Chat AND user allowlist with a single gate.

    Before, the gate was scattered: `handle_message` checked the chat,
    `run()` checked nothing. Here it is one object and every dispatch path
    goes through `authorize()` BEFORE any effect.
    """

    def __init__(
        self,
        allowed_chats: Iterable[int],
        *,
        allowed_users: Iterable[int] | None = None,
    ) -> None:
        self._chats = {int(c) for c in allowed_chats if int(c) != 0}
        # No user list = chat id alone is the criterion (backward compatible
        # with chat_id configuration). With a list, BOTH must match.
        self._users = {int(u) for u in (allowed_users or ()) if int(u) != 0}

    @property
    def has_chats(self) -> bool:
        return bool(self._chats)

    def is_allowed(self, ident: Identity) -> bool:
        if not self._chats:
            return False
        if ident.chat_id not in self._chats:
            return False
        if self._users and ident.user_id not in self._users:
            return False
        return True

    def authorize(self, ident: Identity | None, operation: str) -> Identity:
        """The single gate. Raises `AuthDenied` before any effect.

        `ident is None` means an update with no identifiable origin (e.g.
        a malformed callback). It never passes.
        """
        if ident is None:
            raise AuthDenied("update without identity (chat_id/user_id)")
        if not self.has_chats:
            raise AuthDenied("no authorized chat configured")
        if not self.is_allowed(ident):
            raise AuthDenied(f"unauthorized chat/user: {ident.label()}")
        risk = classify(operation)
        if risk is Risk.DENY:
            raise AuthDenied(f"operation denied by policy: {operation}")
        return ident


# ── Bound approval ─────────────────────────────────────────────────────────

def payload_digest(operation: str, payload: Any) -> str:
    """Hash of the exact approved content. A callback for other content misses."""
    raw = f"{operation}\x00{payload!r}".encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()[:32]


class ApprovalState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CONSUMED = "consumed"   # already spent to authorize (single use)


@dataclass
class ApprovalTicket:
    ticket_id: str
    operation: str
    digest: str
    chat_id: int
    user_id: int
    risk: Risk
    summary: str
    created_at: float = field(default_factory=time.time)
    ttl_seconds: float = 300.0
    message_id: int | None = None
    state: ApprovalState = ApprovalState.PENDING

    @property
    def expires_at(self) -> float:
        return self.created_at + self.ttl_seconds

    def is_expired(self, now: float | None = None) -> bool:
        return (now or time.time()) >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id, "operation": self.operation,
            "digest": self.digest, "chat_id": self.chat_id,
            "user_id": self.user_id, "risk": self.risk.value,
            "summary": self.summary[:200], "created_at": self.created_at,
            "expires_at": self.expires_at, "message_id": self.message_id,
            "state": self.state.value, "ttl_seconds": self.ttl_seconds,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApprovalTicket:
        return cls(
            ticket_id=d["ticket_id"], operation=d["operation"],
            digest=d["digest"], chat_id=int(d["chat_id"]),
            user_id=int(d["user_id"]),
            risk=Risk(d.get("risk", "approval")),
            summary=d.get("summary", ""),
            created_at=float(d.get("created_at", time.time())),
            ttl_seconds=float(d.get("ttl_seconds", 300.0)),
            message_id=d.get("message_id"),
            state=ApprovalState(d.get("state", "pending")),
        )


# Bot API callback_data limit: 1..64 bytes. "ap:<32 hex>:<yes|no>" = 40 bytes.
CB_PREFIX = "ap"


def encode_callback(ticket_id: str, approved: bool) -> str:
    return f"{CB_PREFIX}:{ticket_id}:{'yes' if approved else 'no'}"


def decode_callback(data: str) -> tuple[str, bool] | None:
    """-> (ticket_id, approved), or None if this is not one of our callbacks.

    Tolerates Forms: `ap:<id>:yes`. Anything else is None (the provider
    answers "ignored" and touches nothing).
    """
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != CB_PREFIX:
        return None
    verdict = parts[2].lower()
    if verdict not in ("yes", "no"):
        return None
    if not parts[1] or len(parts[1]) > 40:
        return None
    return parts[1], verdict == "yes"


class ApprovalRegistry:
    """Approval tickets: single use, bound, expiring.

    Thread-safe (the polling loop and execution threads run in parallel).
    `resolve` is compare-and-set: the first resolve wins, later ones get the
    real state back and authorize nothing.
    """

    def __init__(self, *, clock: Callable[[], float] | None = None) -> None:
        self._tickets: dict[str, ApprovalTicket] = {}
        self._lock = threading.RLock()
        self._clock = clock or time.time
        # Security audit trail: every attempt is kept, including denials.
        self.audit: list[dict[str, Any]] = []

    # -- issuing ----------------------------------------------------------

    def issue(
        self,
        *,
        ident: Identity,
        operation: str,
        payload: Any = None,
        summary: str = "",
        ttl_seconds: float = 300.0,
    ) -> ApprovalTicket:
        risk = classify(operation)
        if risk is Risk.DENY:
            raise AuthDenied(f"operation denied by policy: {operation}")
        if risk is Risk.ROUTINE:
            # Caller asked for a ticket on something routine. We still
            # issue, but it is recorded in the audit trail because it is a
            # signal of misapplied policy.
            self._record("issue_routine", ident, operation, "warn")
        ticket = ApprovalTicket(
            ticket_id=secrets.token_hex(16),
            operation=operation,
            digest=payload_digest(operation, payload),
            chat_id=ident.chat_id, user_id=ident.user_id,
            risk=risk, summary=summary, ttl_seconds=ttl_seconds,
        )
        with self._lock:
            self._tickets[ticket.ticket_id] = ticket
        self._record("issue", ident, operation, "ok", ticket.ticket_id)
        return ticket

    def bind_message(self, ticket_id: str, message_id: int) -> None:
        """Bind the ticket to the message actually sent (for diagnostics)."""
        with self._lock:
            t = self._tickets.get(ticket_id)
            if t is not None:
                t.message_id = message_id

    # -- resolution (the callback path) ------------------------------------

    def resolve(
        self,
        ticket_id: str,
        approved: bool,
        *,
        ident: Identity | None,
        operation: str | None = None,
        payload: Any = None,
    ) -> tuple[bool, str]:
        """Resolve a callback. -> (authorized?, reason).

        Returns authorized=False when the ticket is unknown, already
        resolved, expired, from another user, from another chat, or bound
        to another operation/payload (digest mismatch).
        """
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                self._record("resolve_unknown", ident, operation or "?", "deny")
                return False, "unknown or already discarded approval"
            if ident is None:
                self._record("resolve_no_identity", None, ticket.operation, "deny")
                return False, "callback without identity"
            if ident.user_id != ticket.user_id:
                self._record("resolve_wrong_user", ident, ticket.operation, "deny",
                             ticket_id)
                return False, "approval belongs to another user"
            if ident.chat_id != ticket.chat_id:
                self._record("resolve_wrong_chat", ident, ticket.operation, "deny",
                             ticket_id)
                return False, "approval belongs to another chat"
            if ticket.state is not ApprovalState.PENDING:
                self._record("resolve_replay", ident, ticket.operation, "deny",
                             ticket_id)
                return False, f"approval was already {ticket.state.value}"
            if ticket.is_expired(self._clock()):
                ticket.state = ApprovalState.EXPIRED
                self._record("resolve_expired", ident, ticket.operation, "deny",
                             ticket_id)
                return False, "approval expired - request it again"
            if operation is not None and operation != ticket.operation:
                self._record("resolve_wrong_op", ident, ticket.operation, "deny",
                             ticket_id)
                return False, "approval is for a different operation"
            if payload is not None and payload_digest(operation or ticket.operation,
                                                      payload) != ticket.digest:
                self._record("resolve_wrong_payload", ident, ticket.operation, "deny",
                             ticket_id)
                return False, "approval is for different content"
            # compare-and-set: only the first resolve changes state
            ticket.state = ApprovalState.APPROVED if approved else ApprovalState.DENIED
            verdict = ticket.state.value
        self._record("resolve", ident, ticket.operation, verdict, ticket_id)
        return approved, ("approved" if approved else "denied")

    def consume(self, ticket_id: str, *, ident: Identity | None = None,
                operation: str | None = None, payload: Any = None) -> bool:
        """Spend an authorized ticket — single use.

        Separate from `resolve` on purpose: "the user tapped Yes" and "this
        execution was actually authorized to run" are different events.
        Without the split, an approved callback could be replayed later.
        """
        with self._lock:
            ticket = self._tickets.get(ticket_id)
            if ticket is None:
                return False
            if ticket.state is not ApprovalState.APPROVED:
                return False
            if ticket.is_expired(self._clock()):
                ticket.state = ApprovalState.EXPIRED
                return False
            if ident is not None and ident.user_id != ticket.user_id:
                return False
            if operation is not None and operation != ticket.operation:
                return False
            if payload is not None and payload_digest(ticket.operation,
                                                      payload) != ticket.digest:
                return False
            ticket.state = ApprovalState.CONSUMED
            return True

    # -- inspection --------------------------------------------------------

    def get(self, ticket_id: str) -> ApprovalTicket | None:
        with self._lock:
            return self._tickets.get(ticket_id)

    def pending(self) -> list[ApprovalTicket]:
        now = self._clock()
        with self._lock:
            live = [t for t in self._tickets.values()
                    if t.state is ApprovalState.PENDING]
        return [t for t in live if not t.is_expired(now)]

    def prune(self, *, max_age_seconds: float = 3600.0) -> int:
        """Drop old/terminal tickets. Returns how many were removed."""
        cutoff = self._clock() - max_age_seconds
        with self._lock:
            stale = [
                tid for tid, t in self._tickets.items()
                if t.state is not ApprovalState.PENDING
                and t.created_at < cutoff
            ]
            for tid in stale:
                self._tickets.pop(tid, None)
        return len(stale)

    def _record(self, action: str, ident: Identity | None, operation: str,
                outcome: str, ticket_id: str | None = None) -> None:
        self.audit.append({
            "ts": self._clock(), "action": action, "operation": operation,
            "outcome": outcome, "ticket": ticket_id,
            "user": ident.user_id if ident else None,
            "chat": ident.chat_id if ident else None,
        })
        # The audit trail must not grow unbounded in a daemon.
        if len(self.audit) > 2000:
            del self.audit[:1000]


# ── High level policy ──────────────────────────────────────────────────────

@dataclass
class Decision:
    """Policy answer for one (identity, operation) pair.

    `allowed` answers "is this identity permitted to attempt this class of
    operation at all". It does NOT mean the operation may run: for an
    APPROVAL risk the operation still needs a valid, unspent ticket. Read
    `needs_approval` before executing, and prefer `authorize_once`, which
    handles both.
    """

    allowed: bool
    risk: Risk
    reason: str = ""
    ticket: ApprovalTicket | None = None

    @property
    def needs_approval(self) -> bool:
        return self.allowed and self.risk is Risk.APPROVAL


class PolicyEngine:
    """Answers "does this operation need a ticket?" for an identity.

    `check` is pure (sends nothing, executes nothing) — the caller sends or
    executes, and only after `allowed=True` plus a valid ticket.
    """

    def __init__(
        self,
        gate: IdentityGate,
        approvals: ApprovalRegistry,
        *,
        persist_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        self.gate = gate
        self.approvals = approvals
        self._persist_dir = persist_dir

    def check(self, ident: Identity | None, operation: str,
              payload: Any = None) -> Decision:
        """Policy query — authorizes NOTHING by itself.

        `allowed=True` + `needs_approval=True` means: this identity may
        attempt the operation, but only with a valid ticket. It never looks
        for a spent ticket: "the user tapped Yes" and "this execution was
        already authorized" are different events, and a consumed ticket must
        not re-authorize (that would be exactly the replay section 2
        forbids).

        Correct path: `check` -> caller issues a ticket -> the callback
        resolves it -> `authorize_once` spends it ONCE, bound to this
        operation and this payload.
        """
        try:
            self.gate.authorize(ident, operation)
        except AuthDenied as exc:
            return Decision(False, Risk.DENY, str(exc))
        risk = classify(operation)
        if risk is Risk.ROUTINE:
            return Decision(True, risk, "routine - proceeds automatically")
        if risk is Risk.DENY:  # pragma: no cover - authorize already filtered
            return Decision(False, risk, "operation denied")
        return Decision(True, risk, "owner approval required")

    def find_approved(self, ident: Identity | None, operation: str,
                      payload: Any = None) -> ApprovalTicket | None:
        """An APPROVED-but-unspent ticket for this exact (identity, op, payload).

        This is what turns "the owner pressed Yes" into "the operation may
        now run": the caller asks for a ticket, and when the callback has
        resolved it, the next call finds it here and spends it via
        `authorize_once`. Without this, approval could never be redeemed
        and the user would be prompted forever.
        """
        digest = payload_digest(operation, payload)
        with self.approvals._lock:  # noqa: SLF001 - same module, read-only scan
            candidates = list(self.approvals._tickets.values())  # noqa: SLF001
        for t in sorted(candidates, key=lambda x: -x.created_at):
            if (t.state is ApprovalState.APPROVED
                    and t.operation == operation
                    and t.digest == digest
                    and (ident is None or t.user_id == ident.user_id)):
                return t
        return None

    def authorize_once(self, ticket_id: str | None, ident: Identity | None,
                       operation: str, payload: Any = None) -> tuple[bool, str]:
        """The sanctioned execution path: identity + valid ticket -> once.

        Returns (may_execute, reason). Spending the ticket HERE is what
        prevents the same button being presented again later.
        """
        decision = self.check(ident, operation, payload)
        if not decision.allowed:
            return False, decision.reason
        if decision.risk is Risk.ROUTINE:
            return True, "routine"
        if not ticket_id:
            # No ticket supplied: fall back to any approved-and-unspent one
            # for this exact operation and payload.
            found = self.find_approved(ident, operation, payload)
            if found is None:
                return False, "owner approval required (no ticket)"
            ticket_id = found.ticket_id
        if not self.approvals.consume(ticket_id, ident=ident,
                                      operation=operation, payload=payload):
            return False, "approval missing, expired, or already spent"
        return True, "approved"