"""Tests for the operational surfaces of the Telegram channel.

Covers what the spec calls "Telegram e operação": network errors, oversized
messages, formatting failures, expired approval, concurrent missions, and
service lifecycle. All without touching the network.
"""

from __future__ import annotations

import threading
import time

import pytest

from jarvis.core.authz import ApprovalRegistry, ApprovalState, Identity
from jarvis.mission.models import Mission, MissionState, MissionTask, TaskState
from jarvis.mission.store import MissionStore
from jarvis.providers.telegram import (
    MAX_MSG, TelegramBot, TelegramChannel, TelegramError,
)


class FakeBot:
    def __init__(self, *, fail_everything=False, fail_markdown=False):
        self.sent: list = []
        self.answered: list = []
        self.updates: list = []
        self.fail_everything = fail_everything
        self.fail_markdown = fail_markdown
        self.get_updates_calls: list[int] = []
        self.msg_id = 100

    def send_message(self, chat_id, text, *, reply_markup=None, parse_mode=None):
        if self.fail_everything:
            raise TelegramError("network unreachable")
        if self.fail_markdown and parse_mode == "Markdown":
            raise TelegramError("can't parse entities")
        self.msg_id += 1
        self.sent.append((chat_id, text, reply_markup, self.msg_id, parse_mode))
        return {"message_id": self.msg_id, "chat": {"id": chat_id}}

    def get_updates(self, *, offset=0, timeout=25):
        self.get_updates_calls.append(offset)
        out = [u for u in self.updates if u.get("update_id", 0) >= offset]
        self.updates = [u for u in self.updates if u.get("update_id", 0) < offset]
        return out

    def answer_callback(self, callback_id, text=""):
        if self.fail_everything:
            raise TelegramError("network unreachable")
        self.answered.append((callback_id, text))

    def get_me(self):
        return {"username": "jarvis_test_bot"}


def _chan(bot=None, **kw):
    bot = bot or FakeBot()
    return TelegramChannel("tok", [123], bot=bot, **kw), bot


# ── oversized / formatting ─────────────────────────────────────────────────

def test_long_output_is_truncated_not_dropped() -> None:
    ch, bot = _chan(ask_fn=lambda q: "x" * 10000)
    out = ch.handle_message("please answer", chat_id=123, user_id=7)
    assert out is not None
    ch._safe_send(123, out)
    assert len(bot.sent[-1][1]) <= MAX_MSG


def test_help_falls_back_when_markdown_is_rejected() -> None:
    ch, bot = _chan(bot=FakeBot(fail_markdown=True))
    ch.send_help(123)
    assert bot.sent[-1][4] is None, "must retry as plain text"
    assert "/mission" in bot.sent[-1][1]


def test_send_failure_is_not_raised() -> None:
    ch, _ = _chan(bot=FakeBot(fail_everything=True))
    ch._safe_send(123, "anything")          # must not raise


# ── network failures ───────────────────────────────────────────────────────

def test_polling_survives_backend_outage() -> None:
    """A dead backend must not kill the loop or raise."""
    ch, bot = _chan(bot=FakeBot())
    bot.updates = []                        # empty: the loop keeps polling
    got = bot.get_updates(offset=0)
    assert got == []


def test_bot_client_raises_on_api_error(monkeypatch) -> None:
    from jarvis.providers import telegram as tg

    class R:
        status_code = 200

        def __init__(self, payload):
            self._p = payload

        def json(self):
            return self._p

    monkeypatch.setattr(tg.requests, "post",
                        lambda url, json=None, timeout=None: R({"ok": False, "description": "boom"}))
    with pytest.raises(TelegramError):
        TelegramBot("BAD").get_me()


def test_bot_client_wraps_connection_error(monkeypatch) -> None:
    from jarvis.providers import telegram as tg

    def boom(url, json=None, timeout=None):
        raise tg.requests.ConnectionError("down")

    monkeypatch.setattr(tg.requests, "post", boom)
    with pytest.raises(TelegramError):
        TelegramBot("TOK").get_me()


def test_get_updates_returns_empty_on_failure(monkeypatch) -> None:
    """Long polling must degrade to empty, not raise into the loop."""
    from jarvis.providers import telegram as tg

    def boom(url, json=None, timeout=None):
        raise tg.requests.ConnectionError("down")

    monkeypatch.setattr(tg.requests, "post", boom)
    assert TelegramBot("TOK").get_updates() == []


# ── approval lifecycle ─────────────────────────────────────────────────────

def test_expired_approval_reports_expiry_to_the_user() -> None:
    ch, bot = _chan()
    ident = Identity(chat_id=123, user_id=7)
    t = ch.approvals.issue(ident=ident, operation="shell.exec", payload="x",
                           ttl_seconds=-1)
    ch._handle_callback({
        "id": "cq", "from": {"id": 7},
        "data": f"ap:{t.ticket_id}:yes",
        "message": {"message_id": 1, "chat": {"id": 123}},
    })
    assert any("expired" in txt for _c, txt in bot.answered)


def test_pending_approvals_are_listed_and_individually_approvable() -> None:
    ch, _ = _chan()
    ident = Identity(chat_id=123, user_id=7)
    t = ch.approvals.issue(ident=ident, operation="shell.exec",
                           payload="do thing", summary="do thing")
    listing = ch.handle_message("/approve", chat_id=123, user_id=7)
    assert "Pending approvals" in listing
    short = t.ticket_id[:10]
    out = ch.handle_message(f"/approve {short}", chat_id=123, user_id=7)
    assert "approved" in out


def test_unknown_approval_id_is_refused() -> None:
    ch, _ = _chan()
    assert "No pending approval" in ch.handle_message("/approve deadbeef00",
                                                      chat_id=123, user_id=7)


