"""Loop Detector — detecta padrões de loop no agent loop e fornece
estratégias de recovery.

Detecta 4 padrões:
  1. Tool call repetida (mesma tool + args)
  2. Sequência cíclica (A→B→A→B)
  3. Edição sem progresso (edit→revert→edit)
  4. Stagnation (N iterações sem mudança significativa)

Cada detecção gera uma RecoveryStrategy que altera condição do loop.
"""

from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LoopType(Enum):
    NONE = "none"
    DUPLICATE = "duplicate"          # mesma tool+args 2x+
    CYCLE = "cycle"                  # sequência A→B→A→B
    EDIT_REVERT = "edit_revert"      # edit→revert→edit
    STAGNATION = "stagnation"        # N iteras sem progresso


class RecoveryAction(Enum):
    NONE = "none"
    INJECT_WARNING = "inject_warning"      # avisa o modelo
    SUMMARIZE_CONTEXT = "summarize_context"  # comprime contexto
    FORCE_ANSWER = "force_answer"           # força resposta final
    CHANGE_STRATEGY = "change_strategy"     # muda abordagem
    ABORT = "abort"                         # para o loop


@dataclass
class RecoveryStrategy:
    action: RecoveryAction
    message: str
    loop_type: LoopType
    iteration: int


@dataclass
class ToolSignature:
    """Assinatura de uma tool call para comparação."""
    name: str
    args_hash: str
    raw_args: str

    @classmethod
    def from_tool_call(cls, tool_call: dict[str, Any]) -> ToolSignature:
        func = tool_call.get("function", {})
        if not isinstance(func, dict):
            func = {}
        name = func.get("name", "")
        raw_args = func.get("arguments", "")
        if isinstance(raw_args, dict):
            raw_args = json.dumps(raw_args, sort_keys=True)
        args_hash = hashlib.md5(raw_args.encode()).hexdigest()[:12]
        return cls(name=name, args_hash=args_hash, raw_args=raw_args)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ToolSignature):
            return NotImplemented
        return self.name == other.name and self.args_hash == other.args_hash

    def __hash__(self) -> int:
        return hash((self.name, self.args_hash))


