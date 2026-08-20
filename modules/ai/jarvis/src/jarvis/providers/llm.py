"""Provider de LLM — cliente OpenAI-compatível para o llama.cpp (llama-server).

O core do JARVIS conversa com esta interface; trocar de backend
(ollama, outro servidor) não afeta o core.
"""

from __future__ import annotations

from typing import Any

import requests

from jarvis.core.config import Config


class LLMError(RuntimeError):
    pass


class LLMClient:
    """Cliente mínimo para a API /v1/chat/completions do llama-server."""

    def __init__(self, config: Config | None = None) -> None:
        self._cfg = config or Config()
        self._base = self._cfg.llm_base_url.rstrip("/")

    # --- health ---

    def is_available(self, timeout: float = 2.0) -> bool:
        try:
            resp = requests.get(f"{self._base}/models", timeout=timeout)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def models(self) -> list[dict[str, Any]]:
        resp = requests.get(f"{self._base}/models", timeout=self._cfg.llm_timeout)
        resp.raise_for_status()
        return resp.json().get("data", [])

    # --- chat ---

    def chat(self, messages: list[dict[str, str]], *, temperature: float = 0.0, max_tokens: int | None = None) -> str:
        payload: dict[str, Any] = {
            "model": self._cfg.llm_model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if self._cfg.llm_disable_thinking:
            # Qwen3/Qwen3.6: desliga o modo de raciocínio (chat template suporta
            # enable_thinking) — tool calling direto e rápido em CPU. Aceito pelo
            # llama-server (validado ao vivo); ignorado por templates que não o
            # conhecem (jinja trata variável ausente como falsy).
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        try:
            resp = requests.post(f"{self._base}/chat/completions", json=payload, timeout=self._cfg.llm_timeout)
        except requests.RequestException as exc:
            raise LLMError(f"falha de conexão com {self._base}: {exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"llama-server respondeu HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"resposta sem conteúdo esperado: {data}") from exc

    # --- embeddings ---

    # ctx do modelo de embedding (nomic-embed-text-v2-moe = 512 tokens);
    # além disso o embedding perde qualidade em textos longos de qualquer forma
    _EMBED_MAX_CHARS = 600O  # ~1500 tokens seguro p/ o ctx 2048

    def embed(self, text: str, model: str | None = None) -> list[float]:
        """Embedding via /v1/embeddings — servidor dedicado (--embeddings).

        Usa `embed_base_url` (porta 8081 por padrão), separado do chat.
        Trunca para o ctx do modelo (512 tokens): o llama-server rejeita
        input maior com HTTP 400 "exceed_context_size_error".
        """
        base = self._cfg.embed_base_url.rstrip("/")
        text = text[: self._EMBED_MAX_CHARS]
        payload: dict[str, Any] = {"model": model or self._cfg.embed_model, "input": text}
        try:
            resp = requests.post(f"{base}/embeddings", json=payload, timeout=self._cfg.llm_timeout)
        except requests.RequestException as exc:
            raise LLMError(f"falha de conexão com {base}: {exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"embeddings respondeu HTTP {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            return data["data"][0]["embedding"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"embedding sem dado esperado: {data}") from exc
