"""Contract for the ASRD short-segment guard (scripts/duplex-asrd.py).

Why: `seg_to_text` used to return a bare string for segments shorter than
0.4 s while its caller unpacks a tuple, so the ASRD raised
"not enough values to unpack (expected 2, got 0)", the exception was
swallowed and the segment was lost. That was the root cause of the E2E
battery reading 0/10 "sem-segmento" with the voice stack up, and it also
silently dropped any short utterance.
"""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest


def _find_scripts():
    for p in Path(__file__).resolve().parents:
        if (p / "scripts").is_dir():
            return p / "scripts"
    return None


SCRIPTS = _find_scripts()
if SCRIPTS is None:
    pytest.skip("scripts/ fora do src (sandbox Nix)", allow_module_level=True)
sys.path.insert(0, str(SCRIPTS))

_spec = importlib.util.spec_from_file_location(
    "duplex_asrd", SCRIPTS / "duplex-asrd.py")
_asrd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_asrd)


def test_short_segment_returns_the_tuple_shape():
    out = _asrd._min_segment(np.zeros(int(16000 * 0.2), dtype="float32"))
    assert out is not None
    assert isinstance(out, tuple) and len(out) == 2
    text, nsp = out
    assert text == ""
    assert isinstance(nsp, float)


def test_long_segment_is_not_short():
    out = _asrd._min_segment(np.zeros(int(16000 * 2), dtype="float32"))
    assert out is None
