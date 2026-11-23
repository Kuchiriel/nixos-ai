"""O codigo gerado para o subprocesso de decode deve ser Python valido."""
import importlib.util
import pathlib
from importlib.machinery import SourceFileLoader

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_loader(
    "kdecode", SourceFileLoader("kdecode", str(ROOT / "benchmarks/littlebit2/kaggle-official/script.py")))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_generated_decode_code_compiles():
    code = m.decode_latency_code("/tmp/checkpoint com espaco", 16, 128)
    compile(code, "<decode>", "exec")
    assert "path='/tmp/checkpoint com espaco'" in code
    assert "warmup=16" in code
    assert "tokens=128" in code
    assert "json.dumps(" in code  # serializa a medicao para o parser

