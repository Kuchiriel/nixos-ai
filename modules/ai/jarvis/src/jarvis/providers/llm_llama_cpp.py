"""llama.cpp backend adapter.

Implements the LLMBackend interface for llama-server's OpenAI-compatible API.
This is the current default backend.

Endpoints used:
- POST /v1/chat/completions — chat (+ SSE streaming via stream=true)
- POST /v1/embeddings — embeddings
- GET /health — health check
- GET /props — server properties (n_ctx, etc.)
- GET /models — model list
- GET /slots — slot status (optional)

MISSÃO 2 (ASYNC P0): streaming SSE real token a token.
- chat_stream(): gerador síncrono sobre requests stream=True (compat CLI).
- achat_stream(): gerador assíncrono sobre httpx.AsyncClient (event loop livre).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from .llm_backend import LLMBackend, ChatResponse, EmbeddingResponse, BackendInfo
from jarvis.providers.embedding import embed_long

logger = logging.getLogger(__name__)


def _build_session(
    total_retries: int = 3,
    backoff_factor: float = 0.5,
    backoff_jitter: float = 0.3,
) -> requests.Session:
    """Build an HTTP session with retry/backoff."""
    retry = Retry(
        total=total_retries,
        connect=total_retries,
        read=total_retries,
        status=total_retries,
        backoff_factor=backoff_factor,
        backoff_jitter=backoff_jitter,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
        respect_retry_after_header=True,
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    session = requests.Session()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class LlamaCppBackend(LLMBackend):
    """llama.cpp backend adapter.
    
    Connects to a running llama-server instance via its OpenAI-compatible API.
    Supports chat completions, embeddings, tool calling, and streaming.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        embed_url: str | None = None,
        model: str = "default",
        connect_timeout: float = 5.0,
        read_timeout: float = 120.0,
        session: requests.Session | None = None,
        enable_thinking: bool = True,
    ):
        """
        Args:
            base_url: Base URL for llama-server (e.g., http://127.0.0.1:8080)
            embed_url: Separate URL for embedding server (if different port)
            model: Model name to send in requests
            connect_timeout: Connection timeout in seconds
            read_timeout: Read timeout in seconds
            session: Optional pre-built requests session (for testing)
            enable_thinking: Marmaps JARVIS_LLM_DISABLE_THINKING (invertido).
                False envia chat_template_kwargs.enable_thinking=false
                (modelos thinking respondem em `content`; sem isso o Agent
                recebe content vazio). True = nada enviado (auto, como antes).
        """
        self._base_url = base_url.rstrip("/")
        self._embed_url = (embed_url or base_url).rstrip("/")
        self._model = model
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._session = session or _build_session()
        self._enable_thinking = enable_thinking
        self._info_cache: BackendInfo | None = None


    _STABLE_MODEL: dict[str, str] = {}

    def _stable_model_name(self, requested: str) -> str:
        """Fixa o nome do modelo servido (25/09: evita unload/load no router).

        Se chamarmos com 'default' e antes com 'bonsai', o router
        --models-max 1 descarrega e recarrega o modelo a cada troca — e o
        reload falha se a VRAM estiver ocupada (500). Fixamos no primeiro
        nome que o servidor aceitar.
        """
        key = self._base_url
        fixed = self._STABLE_MODEL.get(key)
        if fixed:
            return fixed
        if requested and requested not in ("default", "", None):
            self._STABLE_MODEL[key] = requested
            return requested
        # 'default': pergunta o que está residente e fixa nesse
        try:
            r = self._session.get(f"{self._base_url}/props", timeout=3)
            if r.status_code == 200:
                d = r.json()
                name = d.get("model_path") or d.get("model") or ""
                if name:
                    self._STABLE_MODEL[key] = "bonsai" if "bonsai" in name.lower() else requested
                    return self._STABLE_MODEL[key]
        except Exception:  # noqa: BLE001
            pass
        return requested or "default"


    _CTX_CACHE: dict[str, int] = {}

    def _context_window(self) -> int:
        """n_ctx real do endpoint (o dev.py detecta e mostra no banner)."""
        cached = self._CTX_CACHE.get(self._base_url)
        if cached:
            return cached
        try:
            r = self._session.get(f"{self._base_url}/props", timeout=3)
            if r.status_code == 200:
                d = r.json()
                n = (d.get("default_generation_settings", {}) or {}).get("n_ctx") \
                    or d.get("n_ctx") or d.get("context_length")
                if n:
                    self._CTX_CACHE[self._base_url] = int(n)
                    return int(n)
        except Exception:  # noqa: BLE001
            pass
        return 0

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> ChatResponse:
        """Send a chat completion request to llama-server."""
        t0 = time.monotonic()
        
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": stream,
        }
        # (25/09) Temperature so vai no payload se o caller definiu. Antes o
        # default 0.0 era enviado SEMPRE, sobrescrevendo o sampling afinado
        # que o modelo carrega no GGUF (general.sampling.*). Medido no bonsai
        # 8B: temp 0.0 -> 2/2 respostas IDENTICAS (greedy colapsa); default
        # do modelo (0.5 p/ bonsai) -> 2/2 diferentes. O vendor recomenda 0.5.
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        # 25/09 — o "server error" no 1o turno do REPL: o payload real
        # (system prompt + schema de 22 tools + historico) chegou a quase
        # a janela inteira do endpoint fraco, e o budget de resposta
        # pedido estourava o resto -> build devolvia 500. Aqui nunca se
        # pede mais do que cabe: a folga vem do n_ctx real (lido do
        # /props), nunca de um literal aqui.
        _nctx = self._context_window()
        if _nctx:
            _est = len(json.dumps(payload["messages"], ensure_ascii=False)) // 4
            _est += len(json.dumps(payload.get("tools", []), ensure_ascii=False)) // 4
            _room = _nctx - _est - 128
            if _room < 32:
                _room = 32
            want = max_tokens if max_tokens is not None else _room
            payload["max_tokens"] = max(16, min(int(want), _room))
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        if extra:
            payload.update(extra)
        if not self._enable_thinking:
            payload["chat_template_kwargs"] = self._thinking_kwarg(extra)

        # 25/09 — o "server error" no meio da conversa: o router
        # (--models-preset --models-max 1) faz UNLOAD+LOAD quando o nome do
        # modelo muda na requisição; se o reload cai enquanto a VRAM está
        # ocupada, o server responde 500 {"failed to load"} e a sessão morre.
        # Dois consertos aqui: (1) pin do nome do modelo já carregado
        # (evita o churn), (2) retry curtoSpecifically para esse 500.
        payload["model"] = self._stable_model_name(payload["model"])
        resp = self._session.post(
            f"{self._base_url}/v1/chat/completions",
            json=payload,
            timeout=(self._connect_timeout, self._read_timeout),
            stream=stream,
        )
        _code = getattr(resp, "status_code", 200)
        if _code >= 500:
            body = str(getattr(resp, "text", ""))[:200].lower()
            if "failed to load" in body or "loading" in body:
                # reload em andamento: espera e tenta 2x (2s, 5s)
                for wait_s in (2.0, 5.0):
                    time.sleep(wait_s)
                    resp = self._session.post(
                        f"{self._base_url}/v1/chat/completions",
                        json=payload,
                        timeout=(self._connect_timeout, self._read_timeout),
                        stream=stream,
                    )
                    if getattr(resp, "status_code", 200) < 500:
                        break
        elapsed = time.monotonic() - t0
        resp.raise_for_status()
        data = resp.json()

        _choices = data.get("choices") or []
        if not _choices:
            raise RuntimeError("LLM returned no choices (empty response)")
        choice = _choices[0]
        message = choice["message"]

        return ChatResponse(
            content=message.get("content", ""),
            reasoning=message.get("reasoning_content", "") or "",
            tool_calls=message.get("tool_calls", []),
            finish_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
            timings=data.get("timings", {}),
            latency_seconds=elapsed,
            backend="llama-cpp",
            model_id=data.get("model", self._model),
        )

    def _thinking_kwarg(self, extra: dict[str, Any] | None) -> dict[str, Any]:
        """chat_template_kwargs p/ desligar thinking (mesma regra do chat()).

        Extraído p/ uso compartilhado: chat() e _stream_payload() (streams
        de modelos thinking rendiam zero tokens úteis sem isso).
        """
        tpl = dict((extra or {}).get("chat_template_kwargs") or {})
        tpl.setdefault("enable_thinking", False)
        return tpl

    def _stream_payload(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Payload compartilhado entre chat_stream() e achat_stream()."""
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        # mesma regra do chat(): so envia temperature se o caller definiu
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if not self._enable_thinking:
            payload["chat_template_kwargs"] = self._thinking_kwarg(None)
        return payload

    @staticmethod
    def _extract_delta(line: str) -> str | None:
        """Extrai o token incremental de uma linha SSE. None = ignorar."""
        if not line.startswith("data:"):
            return None
        data = line[5:].strip()
        if not data or data == "[DONE]":
            return None
        try:
            chunk = json.loads(data)
        except ValueError:
            return None
        choices = chunk.get("choices") or []
        if not choices:
            return None
        delta = choices[0].get("delta") or {}
        return delta.get("content") or None

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[str]:
        """Yields incrementais token a token via SSE real (requests stream=True).

        Compatível com consumidores síncronos (CLI). Não aguarda o buffer
        completo: o primeiro yield sai no TTFT do servidor.
        """
        payload = self._stream_payload(
            messages, temperature=temperature, max_tokens=max_tokens, tools=tools,
        )
        with self._session.post(
            f"{self._base_url}/v1/chat/completions",
            json=payload,
            timeout=(self._connect_timeout, self._read_timeout),
            stream=True,
        ) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                token = self._extract_delta(line)
                if token:
                    yield token

    async def achat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[str]:
        """Yields incrementais sem bloquear o event loop (httpx.AsyncClient).

        Para o painel SvelteKit via SSE/WebSocket e futuros callers async.
        """
        payload = self._stream_payload(
            messages, temperature=temperature, max_tokens=max_tokens, tools=tools,
        )
        timeout = httpx.Timeout(self._read_timeout, connect=self._connect_timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    token = self._extract_delta(line)
                    if token:
                        yield token

    def embed(self, text: str, model: str | None = None) -> list[float]:
        """Embedding via llama-server (texto longo: chunk + mean-pool)."""
        def _one(chunk: str) -> list[float]:
            payload: dict[str, Any] = {
                "model": model or self._model,
                "input": chunk,
            }
            resp = self._session.post(
                f"{self._embed_url}/v1/embeddings",
                json=payload,
                timeout=(self._connect_timeout, self._read_timeout),
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]

        return embed_long(_one, text)

    def health(self, timeout: float = 3.0) -> bool:
        """Check if llama-server is responding."""
        try:
            resp = self._session.get(
                f"{self._base_url}/health",
                timeout=(timeout, timeout),
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def info(self) -> BackendInfo:
        """Get server info from /props endpoint."""
        if self._info_cache is not None:
            return self._info_cache
        
        try:
            resp = self._session.get(
                f"{self._base_url}/props",
                timeout=(self._connect_timeout, 5),
            )
            resp.raise_for_status()
            data = resp.json()
            settings = data.get("default_generation_settings", {})
            
            self._info_cache = BackendInfo(
                backend_type="llama-cpp",
                model_name=settings.get("model", self._model),
                n_ctx=settings.get("n_ctx", 0),
                n_gpu_layers=settings.get("n_gpu_layers", 0),
                is_available=True,
                extra=settings,
            )
            return self._info_cache
        except Exception as e:
            logger.warning("Failed to get backend info: %s", e)
            return BackendInfo(
                backend_type="llama-cpp",
                model_name=self._model,
                is_available=False,
            )

    _SLOTS_MODEL: dict[str, str] = {}

    def _slots_model_id(self) -> str:
        """Id do modelo p/ /slots (26/09, voz quebrada: router b10743 exige
        ?model= — sem ele, 400 → status vazio → is_busy sempre True → o
        voice_loop recusava TUDO com 'outra tarefa'. Espelhar em prism)."""
        cached = self._SLOTS_MODEL.get(self._base_url)
        if cached:
            return cached
        if self._model and self._model not in ("default", "", None):
            return self._model
        try:
            r = self._session.get(f"{self._base_url}/v1/models", timeout=3)
            if r.status_code == 200:
                data = (r.json().get("data") or [])
                if data and data[0].get("id"):
                    self._SLOTS_MODEL[self._base_url] = data[0]["id"]
                    return data[0]["id"]
        except Exception:  # noqa: BLE001
            pass
        return self._model or "default"

    def get_slots_status(self) -> dict[str, Any]:
        """Get slot status from /slots endpoint (llama.cpp specific)."""
        try:
            resp = self._session.get(
                f"{self._base_url}/slots",
                params={"model": self._slots_model_id()},
                timeout=(self._connect_timeout, 3),
            )
            if resp.status_code != 200:
                # servidor antigo sem ?model=: tenta nu (compat)
                resp = self._session.get(
                    f"{self._base_url}/slots",
                    timeout=(self._connect_timeout, 3),
                )
            if resp.status_code != 200:
                return {}
            slots = resp.json()
            if not isinstance(slots, list):
                return {}
            idle = sum(1 for s in slots if not s.get("is_processing"))
            busy = sum(1 for s in slots if s.get("is_processing"))
            total_ctx = sum(s.get("n_ctx", 0) for s in slots)
            used_ctx = sum(s.get("n_prompt_tokens", 0) for s in slots)
            return {
                "slots_total": len(slots),
                "slots_idle": idle,
                "slots_busy": busy,
                "ctx_total": total_ctx,
                "ctx_used": used_ctx,
                "ctx_pct": round(used_ctx / total_ctx * 100, 1) if total_ctx > 0 else 0,
            }
        except (requests.RequestException, ValueError):
            return {}

    def is_busy(self, ctx_threshold: float = 80.0) -> bool:
        """Check if server is under heavy load."""
        status = self.get_slots_status()
        if not status:
            return True
        if status["slots_busy"] >= status["slots_total"]:
            return True
        if status["ctx_pct"] > ctx_threshold:
            return True
        return False

    def close(self) -> None:
        """Close the HTTP session."""
        self._session.close()
