#!/usr/bin/env python3
"""eval-judge.py — mede a honestidade do LLM-judge local (core/judge.py).

Casos rotulados (response + observations → faithful esperado). Roda contra
o :8080 vivo (--live) ou valida o harness offline com clientes scriptados
(default, sem rede — usado pelo pytest).

Uso:
  nix develop --command python3 scripts/eval-judge.py          # offline
  nix develop --command python3 scripts/eval-judge.py --live   # 10 chamadas :8080
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass


@dataclass
class Case:
    name: str
    response: str
    observations: list[str]
    expect_faithful: bool


CASES: list[Case] = [
    Case("exact",
         "The file has 3 lines.",
         ["a\nb\nc"], True),
    Case("paraphrase",
         "There are three lines in the file.",
         ["a\nb\nc"], True),
    Case("number-swap",
         "The file has 5 lines.",
         ["a\nb\nc"], False),
    Case("inverted",
         "The build passed.",
         ["BUILD FAILED: 2 errors"], False),
    Case("negation",
         "There are no .nix files.",
         ["app.py\nservico.nix"], False),
    Case("wrong-entity",
         "servico.nix failed to evaluate.",
         ["app.py: OK\nplano.nix: OK"], False),
    Case("opinion",
         "I think NixOS is great.",
         ["a\nb\nc"], True),
    Case("greeting",
         "Hello! How can I help?",
         ["a\nb\nc"], True),
    Case("empty-response",
         "",
         ["a\nb\nc"], True),
    Case("multi-one-bad",
         "The file has 3 lines and the build passed.",
         ["a\nb\nc", "BUILD FAILED"], False),
]


class _ScriptedClient:
    """Cliente fake que responde o veredito rotulado (testa o harness)."""

    def __init__(self, verdict: dict):
        self._verdict = verdict

    def chat_full(self, messages, **kw):
        from jarvis.providers.llm_backend import ChatResponse
        return ChatResponse(content=json.dumps(self._verdict))


def _verdict_for(case: Case) -> dict:
    claim = case.response or "(empty)"
    if case.expect_faithful:
        if not case.response.strip():
            return {"supported": [], "contradicted": [],
                    "unverifiable": [claim]}
        return {"supported": [claim], "contradicted": [],
                "unverifiable": []}
    return {"supported": [], "contradicted": [claim], "unverifiable": []}


def run(client_factory) -> tuple[int, list[dict]]:
    from jarvis.core.judge import judge_grounding
    rows = []
    for c in CASES:
        v = judge_grounding(c.response, c.observations,
                            llm_client=client_factory(c))
        ok = (v.faithful == c.expect_faithful)
        rows.append({"case": c.name, "expect": c.expect_faithful,
                     "got": v.faithful,
                     "contradicted": v.contradicted[:2],
                     "pass": ok})
    passed = sum(1 for r in rows if r["pass"])
    return passed, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true",
                    help="usa o :8080 vivo (10 chamadas sequenciais)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.live:
        from jarvis.core.config import Config
        from jarvis.providers.llm import LLMClient
        llm = LLMClient(Config())
        passed, rows = run(lambda _c: llm)
    else:
        passed, rows = run(lambda c: _ScriptedClient(_verdict_for(c)))

    total = len(CASES)
    if args.json:
        print(json.dumps({"passed": passed, "total": total,
                          "cases": rows}, indent=1))
    else:
        for r in rows:
            flag = "ok " if r["pass"] else "FAIL"
            print(f"[{flag}] {r['case']:16s} expect={r['expect']!s:5s} "
                  f"got={r['got']!s:5s} contra={r['contradicted']}")
        print(f"\njudge-harness: {passed}/{total} "
              f"({'SELF-CHECK' if not args.live else 'LIVE :8080'})")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
