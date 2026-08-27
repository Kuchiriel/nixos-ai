"""Context Budget Manager — gerencia orçamento de tokens no agent loop.

Responsabilidades:
  1. Estimar tokens por mensagem (heurística: ~4 chars/token)
  2. Truncar tool outputs por prioridade quando budget está baixo
  3. Inserir warnings quando contexto >80% do budget
  4. Comprimir histórico antigo quando necessário
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


# Heurística: ~4 chars por token para modelos com tokenizer similar ao GPT
CHARS_PER_TOKEN = 4

# Tool outputs são o maior consumidor — eles são truncados primeiro
TOOL_OUTPUT_PRIORITY = {
    "execute_shell": 1,      # Mais importante — resultado de comando
    "read_file": 2,          # Conteúdo de arquivo
    "code_search": 3,        # Resultado de busca
    "list_directory": 4,     # Listagem
    "capture_screen": 5,     # Screenshot (metadata)
    "str_replace": 6,        # Confirmação de edição
    "write_file": 7,         # Confirmação de escrita
    "run_tests": 8,          # Output de teste
}

# Limites de truncamento por prioridade
TRUNCATE_LIMITS = {
    1: 4000,   # execute_shell: até 4K chars
    2: 3000,   # read_file: até 3K chars
    3: 2000,   # code_search: até 2K chars
    4: 1000,   # list_directory: até 1K chars
    5: 500,    # capture_screen: metadata only
    6: 500,    # str_replace: confirmation
    7: 500,    # write_file: confirmation
    8: 3000,   # run_tests: até 3K chars
}


@dataclass
class ContextBudget:
    """Gerencia orçamento de tokens para o agent loop.

    Uso:
        budget = ContextBudget(max_tokens=32000)
        for msg in messages:
            budget.add_message(msg)
        if budget.usage_percent > 80:
            budget.truncate_tool_outputs()
            budget.compress_history()
    """
    max_tokens: int = 32000
    reserved_tokens: int = 2000  # Reservado pra system prompt + resposta
    warning_threshold: float = 0.80  # 80% do budget

    # Estado
    _total_tokens: int = field(default=0, init=False)
    _messages: list[dict[str, Any]] = field(default_factory=list, init=False)
    _tool_message_indices: list[int] = field(default_factory=list, init=False)

    @property
    def available_tokens(self) -> int:
        return self.max_tokens - self.reserved_tokens

    @property
    def used_tokens(self) -> int:
        return self._total_tokens

    @property
    def remaining_tokens(self) -> int:
        return max(0, self.available_tokens - self._total_tokens)

    @property
    def usage_percent(self) -> float:
        if self.available_tokens <= 0:
            return 100.0
        return (self._total_tokens / self.available_tokens) * 100

    @property
    def needs_warning(self) -> bool:
        return self.usage_percent >= self.warning_threshold * 100

    @property
    def is_overflow(self) -> bool:
        return self._total_tokens > self.available_tokens

    def estimate_tokens(self, text: str) -> int:
        """Estima tokens de um texto (~4 chars/token)."""
        return max(1, len(text) // CHARS_PER_TOKEN)

    def add_message(self, msg: dict[str, Any]) -> int:
        """Adiciona uma mensagem e retorna tokens estimados."""
        content = msg.get("content", "")
        if isinstance(content, list):
            # multipart content
            content = " ".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        tokens = self.estimate_tokens(content)

        # Tool calls e arguments também consomem tokens
        if "tool_calls" in msg and msg["tool_calls"]:
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                tokens += self.estimate_tokens(func.get("name", ""))
                tokens += self.estimate_tokens(func.get("arguments", ""))

        self._messages.append(msg)
        self._total_tokens += tokens

        # Marcar tool messages pra truncamento
        if msg.get("role") == "tool":
            self._tool_message_indices.append(len(self._messages) - 1)

        return tokens

    def get_budget_warning(self) -> str | None:
        """Retorna mensagem de warning se budget está baixo."""
        if not self.needs_warning:
            return None
        pct = self.usage_percent
        remaining = self.remaining_tokens
        return (
            f"⚠️ Context budget: {pct:.0f}% used "
            f"({self._total_tokens}/{self.available_tokens} tokens). "
            f"~{remaining} tokens remaining. "
            f"Prioritize concise responses and minimize tool output."
        )

    def truncate_tool_outputs(self, aggressive: bool = False) -> int:
        """Trunca tool outputs por prioridade. Retorna chars removidos."""
        removed = 0
        for idx in reversed(self._tool_message_indices):
            if idx >= len(self._messages):
                continue
            msg = self._messages[idx]
            content = msg.get("content", "")
            if not content or len(content) < 500:
                continue

            # Determinar prioridade pela tool name
            tool_name = msg.get("name", "unknown")
            priority = TOOL_OUTPUT_PRIORITY.get(tool_name, 99)
            limit = TRUNCATE_LIMITS.get(priority, 1000)
            if aggressive:
                limit = limit // 2

            if len(content) > limit:
                truncated = content[:limit] + f"\n... [truncated from {len(content)} chars]"
                removed += len(content) - len(truncated)
                msg["content"] = truncated
                # Atualizar estimativa de tokens
                old_tokens = self.estimate_tokens(content)
                new_tokens = self.estimate_tokens(truncated)
                self._total_tokens -= (old_tokens - new_tokens)

        return removed

    def compress_history(self, keep_last: int = 6) -> int:
        """Comprime mensagens antigas, mantendo as últimas keep_last.
        Retorna tokens economizados."""
        if len(self._messages) <= keep_last + 2:
            return 0

        saved = 0
        # Manter: system[0] + user[1] + últimas keep_last
        compress_end = len(self._messages) - keep_last
        for i in range(2, compress_end):  # Pular system e first user
            msg = self._messages[i]
            content = msg.get("content", "")
            if not content or len(content) < 200:
                continue

            old_tokens = self.estimate_tokens(content)
            # Substituir por resumo de 1 linha
            summary = f"[Earlier context: {msg.get('role', '?')} — {len(content)} chars compressed]"
            msg["content"] = summary
            new_tokens = self.estimate_tokens(summary)
            saved += (old_tokens - new_tokens)

        self._total_tokens -= saved
        return saved

    def get_stats(self) -> dict[str, Any]:
        """Retorna estatísticas do budget."""
        return {
            "max_tokens": self.max_tokens,
            "used_tokens": self._total_tokens,
            "remaining_tokens": self.remaining_tokens,
            "usage_percent": round(self.usage_percent, 1),
            "total_messages": len(self._messages),
            "tool_messages": len(self._tool_message_indices),
            "needs_warning": self.needs_warning,
            "is_overflow": self.is_overflow,
        }
