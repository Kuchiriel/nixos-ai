"""TOOL SURFACE — entropy control (Contract A, E6 evidence).

Empirical basis (EXP-E2/D2/E6, 20/09): correct tool isolated -> 9/9;
read_file present as attractor -> 0/6. Progressive disclosure via
deterministic task-class -> minimal action subset, excluding attractors,
recovers capability without removing functionality.

Design: TASK_CLASSES + classify_task (deterministic keyword rules,
ordered secret>data>knowledge>action>write>read) + surface_for (drop
attractors per class) + entropy_metrics. Deterministic => unit-testable
without a model.

GENERAL harness property (model-agnostic, §19): fewer plausible choices
=> more reliable selection for SLMs. MODEL-SPECIFIC detail: numeric
sensitivity is Bonsai-specific (not encoded here).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

READ_TOOLS = {"read_file", "list_directory"}
ACTION_TOOLS = {"execute_shell", "list_directory"}
WRITE_TOOLS = {"write_file", "str_replace", "read_file", "list_directory"}
KNOWLEDGE_TOOLS = {"read_file", "rag_search", "list_directory"}
DATA_TOOLS = {"build_json_dataset", "read_file"}
SECRET_TOOLS = {"sanitize_secrets", "read_file"}
WEB_TOOLS = {"execute_shell"}
SHELL_ONLY = {"execute_shell"}

_ATTRACTORS = {"read_file": ("action", "write")}

_RULES = [
    # (pattern, task_class) — primeira regra que casar vence (ordem = prioridade)
    (re.compile(r"secret|token|credential|\.env|senha|password", re.I), "secret"),
    (re.compile(r"csv|schema\.json|dataset|transform", re.I), "data"),
    (re.compile(r"commit|git log|history|changed files", re.I), "action"),
    (re.compile(r"count|list|find|search|grep|how many", re.I), "action"),
    (re.compile(r"write|create|edit|save|generate|produce|append|update", re.I), "write"),
    (re.compile(r"read|cat|show|print|what is in", re.I), "read"),
]


@dataclass
class ToolSurface:
    """Superfície calculada para uma task."""
    task_class: str
    available: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    rationale: str = ""

    def entropy(self) -> dict:
        return entropy_metrics(self.available)

    def to_dict(self) -> dict:
        return {"task_class": self.task_class, "available": self.available,
                "dropped": self.dropped, "rationale": self.rationale,
                "entropy": self.entropy()}


def classify_task(task: str) -> str:
    """Deterministic keyword classification (S4/E6 evidence). Regras
    ordenadas por prioridade: secret > data > action > write > read."""
    if not task:
        return "read"
    for pattern, cls in _RULES:
        if pattern.search(task):
            return cls
    return "read"


_SURFACE = {
    "read": READ_TOOLS,
    "write": WRITE_TOOLS,
    "action": ACTION_TOOLS,
    "data": DATA_TOOLS,
    "secret": SECRET_TOOLS,
    "knowledge": KNOWLEDGE_TOOLS,
    "web": WEB_TOOLS,
}


def surface_for(task_class: str, base_tools: list[str] | None = None,
                task: str = "") -> ToolSurface:
    """Computa a superfície para uma task class a partir dos tools base.

    Attractor rule (E6): para classes de AÇÃO/ESCRITA, read_file é o
    distrator comprovado (0/6) — removido; read_file fica disponível via
    leitura explícita da task (class read) ou sob demanda do modelo
    quando a class é knowledge.
    """
    base = set(base_tools or _SURFACE.get("read"))
    keep = set(_SURFACE.get(task_class, READ_TOOLS))
    # Task explícita pode reconduzir (read citado no texto de ação) —
    # regra mínima: se a task pedir leitura, read_file volta.
    if task and re.search(r"read|open|capture|list", task, re.I):
        keep.add("read_file")
    available = sorted(n for n in base & keep)
    dropped = sorted(base - set(available))
    return ToolSurface(task_class=task_class, available=available,
                       dropped=dropped,
                       rationale=f"surface({task_class}); attractors dropped")


def entropy_metrics(tool_names: list[str]) -> dict:
    """Métrica de engenharia (não estatística decorativa, §PHASE 2)."""
    names = list(tool_names)
    return {
        "available": len(names),
        "semantically_plausible": len(names),  # proxy: superfície já filtrada
        "correct": 1,  # assumido pós-classificação determinística
        "delta": len(names) - 1,
    }