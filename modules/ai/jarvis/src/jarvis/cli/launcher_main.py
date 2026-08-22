"""jarvis launcher — GUI para todas as features do NixOS-AI.

Wrapper Python que chama o script bash launcher.sh com Yad.
"""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Executa o launcher GUI."""
    script = Path(__file__).parent / "launcher.sh"
    if not script.exists():
        print(f"ERROR: launcher.sh não encontrado: {script}", file=sys.stderr)
        return 1

    try:
        result = subprocess.run(
            [str(script)] + sys.argv[1:],
            timeout=300,
        )
        return result.returncode
    except FileNotFoundError:
        print("ERROR: yad não encontrado. Instale com: nix-env -iA nixpkgs.yad", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        return 0
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
