"""Detecção de consolidação de memória (25/09) — camada Reflection→Experience.

Por que existe: o `MemoryVault.summarize()` já faz *Reflection* (eventos →
resumo no vault), mas não faz as três operações que a literatura de 2026
aponta como o mecanismo central da consolidação:

  - **merge**: entradas que dizem a mesma coisa (Mem0/A-MEM);
  - **supersede**: entrada nova que CONTRADIZ uma antiga — sem isso a
    memória acumula versões e o agente passa a citar a velha (o modo de
    falha mais caro, porque a memória errada é indistinguível da certa);
  - **heat**: frequência de acesso × recência, para promover o que é
    usado e esfriar o que é obsoleto (MemoryOS) — em vez de acumular
    igual para sempre.

REGRA DA CASA: isto é **READ-ONLY por padrão**. Ele *detecta* e relata;
não apaga, não reescreve, não muta nada. A regra do dono é "nunca
apagar" e Supersedição no Qdrant é mutação de dado vivo. Aplicar exige
`--apply` explícito e ainda assim apenas marca (`superseded_by`), nunca
deleta — o registro original continua legível para auditoria.

Superfície de similaridade: usa o mesmo `memories` collection e compara
por cosseno dos vetores densos que o Qdrant já guarda. Sem LLM: a
detecção é mecânica e reprodutível, então o veredito não é opinião do
modelo (mesma doutrina do memory-arena-lite).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any

# Limiares: conservador de propósito. Falso positivo numa consolidação
# custa mais que uma duplicata esquecida (perde-se um fato; ganha-se um
# fato que o agente pode citar errado).
DUP_COSINE = 0.92      # quase idêntico
SUPERSEDE_COSINE = 0.78  # mesmo assunto, possível contradição
HOT_WINDOW_DAYS = 7.0


@dataclass
class Finding:
    kind: str                      # "duplicate" | "supersede" | "cold"
    newer_id: str
    older_id: str
    score: float
    preview: str
    detail: str = ""


@dataclass
class Report:
    scanned: int = 0
    findings: list[Finding] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "duplicate": len(self.by_kind("duplicate")),
            "supersede": len(self.by_kind("supersede")),
            "cold": len(self.by_kind("cold")),
            "findings": [
                {"kind": f.kind, "newer": f.newer_id, "older": f.older_id,
                 "score": round(f.score, 4), "preview": f.preview, "detail": f.detail}
                for f in self.findings
            ],
        }


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def heat(access_count: int, ts: float, *, now: float | None = None,
         half_life_days: float = HOT_WINDOW_DAYS) -> float:
    """Calor = frequência × decaimento exponencial pela recência.

    Não é "importância": é o sinal de que a literatura usa para decidir o
    que fica em cache (MemoryOS usa frequência de acesso × recência).
    Mantém o escopo honesto — calor não é valor, é atividade.
    """
    now = time.time() if now is None else now
    age_days = max(0.0, (now - float(ts or 0)) / 86400.0)
    decay = 0.5 ** (age_days / half_life_days)
    return (1.0 + math.log1p(max(0, access_count))) * decay


def _text(ev: dict[str, Any]) -> str:
    return str(ev.get("text", "") or "").strip()


def apply(report, store, collection: str, *, dry_run: bool = True) -> dict:
    """(26/09, LOOP-v3 — fila #1) Aplica o veredito do detect(): marca o
    ponto ANTIGO de cada duplicate/supersede com `superseded_by` + `ts`.

    NUNCA deleta (regra #1 da casa): quem filta é o recall. dry_run
    default True — casa: comece sempre em dry_run. Read-modify-write via
    get_points+upsert (o store não tem set_payload; o vetor preserva).
    """
    import time as _t
    targets = {}
    for f in getattr(report, "findings", []):
        if f.kind not in ("duplicate", "supersede"):
            continue
        targets.setdefault(str(f.older_id), str(f.newer_id))
    if not targets:
        return {"dry_run": dry_run, "marked": 0, "ids": []}
    ids = [int(i) for i in targets.keys() if str(i).lstrip("-").isdigit()]
    pts = store.get_points(collection, ids)
    marked = []
    now = _t.time()
    for p in pts:
        pid = str(p.get("id"))
        if pid not in targets:
            continue
        payload = dict(p.get("payload") or {})  # copia: nunca mutar objeto do store
        payload["superseded"] = True
        payload["superseded_by"] = int(targets[pid])
        payload["superseded_ts"] = now
        marked.append({"id": p["id"], "vector": p.get("vector"),
                       "payload": payload})
    if dry_run:
        return {"dry_run": True, "marked": len(marked),
                "ids": [str(m["id"]) for m in marked]}
    if marked:
        store.upsert(collection, marked)
    return {"dry_run": False, "marked": len(marked),
            "ids": [str(m["id"]) for m in marked]}


def detect(events: list[dict[str, Any]], vectors: dict[str, list[float]] | None = None,
           *, now: float | None = None, access: dict[str, int] | None = None) -> Report:
    """Analisa eventos e devolve o que CONSOLIDARIA (sem aplicar nada).

    `vectors` é opcional: sem vetores, só o achado `cold` sai (e a razão
    fica explícita em vez de o sistema fingir que comparou).
    """
    rep = Report(scanned=len(events))
    access = access or {}
    evs = sorted(events, key=lambda e: float(e.get("ts", 0) or 0))

    if not vectors:
        for e in evs:
            if heat(access.get(str(e.get("id")), 0), e.get("ts", 0), now=now) < 0.5:
                rep.findings.append(Finding(
                    "cold", str(e.get("id")), str(e.get("id")), 0.0,
                    _text(e)[:90], "sem vetor: só calor avaliado"))
        return rep

    for i, newer in enumerate(evs):
        nv = vectors.get(str(newer.get("id")))
        if not nv:
            continue
        for older in evs[:i]:                      # só compara com o mais antigo
            ov = vectors.get(str(older.get("id")))
            if not ov:
                continue
            c = cosine(nv, ov)
            if c >= DUP_COSINE:
                rep.findings.append(Finding(
                    "duplicate", str(newer.get("id")), str(older.get("id")), c,
                    _text(newer)[:90], "quase idêntico; mantém o mais recente"))
            elif c >= SUPERSEDE_COSINE:
                rep.findings.append(Finding(
                    "supersede", str(newer.get("id")), str(older.get("id")), c,
                    _text(newer)[:90], "mesmo assunto, texto diferente: VERIFICAR contradição"))
    return rep
