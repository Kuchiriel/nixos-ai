"""Canal Telegram do JARVIS (Fase 9) — aprovação assíncrona do self-evolve.

Padrão do pithagoras: o agente expõe um serviço; o canal (Telegram) consome
e o usuário aprova de onde estiver. Aqui o `jarvis telegram` é o serviço:
  - um ÚNICO consumidor de getUpdates (long-polling) — sem webhook, funciona
    atrás de NAT;
  - `/ask`, `/agent`, `/status`, `/remember`, `/vault` roteados para o
    pipeline local;
  - quando o agente precisa aprovar um comando fora da allowlist, envia a
    mensagem com botões [Sim]/[Não] e o callback é roteado para o thread do
    agente (threading.Event) — o loop continua polling enquanto isso.

Segurança: só responde aos chat_ids configurados (allowlist).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from jarvis.core.config import Config, get_config

API_BASE = "https://api.telegram.org/bot{token}"


class TelegramError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Cliente mínimo da Bot API (só o que o canal usa)
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
            raise TelegramError(f"falha de conexão com o Telegram: {exc}") from exc
        data = resp.json()
        if not data.get("ok"):
            raise TelegramError(f"Telegram {method}: {data.get('description', 'erro')}")
        return data.get("result", {})

    def get_me(self) -> dict[str, Any]:
        return self._post("getMe")

    def send_message(
        self, chat_id: int, text: str, *,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str | None = "Markdown",
    ) -> dict[str, Any]:
        """Envia mensagem. `parse_mode` default Markdown, mas o canal usa
        `parse_mode=None` (texto puro) para respostas dinâmicas — saídas do
        doctor/agente contêm `_`/`*`/backticks que QUEBRAM o markdown do
        Telegram (erro 400 "can't parse entities") e seriam engolidas.
        """
        kwargs: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            kwargs["parse_mode"] = parse_mode
        if reply_markup is not None:
            kwargs["reply_markup"] = reply_markup
        return self._post("sendMessage", **kwargs)

    def get_updates(self, *, offset: int = 0, timeout: int = 25) -> list[dict[str, Any]]:
        """Long-polling. `timeout` é o timeout da chamada HTTP (Telegram
        segura a resposta até haver update ou o timeout expirar)."""
        try:
            return self._post("getUpdates", offset=offset, timeout=timeout)
        except TelegramError:
            return []

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self._post("answerCallbackQuery", callback_id=callback_id, text=text)


# ---------------------------------------------------------------------------
# Canal: loop + aprovação + roteamento
# ---------------------------------------------------------------------------

@dataclass
class _PendingApproval:
    event: threading.Event = field(default_factory=threading.Event)
    answer: str = ""  # "yes" | "no"


class TelegramChannel:
    """O serviço do canal. `run()` é o loop; `handle_message` é testável."""

    def __init__(
        self,
        token: str,
        allowed_chats: list[int],
        *,
        bot: TelegramBot | None = None,
        ask_fn: Callable[[str], str] | None = None,
        agent_fn: Callable[[str, Callable[[str], bool]], str] | None = None,
        status_fn: Callable[[], str] | None = None,
        remember_fn: Callable[[str], str] | None = None,
        vault_fn: Callable[[str], str] | None = None,
        approval_timeout: float = 120.0,
        circuit_breaker: Any | None = None,
        force_local_fn: Callable[[], str] | None = None,
        force_remote_fn: Callable[[], str] | None = None,
    ) -> None:
        self._bot = bot or TelegramBot(token)
        self._allowed = set(allowed_chats)
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

    # --- aprovação (usada pelo agente) ---

    def make_approver(self, chat_id: int) -> Callable[[str], bool]:
        """Cria o callable de aprovação para o Agent rodar neste canal."""
        def approver(cmd: str) -> bool:
            try:
                # texto puro: o comando pode conter `_`/`*` que quebrariam o
                # markdown (erro 400 silencioso — aprovação nunca chegaria)
                msg = self._bot.send_message(
                    chat_id,
                    f"🔧 Comando fora da allowlist:\n{cmd}\n\nPermitir?",
                    reply_markup={
                        "inline_keyboard": [[
                            {"text": "✅ Sim", "callback_data": "yes"},
                            {"text": "❌ Não", "callback_data": "no"},
                        ]]
                    },
                    parse_mode=None,
                )
            except TelegramError:
                return False
            pending = _PendingApproval()
            self._pending[msg["message_id"]] = pending
            try:
                ok = pending.event.wait(timeout=self._approval_timeout)
            finally:
                self._pending.pop(msg["message_id"], None)
            if not ok:
                return False
            # o callback real já foi respondido em _handle_callback (com o id
            # válido e o texto "aprovado ✅"/"negado ❌") — aqui só devolve a
            # decisão. (Antes havia um answer_callback("") noop que o Telegram
            # rejeitava com Bad Request: query is too old → erro no agente.)
            return pending.answer == "yes"
        return approver

    # --- roteamento de mensagens (testável, sem IO de rede além dos fns) ---

    def handle_message(self, text: str, *, chat_id: int) -> str | None:
        """Roteia uma mensagem; None = ignorada (chat não autorizado)."""
        if chat_id not in self._allowed:
            return None
        text = (text or "").strip()
        if text in ("/start", "/help"):
            return self._help_text()
        if text == "/status":
            return self._handle_status()
        if text == "/force_local":
            return self._handle_force_local()
        if text == "/force_remote":
            return self._handle_force_remote()
        if text.startswith("/ask "):
            return (self._ask or (lambda q: f"ask indisponível: {q}"))(text[5:].strip())
        if text.startswith("/remember "):
            return (self._remember or (lambda t: f"remember indisponível: {t}"))(text[10:].strip())
        if text.startswith("/vault"):
            return (self._vault or (lambda a: f"vault indisponível: {a}"))(text[6:].strip())
        if text.startswith("/agent "):
            # executado em thread pelo run(); aqui retornamos a tarefa
            return None
        if text.startswith("/"):
            return f"comando desconhecido: {text.split()[0]}\n\n{self._help_text()}"
        # default: pergunta livre
        return (self._ask or (lambda q: f"ask indisponível: {q}"))(text)

    def _handle_status(self) -> str:
        """Status do backend com info do circuit breaker."""
        base_status = (self._status or (lambda: "status indisponível"))()
        if self._circuit_breaker is not None:
            cb_info = self._circuit_breaker.state_info
            circuit = cb_info["circuit_state"]
            backend = cb_info["backend"]["state"]
            latency = cb_info["backend"]["latency_ms"]
            uptime = cb_info["backend"]["uptime_pct"]
            mode = "LOCAL" if circuit == "closed" else "FALLBACK" if circuit == "open" else "TESTING"
            extra = (
                f"\n\n🔗 Circuit Breaker: {circuit.upper()}"
                f"\n📡 Backend: {backend} ({latency}ms)"
                f"\n📊 Uptime: {uptime}%"
                f"\n🔄 Modo: {mode}"
                f"\n📈 Local: {cb_info['total_local']} | Fallback: {cb_info['total_fallback']} | Rejeitados: {cb_info['total_rejected']}"
            )
            return base_status + extra
        return base_status

    def _handle_force_local(self) -> str:
        """Força retorno ao modo local."""
        if self._force_local_fn:
            return self._force_local_fn()
        if self._circuit_breaker is not None:
            return self._circuit_breaker.force_local()
        return "Circuit breaker não configurado."

    def _handle_force_remote(self) -> str:
        """Força uso do fallback remoto."""
        if self._force_remote_fn:
            return self._force_remote_fn()
        if self._circuit_breaker is not None:
            return self._circuit_breaker.force_open()
        return "Circuit breaker não configurado."

    def send_help(self, chat_id: int) -> None:
        """Help com markdown (texto controlado por nós — markdown válido)."""
        try:
            self._bot.send_message(chat_id, self._help_text(), parse_mode="Markdown")
        except TelegramError:
            self._bot.send_message(chat_id, self._help_text(), parse_mode=None)

    @staticmethod
    def _help_text() -> str:
        return (
            "🤖 *JARVIS — canal Telegram*\n\n"
            "*Comandos*\n"
            "`/ask <pergunta>` — cascata (fastpath/doctor/nixos/rag/agent)\n"
            "`/agent <tarefa>` — agente com aprovação por botões\n"
            "`/status` — saúde dos serviços + circuit breaker\n"
            "`/force_local` — força modo local (desliga fallback)\n"
            "`/force_remote` — força fallback remoto\n"
            "`/remember <fato>` — grava na memória episódica\n"
            "`/vault summarize|list` — memória de longo prazo\n\n"
            "*Comandos diretos (respondem em ms, sem LLM)*\n"
            "`espaço em disco` · `quanto de memória tem?` · `uptime` · `qual kernel?`\n"
            "`processos ativos` · `quais livros tenho` · `leia o livro <nome>`\n\n"
            "*Exemplos*\n"
            "`/ask como está a saúde do sistema?`\n"
            "`/agent liste os serviços ativos`\n"
            "`/remember prefiro respostas curtas`\n"
            "ou mande uma pergunta direta — eu escolho o caminho mais barato."
        )

    # --- loop ---

    def run(self, *, poll_timeout: int = 25) -> None:
        """Loop de long-polling — ÚNICO consumidor de getUpdates."""
        offset = 0
        while True:
            for update in self._bot.get_updates(offset=offset, timeout=poll_timeout):
                offset = max(offset, update.get("update_id", 0) + 1)
                if "callback_query" in update:
                    self._handle_callback(update["callback_query"])
                elif "message" in update:
                    msg = update["message"]
                    chat_id = msg.get("chat", {}).get("id", 0)
                    text = msg.get("text", "")
                    if text.startswith("/agent "):
                        # agente é longo: roda em thread, loop continua pollando
                        threading.Thread(
                            target=self._run_agent_task,
                            args=(chat_id, text[7:].strip()),
                            daemon=True,
                        ).start()
                    elif text.strip() in ("/start", "/help"):
                        # help é markdown controlado por nós (válido)
                        self.send_help(chat_id)
                    else:
                        try:
                            reply = self.handle_message(text, chat_id=chat_id)
                        except Exception as exc:  # noqa: BLE001
                            reply = f"erro: {exc}"
                        if reply:
                            self._safe_send(chat_id, reply)

    def _run_agent_task(self, chat_id: int, task: str) -> None:
        try:
            if self._agent is None:
                self._safe_send(chat_id, "agente indisponível")
                return
            reply = self._agent(task, self.make_approver(chat_id))
        except Exception as exc:  # noqa: BLE001
            reply = f"erro no agente: {exc}"
        self._safe_send(chat_id, reply)

    def _handle_callback(self, cq: dict[str, Any]) -> None:
        msg_id = cq.get("message", {}).get("message_id")
        pending = self._pending.get(msg_id) if msg_id else None
        if pending is None:
            return
        pending.answer = cq.get("data", "")
        try:
            self._bot.answer_callback(
                cq.get("id", ""),
                "aprovado ✅" if pending.answer == "yes" else "negado ❌",
            )
        except TelegramError:
            pass
        pending.event.set()

    def _safe_send(self, chat_id: int, text: str) -> None:
        try:
            # Texto puro (sem parse_mode): respostas dinâmicas têm `_`/`*`/` `
            # que quebrariam o markdown do Telegram e seriam engolidas em
            # silêncio — o usuário nunca veria a resposta.
            self._bot.send_message(chat_id, text[:4000], parse_mode=None)
        except TelegramError:
            pass


# ---------------------------------------------------------------------------
# Wires com o pipeline local (usados pelo CLI)
# ---------------------------------------------------------------------------

def format_doctor_human(report: dict[str, Any]) -> str:
    """Converte o relatório JSON do doctor em texto legível para humanos.

    O Telegram manda texto puro (sem markdown) — emojis e nomes amigáveis
    dão o "feeling" de ia de bordo sem poluir com JSON.
    """
    names = {
        "llama_cpp": "🧠 Modelo de chat (llama.cpp)",
        "llama_cpp_embeddings": "🔎 Embeddings (RAG)",
        "qdrant": "🗄️ Vector DB (Qdrant)",
        "disk": "💾 Disco",
        "nixos": "❄️ NixOS",
    }
    icons = {"ok": "✅", "degraded": "⚠️", "down": "❌"}
    lines = ["🩺 *JARVIS — saúde do sistema*"]
    for c in report.get("checks", []):
        name = names.get(c.get("name", ""), c.get("name", "?"))
        icon = icons.get(c.get("status", "down"), "❓")
        detail = c.get("detail", "") or ""
        # encurta paths longos do store
        if "/nix/store/" in detail:
            detail = "profile do sistema ativo"
        lines.append(f"{icon} {name}: {detail}")
    overall = report.get("overall", "down")
    lines.append("")
    if overall == "ok":
        lines.append("✅ Tudo funcionando.")
    elif overall == "degraded":
        lines.append("⚠️ Algo degradado — veja acima.")
    else:
        lines.append("❌ Serviços fora — me chame com `/ask como consertar`.")
    return "\n".join(lines)


def send_notification(text: str, config: Config | None = None) -> bool:
    """Envia uma notificação one-way para o chat do usuário (se configurado).

    Usada pelos daemons (idle, vault, heal) para avisar conclusões no celular
    sem exigir interação. Silencioso se não houver token (lab sem Telegram,
    CI, etc.).
    """
    cfg = config or get_config()
    if not cfg.telegram_token or not cfg.telegram_chat_id:
        return False
    try:
        bot = TelegramBot(cfg.telegram_token)
        for chat_id in _parse_chats(cfg.telegram_chat_id):
            bot.send_message(chat_id, text[:4000], parse_mode=None)
        return True
    except TelegramError:
        return False


def _parse_chats(raw: str) -> list[int]:
    return [int(c.strip()) for c in raw.split(",") if c.strip().isdigit()]


def make_channel(config: Config | None = None) -> TelegramChannel | None:
    """Monta o canal com os handlers reais; None se faltar token/chat."""
    cfg = config or get_config()
    if not cfg.telegram_token or not cfg.telegram_chat_id:
        return None
    from jarvis.core.router import (
        handle_agent, handle_doctor, handle_fastpath, handle_nixos, handle_rag, route_request,
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
                # agente via chat: sem --approve → comandos de efeito são negados
                out = handle_agent(route.query, cfg, approve=False)
        except Exception as exc:  # noqa: BLE001
            return f"erro: {exc}"
        return str(out.get("answer") or out.get("output") or out)[:4000]

    def agent(task: str, approver: Callable[[str], bool]) -> str:
        # handle_agent retorna dict (não o objeto AgentResult)
        result = handle_agent(task, cfg, approve=True, approver=approver)
        run = result.get("commands_run", [])
        denied = result.get("commands_denied", [])
        text = result.get("response", "") or ""
        lines = [text]
        if run:
            lines.append(f"\n✅ Comandos executados ({len(run)}): " + "; ".join(run))
        if denied:
            lines.append(f"\n⛔ Negados ({len(denied)}): " + "; ".join(denied))
        return "\n".join(lines)[:4000]

    def status() -> str:
        # relatório legível por padrão (o JSON só se pedido explicitamente)
        report = handle_doctor(cfg)
        return format_doctor_human(report)[:4000]

    def remember(text: str) -> str:
        from jarvis.core.memory import EpisodicMemory, KIND_FACT, MemoryEvent

        pid = EpisodicMemory(cfg).remember(MemoryEvent(kind=KIND_FACT, text=text))
        return f"lembrado ✅ (id={pid})" if pid else "não consegui gravar (serviços fora?)"

    def vault(action: str) -> str:
        from jarvis.core.vault import MemoryVault

        v = MemoryVault()
        if action.strip() == "summarize":
            return str(v.summarize(since_days=7, commit=True))
        notes = v.list_notes()
        return "\n".join(notes) if notes else "(vault vazio)"

    return TelegramChannel(
        cfg.telegram_token,
        _parse_chats(cfg.telegram_chat_id),
        ask_fn=ask,
        agent_fn=agent,
        status_fn=status,
        remember_fn=remember,
        vault_fn=vault,
    )
