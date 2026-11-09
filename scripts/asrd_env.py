#!/usr/bin/env python3
"""asrd_env.py — environment for the duplex ASRD subprocess.

PROBLEM (measured 09/11): the ASRD imports numpy from the karaok venv, whose
wheel expects the system libstdc++/libz. Without those the import dies before
the {"ready": true} line, the duplex receives no segment at all, and the E2E
voice battery reads 0/10 "sem-segmento".

The previous resolver asked nix for "nixpkgs#gcc.lib" and "nixpkgs#zlib.out".
On the current nixpkgs the first path does not resolve (the gcc package has no
"lib" output; the attribute is gcc.cc.lib), and the failure was swallowed: the
resolver returned only zlib and the ASRD survived only because the parent
process environment already carried the gcc library path. Fixing the symptom
in the parent env is not a fix; the resolver itself was the broken part.

WHAT THIS MODULE DOES
  resolve_lib_dirs(): resolves the library directories through nixpkgs
  legacyPackages (attribute paths that really exist), VERIFIES the soname is
  present in each directory, and falls back to a store search when nix is
  unavailable. A directory that does not contain the soname is dropped instead
  of being passed on as a broken path.
  missing_sonames(): what is still absent, so the caller can fail loudly.
  asrd_env(): the full environment for the subprocess.

USAGE
    import asrd_env
    env = asrd_env.asrd_env()
    subprocess.Popen([...], env=env)
"""
import glob
import os
import subprocess

# (nixpkgs attribute path, soname that must exist in <out>/lib)
_LIBS = (
    ("gcc.cc.lib", "libstdc++.so.6"),
    ("zlib", "libz.so.1"),
)

# store glob patterns used when nix is unavailable
_STORE_FALLBACK = (
    ("libstdc++.so.6", "/nix/store/*-gcc-*-lib/lib/libstdc++.so.6"),
    ("libz.so.1", "/nix/store/*-zlib-*/lib/libz.so.1"),
)


def _nix_out_path(attr_path: str, timeout: int = 120) -> str:
    """Store path of a nixpkgs attribute, or '' when it cannot be resolved.

    The expression uses legacyPackages on purpose: flake output paths cannot
    reach nested package attributes (that is exactly how "nixpkgs#gcc.lib"
    silently became a no-op).
    """
    # legacyPackages is keyed by system: the expression reads the current
    # system from nix itself (no hardcoded triple)
    expr = (
        '(builtins.getFlake "nixpkgs").legacyPackages.'
        "${builtins.currentSystem}." + attr_path + ".outPath"
    )
    try:
        r = subprocess.run(
            ["nix", "eval", "--raw", "--impure", "--expr", expr],
            capture_output=True, text=True, timeout=timeout)
    except Exception:
        return ""
    if r.returncode != 0:
        return ""
    return r.stdout.strip()


def _store_fallback(soname: str) -> str:
    """Newest store path holding the soname, used when nix cannot answer.

    The store holds several versions of the same library and the hash prefix
    sorts before the version, so plain sorting picks an arbitrary one: the
    version is parsed and the newest wins (a newer libstdc++ serves every
    older GLIBCXX symbol).
    """
    pattern = dict(_STORE_FALLBACK).get(soname)
    if not pattern:
        return ""
    hits = glob.glob(pattern)
    if not hits:
        return ""
    import re

    def _key(path):
        m = re.search(r"-(\d+)\.(\d+)\.(\d+)", path)
        ver = tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            mtime = 0
        return (ver, mtime, path)

    return os.path.dirname(max(hits, key=_key))


def resolve_lib_dirs(timeout: int = 120) -> list:
    """Directories that really contain the sonames the venv wheels need."""
    dirs = []
    for attr_path, soname in _LIBS:
        out = _nix_out_path(attr_path, timeout=timeout)
        libdir = os.path.join(out, "lib") if out else ""
        if libdir and os.path.exists(os.path.join(libdir, soname)):
            dirs.append(libdir)
            continue
        # nix did not answer (or answered a path without the soname):
        # look for the soname in the store instead of trusting the path
        fallback = _store_fallback(soname)
        if fallback:
            dirs.append(fallback)
    return dirs


def missing_sonames(dirs=None) -> list:
    """Sonames that are not reachable from the given directories."""
    dirs = resolve_lib_dirs() if dirs is None else dirs
    missing = []
    for _attr_path, soname in _LIBS:
        if not any(os.path.exists(os.path.join(d, soname)) for d in dirs):
            missing.append(soname)
    return missing


def asrd_env(base_env=None, timeout: int = 120) -> dict:
    """Environment for the ASRD subprocess: the resolved libs come first."""
    env = dict(os.environ if base_env is None else base_env)
    dirs = resolve_lib_dirs(timeout=timeout)
    if dirs:
        env["LD_LIBRARY_PATH"] = ":".join(
            dirs + [env.get("LD_LIBRARY_PATH", "")]).rstrip(":")
    return env


if __name__ == "__main__":
    dirs = resolve_lib_dirs()
    missing = missing_sonames(dirs)
    print("lib dirs:", dirs or "(none)")
    print("missing sonames:", missing or "(none)")
    raise SystemExit(1 if missing else 0)
