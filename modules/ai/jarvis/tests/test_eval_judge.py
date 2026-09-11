"""Harness do judge (scripts/eval-judge.py) em modo offline: 10/10."""
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration  # scripts/ fora do src do pacote Nix


def _load():
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        cand = parent / "scripts" / "eval-judge.py"
        if cand.exists():
            return SourceFileLoader("eval_judge", str(cand)).load_module()
    raise FileNotFoundError("scripts/eval-judge.py não encontrado subindo de " + str(here))


def test_judge_harness_selfcheck() -> None:
    mod = _load()
    assert len(mod.CASES) >= 8
    passed, rows = mod.run(lambda c: mod._ScriptedClient(mod._verdict_for(c)))
    assert passed == len(mod.CASES), rows
    assert all(r["pass"] for r in rows)
