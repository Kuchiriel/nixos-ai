"""Contract for scripts/asrd_env.py (the ASRD subprocess environment).

Why this exists: the ASRD imports numpy from the karaok venv, whose wheel
expects the system libstdc++/libz. Without them the process dies before the
{"ready": true} line and the voice battery reads 0/10 "sem-segmento". The
resolver that used to live inline asked nix for "nixpkgs#gcc.lib", a path
that does not exist on the current nixpkgs (the attribute is gcc.cc.lib), and
the failure was swallowed: the ASRD only survived because the parent
environment already carried the library path.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import asrd_env  # noqa: E402


def test_resolve_returns_dirs_that_hold_the_sonames():
    dirs = asrd_env.resolve_lib_dirs()
    # the store is present on this host; skip elsewhere instead of failing
    if not dirs:
        pytest.skip("no nix store / no library dirs resolved here")
    for soname in ("libstdc++.so.6", "libz.so.1"):
        assert any(os.path.exists(os.path.join(d, soname)) for d in dirs), \
            f"{soname} not reachable from {dirs}"


def test_missing_sonames_is_empty_when_resolution_worked():
    dirs = asrd_env.resolve_lib_dirs()
    if not dirs:
        pytest.skip("no library dirs resolved here")
    assert asrd_env.missing_sonames(dirs) == []


def test_nix_expression_uses_legacy_packages_and_current_system(monkeypatch):
    """A flake output path cannot reach nested attributes: that was the bug."""
    seen = {}

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="/nix/store/x-lib\n", stderr="")

    monkeypatch.setattr(asrd_env.subprocess, "run", _fake_run)
    assert asrd_env._nix_out_path("gcc.cc.lib") == "/nix/store/x-lib"
    expr = seen["cmd"][-1]
    assert "legacyPackages" in expr
    assert "${builtins.currentSystem}" in expr
    assert "gcc.cc.lib" in expr
    # the broken form (output path of a non-existent output) must not come back
    assert "nixpkgs#gcc.lib" not in expr


def test_store_fallback_picks_the_newest_version(monkeypatch, tmp_path):
    """Plain sorting picks an arbitrary version (the hash sorts first)."""
    for ver in ("14.3.0", "15.3.0", "16.2.0"):
        lib = tmp_path / f"aaa-gcc-{ver}-lib" / "lib"
        lib.mkdir(parents=True)
        (lib / "libstdc++.so.6").write_text("x")
    monkeypatch.setattr(asrd_env, "_STORE_FALLBACK", (
        ("libstdc++.so.6", str(tmp_path / "*-gcc-*-lib/lib/libstdc++.so.6")),
    ))
    picked = asrd_env._store_fallback("libstdc++.so.6")
    assert "16.2.0" in picked, picked


def test_asrd_env_prepends_the_resolved_dirs(monkeypatch):
    monkeypatch.setattr(asrd_env, "resolve_lib_dirs", lambda *a, **k: ["/nix/store/a/lib"])
    env = asrd_env.asrd_env(base_env={"LD_LIBRARY_PATH": "/existing"})
    assert env["LD_LIBRARY_PATH"].startswith("/nix/store/a/lib:")
    assert env["LD_LIBRARY_PATH"].endswith("/existing")
