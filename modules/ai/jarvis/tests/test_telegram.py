"""Testes do canal Telegram (Fase 9) — cliente Bot API + aprovação inline."""

from __future__ import annotations

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
    assert "/agent" in out and "/ask" in out
    out2 = ch.handle_message("/xyz", chat_id=123)
    assert "comando desconhecido" in out2


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

def test_approver_yes_roundtrip(monkeypatch) -> None:
    ch, bot = _channel()
    approver = ch.make_approver(123)

    # simula o usuário tocando [Sim] enquanto o approver espera: o id da
    # mensagem de aprovação é a última enviada pelo bot quando o timer dispara
    def answer_after_delay():
        msg_id = bot.sent[-1][3]
        ch._handle_callback({
            "id": "cq1",
            "data": "yes",
            "message": {"message_id": msg_id},
        })
        ch._handle_callback({
            "id": "cq1",
            "data": "yes",
            "message": {"message_id": msg_id},
        })

    import threading
    threading.Timer(0.05, answer_after_delay).start()
    assert approver("sudo rm -rf /") is True
    assert bot.sent[0][2]["inline_keyboard"][0][0]["text"] == "✅ Sim"
    assert ("cq1", "aprovado ✅") in bot.answered


def test_approver_no(monkeypatch) -> None:
    ch, bot = _channel()
    approver = ch.make_approver(123)

    def answer_no():
        msg_id = bot.sent[-1][3]
        ch._handle_callback({
            "id": "cq2",
            "data": "no",
            "message": {"message_id": msg_id},
        })

    import threading
    threading.Timer(0.05, answer_no).start()
    assert approver("sudo reboot") is False
    assert ("cq2", "negado ❌") in bot.answered


def test_approver_timeout() -> None:
    ch, _ = _channel()
    approver = ch.make_approver(123)  # ninguém responde
    # timeout curto para o teste não demorar
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
    assert "Modelo de chat" in out        # nome amigável, não snake_case
    assert "Vector DB" in out
    assert "/nix/store/" not in out       # path do store encurtado
    assert "Algo degradado" in out
    # JSON puro não deve vazar
    assert "{" not in out and "checks" not in out


def test_parse_chats_and_make_channel() -> None:
    assert _parse_chats("123, 456, ") == [123, 456]
    assert make_channel(Config()) is None  # sem token/chat → None
    cfg = Config(telegram_token="tok", telegram_chat_id="123")
    ch = make_channel(cfg)
    assert ch is not None and ch._allowed == {123}