@dataclass
class LoopDetector:
    """Detecta padrões de loop e sugere recovery strategies.

    Uso:
        detector = LoopDetector(max_history=20)
        for turn in range(MAX_TURNS):
            strategy = detector.check(tool_calls, content)
            if strategy.action == RecoveryAction.ABORT:
                break
            if strategy.action != RecoveryAction.NONE:
                messages.append({"role": "system", "content": strategy.message})
    """
    max_history: int = 20
    max_consecutive_duplicates: int = 2
    max_cycle_length: int = 6
    stagnation_threshold: int = 4
    edit_revert_threshold: int = 3

    # Estado interno
    _history: list[ToolSignature] = field(default_factory=list)
    _consecutive_duplicates: int = 0
    _edit_count: int = 0
    _last_content_hash: str = ""
    _stagnation_count: int = 0
    _total_iterations: int = 0

    def reset(self) -> None:
        """Reseta o estado (novo prompt)."""
        self._history.clear()
        self._consecutive_duplicates = 0
        self._edit_count = 0
        self._last_content_hash = ""
        self._stagnation_count = 0
        self._total_iterations = 0

    def check(
        self,
        tool_calls: list[dict[str, Any]] | None,
        content: str = "",
    ) -> RecoveryStrategy:
        """Verifica padrões de loop. Retorna RecoveryStrategy."""
        self._total_iterations += 1

        if not tool_calls:
            # Sem tool calls — verificar stagnation
            return self._check_stagnation(content)

        for tc in tool_calls:
            sig = ToolSignature.from_tool_call(tc)
            self._history.append(sig)

            # 1. Duplicate detection
            result = self._check_duplicate(sig)
            if result.action != RecoveryAction.NONE:
                return result

            # 2. Cycle detection
            result = self._check_cycle()
            if result.action != RecoveryAction.NONE:
                return result

            # 3. Edit-revert detection
            result = self._check_edit_revert(sig)
            if result.action != RecoveryAction.NONE:
                return result

            # 3b. Windowed relapse (elo D 16/09): mesma assinatura volta
            # pela 3a vez dentro da janela mesmo com calls intercaladas
            # (write→list→write→list quebra streak consecutivo). Ex.:
            # placeholder escrito no path do diretório m6/m10/m16/m23.
            result = self._check_windowed_relapse(sig)
            if result.action != RecoveryAction.NONE:
                return result

        # 4. Stagnation (genérico)
        return self._check_stagnation(content)

    def _check_duplicate(self, sig: ToolSignature) -> RecoveryStrategy:
        """Detecta tool call repetida com mesmos argumentos."""
        if len(self._history) >= 2 and self._history[-1] == self._history[-2]:
            self._consecutive_duplicates += 1
        else:
            self._consecutive_duplicates = 0

        if self._consecutive_duplicates >= self.max_consecutive_duplicates:
            self._consecutive_duplicates = 0
            # A/B 16/09: "try a completely different approach" sem nomear a
            # alternativa devolvia o modelo pra MESMA leitura (B5 [10]).
            # Mesma dose acionável do cycle: leitura repetida = path não
            # existe, criar ou encerrar.
            _dup_extra = ""
            if sig.name in ("read_file", "list_directory", "semantic_search", "code_search"):
                _dup_extra = (
                    " O path lido NÃO EXISTE (você já viu o erro 3 vezes) — "
                    "mais leitura nunca vai resolver. Se a task é CRIAR, chame "
                    "write_file com o path completo AGORA; senão, responda e encerre."
                )
            return RecoveryStrategy(
                action=RecoveryAction.INJECT_WARNING,
                message=(
                    f"You repeated '{sig.name}' with identical arguments "
                    f"{self.max_consecutive_duplicates + 1} times. This is not productive. "
                    f"Use the data you already have to provide a final answer, "
                    f"or try a completely different approach.{_dup_extra}"
                ),
                loop_type=LoopType.DUPLICATE,
                iteration=self._total_iterations,
            )
        return RecoveryStrategy(
            action=RecoveryAction.NONE, message="",
            loop_type=LoopType.NONE, iteration=self._total_iterations,
        )

    def _check_cycle(self) -> RecoveryStrategy:
        """Detecta sequência cíclica A→B→A→B."""
        n = len(self._history)
        if n < 4:
            return RecoveryStrategy(
                action=RecoveryAction.NONE, message="",
                loop_type=LoopType.NONE, iteration=self._total_iterations,
            )

        # Testa ciclos de tamanho 2 a max_cycle_length/2
        for cycle_len in range(2, min(self.max_cycle_length // 2 + 1, n // 2 + 1)):
            window = self._history[-cycle_len * 2:]
            first_half = window[:cycle_len]
            second_half = window[cycle_len:]
            if first_half == second_half:
                tools_seq = " → ".join(s.name for s in first_half)
                # A/B 16/09: ciclo só de leitura = agente procurando algo que
                # não existe. "Try a different strategy" sem nomear a estratégia
                # devolvia o modelo pro mesmo ciclo (mundo verificado: 0/3).
                # Nomear a alternativa (criar) quebra o beco sem saída.
                _read_only = {"read_file", "list_directory", "semantic_search", "code_search"}
                _extra = ""
                if {s.name for s in first_half} <= _read_only:
                    _extra = (
                        " Você está lendo paths em loop e eles NÃO EXISTEM — "
                        "mais leitura nunca vai resolver. Se a task é CRIAR, "
                        "chame write_file com o path completo AGORA (cria o arquivo "
                        "e os diretórios-pai). Se a task não é criar, responda com "
                        "o que descobriu e termine."
                    )
                return RecoveryStrategy(
                    action=RecoveryAction.CHANGE_STRATEGY,
                    message=(
                        f"Cycle detected: [{tools_seq}] repeated. "
                        f"Your current approach is not making progress. "
                        f"Stop this pattern.{_extra}"
                    ),
                    loop_type=LoopType.CYCLE,
                    iteration=self._total_iterations,
                )
        return RecoveryStrategy(
            action=RecoveryAction.NONE, message="",
            loop_type=LoopType.NONE, iteration=self._total_iterations,
        )

    def _check_edit_revert(self, sig: ToolSignature) -> RecoveryStrategy:
        """Detecta padrão edit→revert→edit."""
        edit_tools = {"str_replace", "write_file"}
        if sig.name not in edit_tools:
            self._edit_count = 0
            return RecoveryStrategy(
                action=RecoveryAction.NONE, message="",
                loop_type=LoopType.NONE, iteration=self._total_iterations,
            )

        # Se a tool atual é igual à 2 positions atrás, é edit→something→edit
        if len(self._history) >= 3:
            prev_edit = self._history[-3]
            if prev_edit.name in edit_tools and sig.name == prev_edit.name:
                self._edit_count += 1
            else:
                self._edit_count = 1
        else:
            self._edit_count = 1

        if self._edit_count >= self.edit_revert_threshold:
            self._edit_count = 0
            return RecoveryStrategy(
                action=RecoveryAction.CHANGE_STRATEGY,
                message=(
                    f"Edit-revert cycle detected ({self.edit_revert_threshold}+ edits). "
                    f"Your changes are not sticking. "
                    f"Analyze the root cause before editing again. "
                    f"Read the file completely, understand the issue, then make one correct edit."
                ),
                loop_type=LoopType.EDIT_REVERT,
                iteration=self._total_iterations,
            )
        return RecoveryStrategy(
            action=RecoveryAction.NONE, message="",
            loop_type=LoopType.NONE, iteration=self._total_iterations,
        )

    def _check_windowed_relapse(self, sig: ToolSignature) -> RecoveryStrategy:
        """Detecta relapso: mesma assinatura 3+ vezes na janela (max_history),
        mesmo com calls intercaladas. Streak consecutivo não pega
        write→list→write→list (elo D H3-chain m22-m24: relapso no fim)."""
        window = self._history[-self.max_history:]
        hits = sum(1 for s in window if s == sig)
        if hits >= 3:
            key = ""
            try:
                args = json.loads(sig.raw_args) if sig.raw_args else {}
                key = str(args.get("path") or args.get("cmd")
                          or args.get("selector") or "")[:80]
            except Exception:
                pass
            return RecoveryStrategy(
                action=RecoveryAction.INJECT_WARNING,
                message=(
                    f"You already called '{sig.name} {key}' {hits} times "
                    f"in this run — the outcome is not changing. Do NOT "
                    f"call it again with the same arguments. Instead: "
                    f"re-read the artifacts you already produced and "
                    f"CORRECT the final one (a stale/partial result left "
                    f"behind fails verification). If nothing else helps, "
                    f"answer with what you have and stop."
                ),
                loop_type=LoopType.DUPLICATE,
                iteration=self._total_iterations,
            )
        return RecoveryStrategy(
            action=RecoveryAction.NONE, message="",
            loop_type=LoopType.NONE, iteration=self._total_iterations,
        )

    def _check_stagnation(self, content: str) -> RecoveryStrategy:
        """Detecta stagnation — iterações sem progresso medível."""
        # llama.cpp returns content=None on tool-call turns; never crash on it.
        content = content or ""
        content_hash = hashlib.md5(content[:500].encode()).hexdigest()[:8]
        if content_hash == self._last_content_hash and content.strip():
            self._stagnation_count += 1
        else:
            self._stagnation_count = 0
        self._last_content_hash = content_hash

        if self._stagnation_count >= self.stagnation_threshold:
            self._stagnation_count = 0
            if self._total_iterations >= 6:
                return RecoveryStrategy(
                    action=RecoveryAction.FORCE_ANSWER,
                    message=(
                        "No progress detected for multiple iterations. "
                        "Provide your best answer now with what you have. "
                        "If you need more information, specify exactly what you need."
                    ),
                    loop_type=LoopType.STAGNATION,
                    iteration=self._total_iterations,
                )
        return RecoveryStrategy(
            action=RecoveryAction.NONE, message="",
            loop_type=LoopType.NONE, iteration=self._total_iterations,
        )
