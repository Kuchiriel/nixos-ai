"""Harness do judge (scripts/eval-judge.py) em modo offline: 10/10."""
from importlib.machinery import SourceFileLoader
from pathlib import Path


def _load():
    p = Path(__file__).resolve().parents[4] / "scripts" / "eval-judge.py"
    return SourceFileLoader("eval_judge", str(p)).load_module()


def test_judge_harness_selfcheck() -> None:
    mod = _load()
    assert len(mod.CASES) >= 8
    passed, rows = mod.run(lambda c: mod._ScriptedClient(mod._verdict_for(c)))
    assert passed == len(mod.CASES), rows
    assert all(r["pass"] for r in rows)
