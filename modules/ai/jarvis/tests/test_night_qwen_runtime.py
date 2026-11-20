"""Runtime contract for the nightly default-model benchmark script."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


def _find_script() -> Path | None:
    """Find the benchmark script in a source checkout."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "benchmarks/model-tiers/night-qwen.sh"
        if candidate.is_file():
            return candidate
    return None


SCRIPT = _find_script()
pytestmark = pytest.mark.skipif(
    SCRIPT is None,
    reason="benchmarks/model-tiers/night-qwen.sh not found in this checkout",
)


def _default_port() -> str:
    """Read the default endpoint port from the canonical registry helper."""
    registry = SCRIPT.parents[2] / "scripts/jarvis-registry.sh"
    result = subprocess.run(
        ["bash", "-c", '. "$1"; reg_endpoint "$(reg_default)"', "_", str(registry)],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip().rsplit(":", 1)[-1]


def _fake_commands(tmp_path: Path, router_load_state: str, listen_port: str) -> Path:
    """Create deterministic stand-ins for runtime inspection commands."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo_log = tmp_path / "sudo.log"

    (bin_dir / "curl").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "sudo").write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> '{sudo_log}'\nexit 99\n")
    (bin_dir / "systemctl").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "show" ] && [ "$3" = "LoadState" ]; then\n'
        f"  printf '%s\\n' '{router_load_state}'\n"
        "  exit 0\n"
        "fi\n"
        'if [ "$1" = "show" ] && [ "$3" = "MainPID" ]; then\n'
        "  printf '4242\\n'\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n"
    )
    (bin_dir / "ss").write_text(
        "#!/bin/sh\n"
        "printf 'LISTEN 0 4096 127.0.0.1:%s 0.0.0.0:* "
        'users:(("llama-server",pid=4242,fd=7))\\n\' "$FAKE_LISTEN_PORT"\n'
    )
    for command in ("curl", "sudo", "systemctl", "ss"):
        path = bin_dir / command
        path.chmod(0o755)
    return sudo_log


@pytest.mark.parametrize(
    ("router_load_state", "expected_managed"),
    (("not-found", 0), ("loaded", 1)),
)
def test_check_only_detects_router_topology_without_touching_services(
    tmp_path: Path,
    router_load_state: str,
    expected_managed: int,
) -> None:
    listen_port = _default_port()
    sudo_log = _fake_commands(tmp_path, router_load_state, listen_port)
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env["PATH"] = f"{tmp_path / 'bin'}:{env['PATH']}"
    env["FAKE_LISTEN_PORT"] = listen_port

    result = subprocess.run(
        ["bash", str(SCRIPT), "--check-only"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert "check-only OK" in result.stdout
    assert f"managed={expected_managed}" in result.stdout
    assert not sudo_log.exists() or sudo_log.read_text() == ""
