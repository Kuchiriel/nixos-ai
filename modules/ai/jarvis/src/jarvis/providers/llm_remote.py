"""Remote OpenAI-compatible backend (OpenRouter, NVIDIA NIM, etc.).

Mesmo formato do LlamaCppBackend (chat/completions), mas com Bearer auth
e sem timings/thinking do llama.cpp. Chaves via env (abstração
/etc/litellm.env → home.nix). Uso: fallback da cascata quando o modelo
local trava (STUCK) ou cai — camadas em model_policy.CASCADE_MAP.
"""
from __future__ import annotations

import re
import time
from typing import Any

from .llm_backend import BackendInfo, ChatResponse, LLMBackend


def _sanitize_message(m: dict[str, Any]) -> dict[str, Any]:
    """Reduz mensagem ao schema OpenAI estrito.

    Campos internos do harness (finish_reason, index, provider_extra...)
    quebram providers que validam (Groq 400). tool_calls preservadas no
    formato canônico.
    """
    out: dict[str, Any] = {"role": m.get("role", "user")}
    for k in ("content", "name", "tool_call_id"):
        if m.get(k) is not None:
            out[k] = m[k]
    tcs = m.get("tool_calls")
    if tcs:
        clean = []
        for tc in tcs:
            fn = (tc.get("function") or {})
            clean.append({"id": tc.get("id", ""), "type": "function",
                          "function": {"name": fn.get("name", ""),
                                       "arguments": fn.get("arguments", "{}")}})
        out["tool_calls"] = clean
    return out


class RemoteBackend(LLMBackend):
    """Backend remoto OpenAI-compatible com API key."""
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        connect_timeout: float = 10.0,
        read_timeout: float = 180.0,
        session=None,
        provider: str = "remote",
    ):
        # (06/11) NORMALIZA A BASE — o cascade do harness (free-providers
        # .json) já traz a URL COM a versão (".../openai/v1",
        # ".../v1beta/openai") e este backend acrescentava "/v1" de novo
        # → 404 em TODOS os provedores (a cascade existia mas nunca
        # respondeu). Agora: se a base já tem segmento de versão, mantém;
        # se não tem, acrescenta /v1 (o default do llm_factory).
        _base = base_url.rstrip("/")
        if not re.search(r"/v\d", _base):
            _base += "/v1"
        self._base_url = _base
        self._model = model
        self._api_key = api_key
        self._connect_timeout = connect_timeout
        self._read_timeout = read_timeout
        self._provider = provider
        if session is not None:
            self._session = session
        else:
            import requests
            s = requests.Session()
            if api_key:
                s.headers.update({"Authorization": f"Bearer {api_key}"})
            s.headers.update({"Content-Type": "application/json"})
            self._session = s

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        extra: dict[str, Any] | None = None,
    ) -> ChatResponse:
        t0 = time.monotonic()
        payload: dict[str, Any] = {
            "model": self._model,
            # 29/09 (E-cell): Groq valida estrito — finish_reason e outros
            # campos internos do histórico dão 400. Sanitiza p/ o schema
            # OpenAI (llama.cpp ignora extras; provider externo não).
            "messages": [_sanitize_message(m) for m in messages],
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
            if tool_choice:
                payload["tool_choice"] = tool_choice
        resp = self._session.post(
            f"{self._base_url}/chat/completions",
            json=payload,
            timeout=(self._connect_timeout, self._read_timeout),
        )
        elapsed = time.monotonic() - t0
        resp.raise_for_status()
        data = resp.json()
        _choices = data.get("choices") or []
        if not _choices:
            raise RuntimeError("LLM returned no choices (empty response)")
        choice = _choices[0]
        message = choice["message"]
        return ChatResponse(
            content=message.get("content", "") or "",
            reasoning=message.get("reasoning_content", "") or "",
            tool_calls=message.get("tool_calls", []),
            finish_reason=choice.get("finish_reason", ""),
            usage=data.get("usage", {}),
            timings={},
            latency_seconds=elapsed,
            backend=self._provider,
            model_id=data.get("model", self._model),
        )

    def embed(self, text: str, model: str | None = None) -> list[float]:
        raise NotImplementedError("remote backend não faz embeddings")

    def health(self, timeout: float = 3.0) -> bool:
        try:
            r = self._session.get(f"{self._base_url}/models",
                                  timeout=timeout)
            return r.status_code == 200
        except Exception:
            return False

    def info(self) -> BackendInfo:
        return BackendInfo(name=self._provider, model=self._model,
                           available=self.health())
