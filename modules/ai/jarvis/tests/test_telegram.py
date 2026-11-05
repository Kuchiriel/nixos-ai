"""Testes do canal Telegram (Fase 9) — cliente Bot API + aprovação inline."""

from __future__ import annotations

import threading
import time

import pytest
import requests

from jarvis.providers.telegram import (
    TelegramBot,
    TelegramChannel,
    TelegramError,
    _parse_chats,
    format_doctor_human,
    make_channel,
)
from jarvis.core.authz import Identity, encode_callback
from jarvis.core.config import Config


class FakeBot:
    """Bot fake: respostas configuráveis + captura do que foi enviado."""

    def __init__(self):
        self.sent = []          # (chat_id, text, reply_markup)
        self.answered = []      # callback ids
        self.updates = []       # fila de updates
        self.msg_id = 100

    def send_message(self, chat_id, text, *, reply_markup=None, parse_mode=None):
        self.msg_id += 1
        self.sent.append((chat_id, text, reply_markup, self.msg_id, parse_mode))
        return {"message_id": self.msg_id, "chat": {"id": chat_id}}

    def get_updates(self, *, offset=0, timeout=25):
        out = [u for u in self.updates if u.get("update_id", 0) >= offset]
        self.updates = [u for u in self.updates if u.get("update_id", 0) < offset]
        return out

    def answer_callback(self, callback_id, text=""):
        self.answered.append((callback_id, text))

    def get_me(self):
        return {"username": "jarvis_test_bot"}


def _channel(bot=None, **kw):
    bot = bot or FakeBot()
    ch = TelegramChannel("tok", [123], bot=bot, **kw)
    return ch, bot


# --- roteamento ---

def test_ignores_unauthorized_chat() -> None:
    ch, _ = _channel()
    assert ch.handle_message("/status", chat_id=999) is None


def test_help_and_unknown() -> None:
    ch, _ = _channel()
    out = ch.handle_message("/start", chat_id=123)
    assert "/mission" in out and "/ask" in out
    out2 = ch.handle_message("/xyz", chat_id=123)
    assert "unknown command" in out2


def test_send_help_uses_markdown_then_falls_back() -> None:
    ch, bot = _channel()
    ch.send_help(123)
    # primeira tentativa com markdown; fake não falha → parse_mode=Markdown
    assert bot.sent[0][4] == "Markdown"

    class FailingMarkdownBot(FakeBot):
        def send_message(self, chat_id, text, *, reply_markup=None, parse_mode=None):
            if parse_mode == "Markdown":
                raise TelegramError("can't parse entities")
            return super().send_message(
                chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode,
            )

    ch2, bot2 = _channel(bot=FailingMarkdownBot())
    ch2.send_help(123)
    assert bot2.sent[-1][4] is None  # fallback para texto puro


def test_routes_ask_status_remember_vault() -> None:
    ch, _ = _channel(
        ask_fn=lambda q: f"ASK:{q}",
        status_fn=lambda: "STATUS",
        remember_fn=lambda t: f"REM:{t}",
        vault_fn=lambda a: f"VAULT:{a}",
    )
    assert ch.handle_message("/ask quanto é 2+2", chat_id=123) == "ASK:quanto é 2+2"
    assert ch.handle_message("/status", chat_id=123) == "STATUS"
    assert ch.handle_message("/remember prefiro café", chat_id=123) == "REM:prefiro café"
    assert ch.handle_message("/vault list", chat_id=123) == "VAULT:list"
    # sem comando → pergunta livre
    assert ch.handle_message("qual a capital?", chat_id=123) == "ASK:qual a capital?"


# --- aprovação com botões ---

