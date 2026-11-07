"""O registry nunca pode prometer mais contexto do que o GGUF suporta."""
import subprocess
import sys
from pathlib import Path

import pytest

# O teste precisa do RAIZ do repo nixos-ai (roda scripts/check-ctx-drift.py).
# No build Nix o pacote vive em <store>/ (o src é só ./jarvis) → o caminho
# relativo não existe e parents[4] levanta IndexError na COLETA (medido
# 07/11: o build do jarvis quebrava no installCheck). Aqui o teste PULA
# fora do repo; em nix develop (documentado no package.nix) ele roda.
_HERE = Path(__file__).resolve()
NIXOS_AI = _HERE.parents[4] if len(_HERE.parents) > 4 else None


@pytest.mark.skipif(
    NIXOS_AI is None or not (NIXOS_AI / "flake.nix").is_file(),
    reason="fora do repo nixos-ai (build Nix) — rode em nix develop",
)
def test_registry_ctx_never_exceeds_gguf_trained():
    r = subprocess.run(
        [sys.executable, str(NIXOS_AI / "scripts" / "check-ctx-drift.py"),
         "--quiet"],
        capture_output=True, text=True)
    assert r.returncode == 0, (r.stdout or "") + (r.stderr or "")
