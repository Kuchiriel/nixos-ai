"""O registry nunca pode prometer mais contexto do que o GGUF suporta."""
import subprocess
import sys
from pathlib import Path

NIXOS_AI = Path(__file__).resolve().parents[4]


def test_registry_ctx_never_exceeds_gguf_trained():
    r = subprocess.run(
        [sys.executable, str(NIXOS_AI / "scripts" / "check-ctx-drift.py"),
         "--quiet"],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
