"""Estagios do modelo do zero: forma + gradiente em cada camada."""
import importlib.util
import pathlib
from importlib.machinery import SourceFileLoader

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_loader(
    "zero_model", SourceFileLoader("zero_model", str(ROOT / "scripts/zero_model.py")))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_perceptron():
    r = m.check("perceptron")
    assert r["shape"] == [4, 4] and r["grad_norm"] > 0


def test_attention():
    r = m.check("attention")
    assert r["shape"] == [2, 7, 16] and r["grad_norm"] > 0


def test_transformer():
    r = m.check("transformer")
    assert r["shape"] == [2, 32, 65] and 0 < r["loss"] < 10
    assert r["params"] > 100000
