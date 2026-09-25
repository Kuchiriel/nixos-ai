"""Arquivar-antes-de-remover com verificação da cópia (25/09).

Por que este módulo existe — ele é a resposta a um erro meu, não uma
abstração para elegantismo:

  Eu arquivei 6 pontos numa coleção nova, o Qdrant **aceitou o upsert
  (HTTP 200) e não gravou nada** (coleção ainda inicializando,
  points_count=0), e eu deletei da coleção viva mesmo assim. Resultado:
  6 pontos perdidos sem backup verificado — um deles era uma memória
  real. A regra "nunca apagar" que eu tinha escrito no AGENTS.md não
  protegia nada porque era prosa, não mecanismo.

Aprendizado da literatura que dá o desenho: "archive first, delete
second" e "use unique resource names **instead of** cleanup" — mas
limpeza sempre exige *verificação*, porque o custo de confiar num
status de escrita que mente é perda irrecuperável.

O que este helper garante, mecanicamente:
  1. **Copia** os pontos para a coleção de arquivo (payload + vetor).
  2. **Lê de volta** e confere: contagem E hash do payload de cada
     ponto. Se qualquer um divergir, ABORTA e não remove nada.
  3. Só então **remove** da origem, e reporta o que removeu.
  4. Aceita **IDs explícitos**, nunca filtro por substring: o erro
     original foi um filtro que casou com uma memória que apenas
     *citava* o termo procurado ("E2E test fact" aparecia no texto
     dela, que era uma memória real). A seleção fica com quem decide
     remover; a execução só obedece IDs.
  5. `dry_run=True` (padrão) não escreve nada.

Regra: se a verificação falhar, o resultado é `verified=False` e a
origem fica intacta. Falhar barato é o ponto.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Protocol


class _PointsStore(Protocol):
    """Só o que este módulo precisa — qualquer store serve nos testes."""

    def get_points(self, collection: str, ids: list[Any]) -> list[dict[str, Any]]: ...
    def upsert(self, collection: str, points: list[dict[str, Any]]) -> None: ...
    def delete_points(self, collection: str, ids: list[Any]) -> None: ...
    def count(self, collection: str) -> int: ...


@dataclass
class ArchiveResult:
    requested: int = 0
    archived: int = 0
    verified: bool = False
    removed: int = 0
    reason: str = ""
    mismatches: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        """Só é seguro decir 'removido' se a cópia foi verificada."""
        return self.verified and self.removed == self.requested

    def as_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested, "archived": self.archived,
            "verified": self.verified, "removed": self.removed,
            "reason": self.reason, "mismatches": self.mismatches,
            "safe": self.safe,
        }


def payload_hash(payload: dict[str, Any] | None) -> str:
    """Hash estável do payload, insensível à ordem das chaves."""
    import json

    return hashlib.sha256(
        json.dumps(payload or {}, sort_keys=True, ensure_ascii=False,
                   default=str).encode("utf-8")
    ).hexdigest()


def archive_then_delete(
    store: _PointsStore,
    source: str,
    target: str,
    ids: list[Any],
    *,
    dry_run: bool = True,
    provenance: dict[str, Any] | None = None,
) -> ArchiveResult:
    """Copia `ids` de `source` para `target`, VERIFICA, e só então remove.

    Ordem deliberada e não negociável: copiar → ler de volta → conferir
    → remover. Inverter qualquer passo transforma arquivamento em perda.
    """
    res = ArchiveResult(requested=len(ids))
    if not ids:
        res.reason = "nada_a_fazer"
        res.verified = True
        return res

    pontos = store.get_points(source, list(ids))
    if len(pontos) != len(ids):
        res.reason = f"fonte_devolveu_{len(pontos)}_de_{len(ids)}"
        return res  # NÃO remove: nem tudo foi lido

    if dry_run:
        res.reason = "dry_run"
        res.archived = len(pontos)
        res.verified = True
        return res

    prov = dict(provenance or {})
    stamped = []
    for p in pontos:
        pl = dict(p.get("payload") or {})
        pl["_archived_from"] = source
        pl.update(prov)
        stamped.append({"id": p["id"], "vector": p.get("vector"), "payload": pl})

    try:
        store.upsert(target, stamped)
    except Exception as exc:  # noqa: BLE001
        res.reason = f"falha_escrita:{type(exc).__name__}"
        return res

    # ── a verificação que faltava no erro original ────────────────────
    de_volta = store.get_points(target, list(ids))
    if len(de_volta) != len(pontos):
        res.reason = f"copia_incompleta:{len(de_volta)}_de_{len(pontos)}"
        res.archived = len(de_volta)
        return res  # origem intacta

    for original, copiado in zip(pontos, de_volta):
        if original["id"] != copiado["id"]:
            res.mismatches.append(f"id:{original['id']}!={copiado['id']}")
        pl_orig = dict(original.get("payload") or {})
        pl_cop = dict(copiado.get("payload") or {})
        for k in ("_archived_from", *prov.keys()):
            pl_cop.pop(k, None)
        if payload_hash(pl_orig) != payload_hash(pl_cop):
            res.mismatches.append(f"payload:{original['id']}")
    if res.mismatches:
        res.reason = "divergencia_na_copia"
        return res  # NÃO remove: a cópia não é fiel

    res.archived = len(de_volta)
    res.verified = True
    try:
        store.delete_points(source, list(ids))
        res.removed = len(ids)
        res.reason = "ok"
    except Exception as exc:  # noqa: BLE001
        res.reason = f"falha_remocao:{type(exc).__name__}"
    return res
