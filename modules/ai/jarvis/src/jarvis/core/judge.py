"""LLM-judge p/ falsidade semântica (RAGAS-style, eval e turnos críticos).

Regras estruturais (completion.py) pegam afirmação-sem-escrita e
negação-do-observado. O que escapa — paráfrase errada, número trocado,
conclusão invertida — precisa de juízo semântico. Este módulo faz UMA
chamada estrita (JSON) ao LLM com response+observations e devolve
supported/contradicted/unverifiable por claim.

Uso: scripts de eval e (futuro) turnos críticos. NUNCA no loop quente
por default (custo/latência) — a policy estrutural continua primeira.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class GroundingVerdict:
    supported: list[str] = field(default_factory=list)
    contradicted: list[str] = field(default_factory=list)
    unverifiable: list[str] = field(default_factory=list)

    @property
    def faithful(self) -> bool:
        return not self.contradicted


_JUDGE_SYS = (
    "You check factual grounding. Given RESPONSE and OBSERVATIONS "
    "(tool outputs), split RESPONSE into atomic claims and classify EACH "
    "as: supported (entailed by OBSERVATIONS), contradicted (conflicts "
    "with OBSERVATIONS), unverifiable (not present in OBSERVATIONS). "
    "Respond with ONLY JSON: "
    '{"supported": [...], "contradicted": [...], "unverifiable": [...]}. '
    "Opinions, greetings and hedges are unverifiable, never contradicted."
)


def judge_grounding(response: str, observations: list[str],
                    llm_client=None) -> GroundingVerdict:
    """Julga grounding de response contra observations (1 chamada estrita)."""
    if llm_client is None:
        from jarvis.core.config import Config
        from jarvis.providers.llm import LLMClient
        llm_client = LLMClient(Config())
    obs = "\n---\n".join(o[:1500] for o in observations if o.strip())
    if not (response or "").strip() or not obs.strip():
        return GroundingVerdict(unverifiable=[response[:200] or "(vazio)"])
    prompt = (f"RESPONSE:\n{response[:2000]}\n\nOBSERVATIONS:\n{obs[:4000]}")
    try:
        if hasattr(llm_client, "chat_full"):
            resp = llm_client.chat_full(
                [{"role": "system", "content": _JUDGE_SYS},
                 {"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=512)
            raw = resp.content if hasattr(resp, "content") else str(resp)
        else:
            raw = llm_client.chat(
                [{"role": "system", "content": _JUDGE_SYS},
                 {"role": "user", "content": prompt}],
                temperature=0.0, max_tokens=512)
            raw = raw.content if hasattr(raw, "content") else str(raw)
        data = json.loads(raw[raw.index("{"):raw.rindex("}") + 1])
        return GroundingVerdict(
            supported=[str(x) for x in data.get("supported", [])],
            contradicted=[str(x) for x in data.get("contradicted", [])],
            unverifiable=[str(x) for x in data.get("unverifiable", [])])
    except Exception as e:
        return GroundingVerdict(unverifiable=[f"judge-falhou: {e}"])