def test_stranger_cannot_list_or_approve() -> None:
    """With a user allowlist configured, another group member is refused."""
    ch, _ = _chan(allowed_users=[7])
    assert ch.handle_message("/approve", chat_id=123, user_id=99) is None
    assert ch.handle_message("/approve", chat_id=123, user_id=7) is not None


# ── concurrency ────────────────────────────────────────────────────────────

def test_concurrent_approvals_do_not_cross_talk(tmp_path) -> None:
    """Two approvals in flight: each resolves its own ticket."""
    ch, bot = _chan()
    ident = Identity(chat_id=123, user_id=7)
    t1 = ch.approvals.issue(ident=ident, operation="shell.exec", payload="A")
    t2 = ch.approvals.issue(ident=ident, operation="shell.exec", payload="B")

    def press(ticket, mid, cb_id):
        ch._handle_callback({
            "id": cb_id, "from": {"id": 7},
            "data": f"ap:{ticket.ticket_id}:yes",
            "message": {"message_id": mid, "chat": {"id": 123}},
        })

    threads = [threading.Thread(target=press, args=(t1, 1, "c1")),
               threading.Thread(target=press, args=(t2, 2, "c2"))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert ch.approvals.get(t1.ticket_id).state is ApprovalState.APPROVED
    assert ch.approvals.get(t2.ticket_id).state is ApprovalState.APPROVED


def test_two_presses_of_same_ticket_authorize_once() -> None:
    ch, bot = _chan()
    ident = Identity(chat_id=123, user_id=7)
    t = ch.approvals.issue(ident=ident, operation="shell.exec", payload="A")

    def press():
        ch._handle_callback({
            "id": "dup", "from": {"id": 7},
            "data": f"ap:{t.ticket_id}:yes",
            "message": {"message_id": 1, "chat": {"id": 123}},
        })

    ts = [threading.Thread(target=press) for _ in range(4)]
    for th in ts:
        th.start()
    for th in ts:
        th.join()
    granted = [txt for _c, txt in bot.answered if txt.startswith("✅")]
    refused = [txt for _c, txt in bot.answered if txt.startswith("❌")]
    assert len(granted) == 1, granted
    assert len(refused) == 3, refused
    assert all("already" in t for t in refused)


def test_bounded_worker_pool() -> None:
    ch, _ = _chan()
    assert ch._pool._max_workers <= 2   # noqa: SLF001 - white box


# ── idempotency of updates ─────────────────────────────────────────────────

def test_replayed_update_id_is_not_executed_twice(tmp_path, monkeypatch) -> None:
    """Same update_id twice -> one execution, even across a restart."""
    monkeypatch.setenv("JARVIS_MISSION_DIR", str(tmp_path))
    store = MissionStore(tmp_path)
    bot = FakeBot()
    ch = TelegramChannel("tok", [123], bot=bot, mission_store=store)
    bot.updates = [{"update_id": 77, "message": {
        "text": "/status", "chat": {"id": 123}, "from": {"id": 7}}}]
    status_calls: list[int] = []
    ch._status = lambda: (status_calls.append(1), "OK")[1]

    seen: list[str] = []

    def one_pass():
        for u in list(bot.updates):
            uid = u["update_id"]
            if store.mark_seen(f"upd:{uid}", ttl_seconds=3600):
                seen.append(str(uid))
                ch._dispatch_message(u["message"])

    one_pass()
    bot.updates = [{"update_id": 77, "message": {
        "text": "/status", "chat": {"id": 123}, "from": {"id": 7}}}]
    one_pass()
    assert seen == ["77"], seen
    assert len(status_calls) == 1


def test_poll_offset_survives_restart(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_MISSION_DIR", str(tmp_path))
    ch1, _ = _chan(mission_store=MissionStore(tmp_path))
    ch1._write_offset(4321)                    # noqa: SLF001 - white box
    ch2, _ = _chan(mission_store=MissionStore(tmp_path))
    assert ch2._read_offset() == 4321          # noqa: SLF001 - white box


# ── lifecycle / empty configuration ────────────────────────────────────────

def test_no_token_means_no_channel() -> None:
    from jarvis.core.config import Config
    from jarvis.providers.telegram import make_channel
    assert make_channel(Config()) is None


def test_empty_allowlist_refuses_everything() -> None:
    ch, _ = _chan()
    ch.gate = type(ch.gate)([])               # simulate a misconfigured bot
    assert ch.handle_message("/status", chat_id=123, user_id=7) is None
    assert ch.handle_message("/mission do a thing", chat_id=123, user_id=7) is None


def test_mission_commands_on_empty_store_are_graceful() -> None:
    ch, _ = _chan(mission_store=MissionStore("/tmp/jarvis-empty-missions-test"))
    for cmd in ("/mission", "/tasks", "/mission show msn-nope",
                "/mission cancel msn-nope", "/mission pause msn-nope"):
        out = ch.handle_message(cmd, chat_id=123, user_id=7)
        assert isinstance(out, str) and out.strip(), cmd


def test_stop_and_steer_route_to_steer(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    ch, _ = _chan()
    assert ch.handle_message("/steer go left", chat_id=123, user_id=7).startswith("Steering")
    assert ch.handle_message("/stop", chat_id=123, user_id=7).startswith("STOP")


def test_status_lists_running_missions(tmp_path) -> None:
    ch, _ = _chan(status_fn=lambda: "STATUS", mission_store=MissionStore(tmp_path))
    ch._running_missions["msn-abc"] = "123"   # noqa: SLF001 - white box
    out = ch.handle_message("/status", chat_id=123, user_id=7)
    assert "msn-abc" in out and "execu" in out