def _press(ch, bot, *, approved=True, user_id=7, chat_id=123, timeout=5.0):
    """Wait for the approval message, then press its button.

    Polls instead of sleeping a fixed amount: the old version raced with
    the approver's send and the callback fired against an empty outbox,
    which made the test wait the full 120s approval timeout.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        with_markup = [s for s in bot.sent if s[2] is not None]
        if with_markup:
            _chat, _txt, markup, msg_id, _pm = with_markup[-1]
            row = 0 if approved else 1
            cb = markup["inline_keyboard"][0][row]["callback_data"]
            ch._handle_callback({
                "id": f"cq-{msg_id}",
                "from": {"id": user_id, "username": "owner"},
                "data": cb,
                "message": {"message_id": msg_id, "chat": {"id": chat_id}},
            })
            return True
        time.sleep(0.01)
    raise AssertionError("no approval message was sent")


def test_approver_yes_roundtrip(monkeypatch) -> None:
    ch, bot = _channel()
    ch._approval_timeout = 5.0
    approver = ch.make_approver(123, user_id=7)

    # The user taps [Sim] while the approver waits. The button carries the
    # ticket id (callback_data = ap:<ticket>:yes) and the presser identity
    # must match the ticket owner.
    threading.Timer(0.05, lambda: _press(ch, bot, approved=True)).start()
    assert approver("sudo rm -rf /") is True
    assert bot.sent[0][2]["inline_keyboard"][0][0]["text"] == "✅ Sim"
    assert any(t[0].startswith("cq-") and "approved" in t[1] for t in bot.answered)


def test_approver_no(monkeypatch) -> None:
    ch, bot = _channel()
    ch._approval_timeout = 5.0
    approver = ch.make_approver(123, user_id=7)

    threading.Timer(0.05, lambda: _press(ch, bot, approved=False)).start()
    assert approver("sudo reboot") is False
    assert any(t[0].startswith("cq-") and "denied" in t[1] for t in bot.answered)


def test_approver_rejects_foreign_user() -> None:
    """A callback pressed by someone else must NOT authorize."""
    ch, bot = _channel()
    ch._approval_timeout = 0.6
    approver = ch.make_approver(123, user_id=7)

    threading.Timer(0.05,
                    lambda: _press(ch, bot, approved=True, user_id=999)).start()
    # the foreign press must not release the approval
    assert approver("sudo rm -rf /") is False


def test_approver_rejects_replayed_callback() -> None:
    """The same callback twice must not authorize twice."""
    ch, bot = _channel()
    ch._approval_timeout = 5.0
    ident = Identity(chat_id=123, user_id=7)
    ticket = ch.approvals.issue(ident=ident, operation="shell.exec",
                                payload="danger", summary="danger")
    cb = encode_callback(ticket.ticket_id, True)
    msg = bot.send_message(123, "danger?", parse_mode=None)
    ch.approvals.bind_message(ticket.ticket_id, msg["message_id"])

    cq = {"id": "cqR", "from": {"id": 7}, "data": cb,
          "message": {"message_id": msg["message_id"], "chat": {"id": 123}}}
    ch._handle_callback(dict(cq))
    assert ch.policy.authorize_once(ticket.ticket_id, ident, "shell.exec",
                                    "danger")[0] is True
    # replay: the ticket is consumed, so a second run is refused
    assert ch.policy.authorize_once(ticket.ticket_id, ident, "shell.exec",
                                    "danger")[0] is False


def test_approver_timeout() -> None:
    ch, _ = _channel()
    approver = ch.make_approver(123, user_id=7)  # nobody answers
    ch._approval_timeout = 0.1
    assert approver("sudo algo") is False


# --- cliente Bot API (mocks de requests) ---

class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_bot_send_message(monkeypatch) -> None:
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResp({"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr("jarvis.providers.telegram.requests.post", fake_post)
    out = TelegramBot("TOK").send_message(1, "oi")
    assert out["message_id"] == 1
    assert captured["url"] == "https://api.telegram.org/botTOK/sendMessage"
    assert captured["json"]["chat_id"] == 1


def test_bot_raises_on_api_error(monkeypatch) -> None:
    def fake_post(url, json=None, timeout=None):
        return _FakeResp({"ok": False, "description": "token inválido"})

    monkeypatch.setattr("jarvis.providers.telegram.requests.post", fake_post)
    with pytest.raises(TelegramError):
        TelegramBot("BAD").get_me()


def test_format_doctor_human_readable() -> None:
    report = {
        "overall": "degraded",
        "checks": [
            {"name": "llama_cpp", "status": "ok", "detail": "ok"},
            {"name": "qdrant", "status": "degraded", "detail": "HTTP 500"},
            {"name": "disk", "status": "ok", "detail": "12.3 GB livres"},
            {"name": "nixos", "status": "ok", "detail": "/nix/var/nix/profiles/system"},
        ],
    }
    out = format_doctor_human(report)
    assert "✅" in out and "⚠️" in out
    assert "Chat model" in out        # friendly name, not snake_case
    assert "Vector DB" in out
    assert "/nix/store/" not in out       # path do store encurtado
    assert "Something degraded" in out
    # JSON puro não deve vazar
    assert "{" not in out and "checks" not in out


def test_parse_chats_and_make_channel() -> None:
    assert _parse_chats("123, 456, ") == [123, 456]
    assert make_channel(Config()) is None  # sem token/chat → None
    cfg = Config(telegram_token="tok", telegram_chat_id="123")
    ch = make_channel(cfg)
    assert ch is not None and ch._allowed == {123}


# --- /sshkey (só via dono = chat autorizado) ---

_ED = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqU5X5r8X3v9y2Z1Q7W4E6R8T0Y2U4I6O8P0A2S4D6F8H0J2K4L6N8P0 termux"


def test_sshkey_unauthorized_chat_ignored() -> None:
    ch, _ = _channel()
    assert ch.handle_message("/sshkey " + _ED, chat_id=999) is None


def test_sshkey_invalid_rejected(tmp_path, monkeypatch) -> None:
    ch, _ = _channel()
    monkeypatch.setenv("HOME", str(tmp_path))
    out = ch.handle_message("/sshkey chave-invalida", chat_id=123, user_id=7)
    assert "Invalid key" in out
    assert not (tmp_path / ".ssh" / "authorized_keys").exists()


def test_sshkey_requires_approval_then_installs(tmp_path, monkeypatch) -> None:
    """Installing a key is high impact: no approval, no side effect."""
    ch, bot = _channel()
    monkeypatch.setenv("HOME", str(tmp_path))
    out = ch.handle_message("/sshkey " + _ED, chat_id=123, user_id=7)
    assert "Approval requested" in out
    auth = tmp_path / ".ssh" / "authorized_keys"
    assert not auth.exists(), "must not install before approval"

    # owner presses Yes
    _press(ch, bot, approved=True)

    # Next attempt redeems the approval and installs.
    out2 = ch.handle_message("/sshkey " + _ED, chat_id=123, user_id=7)
    assert "Key installed" in out2
    assert auth.read_text().strip() == _ED
    # dedupe
    out3 = ch.handle_message("/sshkey " + _ED, chat_id=123, user_id=7)
    assert "already installed" in out3
    assert len(auth.read_text().strip().splitlines()) == 1


def test_sshkey_approval_is_bound_to_one_key(tmp_path, monkeypatch) -> None:
    """An approval for key A must not authorize installing key B."""
    ch, bot = _channel()
    monkeypatch.setenv("HOME", str(tmp_path))
    other = ("ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqU5X5r8X3v9y2Z1Q7W4E6R8T0"
             "Y2U4I6O8P0A2S4D6F8H0J2K4L6N8P1 otherkey")
    ch.handle_message("/sshkey " + _ED, chat_id=123, user_id=7)
    _press(ch, bot, approved=True)
    assert "Key installed" in ch.handle_message("/sshkey " + _ED, chat_id=123,
                                                user_id=7)
    # A DIFFERENT key: the spent approval does not cover it -> must ask again
    out = ch.handle_message("/sshkey " + other, chat_id=123, user_id=7)
    assert "Approval requested" in out
    auth = tmp_path / ".ssh" / "authorized_keys"
    assert other not in auth.read_text()
    assert len(auth.read_text().strip().splitlines()) == 1


# --- /opencode ---

def test_opencode_usage_and_unknown_model_flag() -> None:
    ch, _ = _channel()
    assert "Usage" in ch.handle_message("/opencode", chat_id=123)
    assert "Usage" in ch.handle_message("/opencode -m", chat_id=123)
    assert ch.handle_message("/opencode -m", chat_id=999) is None


# --- fuzzy dispatch ---

def test_fuzzy_prefix_case_and_no_slash() -> None:
    ch, _ = _channel(
        ask_fn=lambda q: f"ASK:{q}",
        status_fn=lambda: "STATUS",
        remember_fn=lambda t: f"REM:{t}",
    )
    assert ch.handle_message("/STAT", chat_id=123) == "STATUS"
    assert ch.handle_message("/STA", chat_id=123).startswith("unknown command")  # ambiguous: status/start
    assert ch.handle_message("status", chat_id=123) == "STATUS"
    assert ch.handle_message("/opencode", chat_id=123).startswith("Usage")
    assert ch.handle_message("OPENCOD", chat_id=123).startswith("Usage")
    assert ch.handle_message("/a", chat_id=123) != "ASK:"  # curto não casa


def test_fuzzy_preserves_arg_case() -> None:
    ch, _ = _channel(remember_fn=lambda t: f"REM:{t}")
    out = ch.handle_message("/REMEMBER Prefiro Café", chat_id=123)
    assert out == "REM:Prefiro Café"


# --- steering ---

def test_steer_stop_routing(tmp_path, monkeypatch) -> None:
    ch, _ = _channel()
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert ch.handle_message("/steer vá pela esquerda", chat_id=123).startswith("Steering")
    assert (tmp_path / "steer.md").exists()
    assert ch.handle_message("/stop", chat_id=123).startswith("STOP")
    assert ch.handle_message("/steer", chat_id=123).startswith("Usage")
    assert ch.handle_message("/stop", chat_id=999) is None
