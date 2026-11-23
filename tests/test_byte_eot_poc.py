"""End-Of-Token PoC: normalizacao e diferenca vs Marginalize-It."""
import importlib.util
import pathlib
from importlib.machinery import SourceFileLoader

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_loader(
    "eot", SourceFileLoader("eot", str(ROOT / "scripts/byte-eot-poc.py")))
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def test_eot_distribution_is_normalized():
    toks = {0: [104, 105], 1: [32], 2: [119, 111]}
    eot = m.end_of_token([0.5, 0.2, 0.3], toks)
    assert 0.0 < sum(eot) <= 1.0  # o restante fica no simbolo EoT
    assert all(v >= 0 for v in eot)


def test_marginalize_and_eot_differ():
    toks = {0: [104, 105], 1: [32], 2: [119, 111, 114, 108, 100]}
    p = [0.5, 0.2, 0.3]
    mig = m.marginalize_it(p, toks)
    eot = m.end_of_token(p, toks)
    assert mig != eot
    assert any(abs(a - b) > 1e-4 for a, b in zip(mig, eot))

