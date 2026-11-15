"""playbook.py — as regras de CONDUCAO por papel (portadas do legado).

(15/11, crouton-alpha) O legado tinha `team/roles/*.md` (Pode ver e fazer /
Nao pode / Entrega / Handoff). O sistema novo tinha persona + MBTI, mas nao
as regras do papel. Este loader expoe:

  * playbook_for_kind(kind)  -> o playbook do TIPO de tarefa (dev, pesquisa,
    auditoria) — usado no spawn;
  * playbook_for_agent(agent) -> o playbook do AGENTE (pela lane/contexto) —
    usado no wake.

O texto e cacheado (o arquivo e pequeno e lido muitas vezes).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PLAYBOOK_DIR = Path(__file__).resolve().parents[1] / "playbooks"

# tipo de tarefa -> arquivo do playbook (o legado: dev / researcher / auditor)
POR_KIND = {
    "dev": "dev.md",
    "code": "dev.md",
    "backend": "dev.md",
    "frontend": "dev.md",
    "bugfix": "dev.md",
    "refactor": "dev.md",
    "test": "dev.md",
    "research": "researcher.md",
    "pesquisa": "researcher.md",
    "search": "researcher.md",
    "doc": "researcher.md",
    "docs": "researcher.md",
    "audit": "auditor.md",
    "review": "auditor.md",
    "seguranca": "auditor.md",
    "redteam": "auditor.md",
}

# palavras da lane/contexto -> papel (quando o kind nao diz)
POR_LANE = {
    "redteam": "auditor.md",
    "audit": "auditor.md",
    "security": "auditor.md",
    "research": "researcher.md",
    "doc": "researcher.md",
    "dev": "dev.md",
    "build": "dev.md",
    "code": "dev.md",
}


@lru_cache(maxsize=32)
def _ler(nome: str) -> str:
    p = PLAYBOOK_DIR / nome
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def playbook_for_kind(kind: str) -> str:
    """O playbook do tipo de tarefa (vazio se nao houver)."""
    if not kind:
        return ""
    nome = POR_KIND.get(str(kind).strip().lower())
    if not nome:
        # matching por prefixo (o classify pode devolver "dev/fix")
        k = str(kind).strip().lower()
        for chave, arq in POR_KIND.items():
            if k.startswith(chave):
                nome = arq
                break
    return _ler(nome) if nome else ""


def playbook_for_agent(agent: dict) -> str:
    """O playbook do agente: pela lane, pelo contexto ou pelo nome do papel."""
    if not isinstance(agent, dict):
        return ""
    for campo in ("lane", "context", "role", "papel", "name"):
        valor = str(agent.get(campo) or "").lower()
        for chave, arq in POR_LANE.items():
            if chave in valor:
                texto = _ler(arq)
                if texto:
                    return texto
    return ""


def tem_playbook(agente: dict) -> bool:
    return bool(playbook_for_agent(agente))
