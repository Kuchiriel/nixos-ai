"""KNOWLEDGE STATE — temporal + availability semantics (Contracts C/D).

Empirical basis (EXP-J/G, 20/09): outage (Qdrant down) must NOT collapse
into "no knowledge"; unknown must not collapse into false; historical
must not become current. lessons() already annotates age; this module
makes the state machine explicit and unit-testable.

States: CURRENT | HISTORICAL | SUPERSEDED | UNKNOWN | UNAVAILABLE |
UNVERIFIED.

Grounding: OBSERVED (world/tool) | RETRIEVED (index/rag) |
INFERRED (model) | UNKNOWN.

GENERAL harness property: FAILURE != EMPTY (§27); the distinction is
model-agnostic. Executable via emit + tests.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum


class KnowledgeState(str, Enum):
    CURRENT = "current"
    HISTORICAL = "historical"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    UNVERIFIED = "unverified"


class Grounding(str, Enum):
    OBSERVED = "observed"
    RETRIEVED = "retrieved"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


_CURRENT_MAX_DAYS = 7  # política; configuração por domínio onde couber


def classify_state(ts: float | None, superseded: bool = False) -> KnowledgeState:
    """Temporal state de um registro de conhecimento."""
    if superseded:
        return KnowledgeState.SUPERSEDED
    if ts is None or ts <= 0:
        return KnowledgeState.UNVERIFIED
    age_days = (time.time() - ts) / 86400.0
    if age_days <= _CURRENT_MAX_DAYS:
        return KnowledgeState.CURRENT
    return KnowledgeState.HISTORICAL


def classify_grounding(source: str | None, via_tool: bool) -> Grounding:
    """Grounding de uma claim: OBSERVED se veio de tool/world, RETRIEVED
    se de índice, INFERRED se do modelo, UNKNOWN senão."""
    if via_tool:
        return Grounding.OBSERVED
    if source and source.lower() in ("rag", "qdrant", "index", "vault"):
        return Grounding.RETRIEVED
    if source and source.lower() in ("model", "inference", "llm"):
        return Grounding.INFERRED
    return Grounding.UNKNOWN


@dataclass
class KnowledgeRecord:
    """Registro anotado — o que o runtime sabe sobre o que sabe."""
    text: str
    state: KnowledgeState = KnowledgeState.UNKNOWN
    grounding: Grounding = Grounding.UNKNOWN
    source: str = ""
    ts: float | None = None

    def to_payload(self) -> dict:
        return {"text": self.text, "state": self.state.value,
                "grounding": self.grounding.value, "source": self.source,
                "ts": self.ts}


def annotate(record: dict) -> KnowledgeRecord:
    """Anota um payload de memória/lesson/rag com state+grounding."""
    ts = None
    try:
        ts = float(record.get("ts") or 0) or None
    except (TypeError, ValueError):
        ts = None
    superseded = bool(record.get("superseded"))
    state = classify_state(ts, superseded)
    grounding = classify_grounding(record.get("source"),
                                   bool(record.get("via_tool")))
    return KnowledgeRecord(text=record.get("text", ""), state=state,
                           grounding=grounding,
                           source=record.get("source", ""), ts=ts)