"""Tests for the read-only pre-flight (persona `dev` deliverable).

The pre-flight only READS the contract state: the two public getters plus
the two flags that also make a transfer revert. It must never call an
owner-only function as a holder, never ask for a key, and never touch the
network.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PACK = Path(__file__).resolve().parents[1]
if str(PACK) not in sys.path:
    sys.path.insert(0, str(PACK))

from mock_usdt import USDTLike  # noqa: E402

OWNER = "0x0000000000000000000000000000000000000WNR"
WALLET = "0x000000000000000000000000000000000000dEAD"
USER = "0x0000000000000000000000000000000000000001"
CLEAN = "0x000000000000000000000000000000000000C0DE"
RECIPIENT = "0x000000000000000000000000000000000000BEEF"


def _preflight():
    spec = importlib.util.spec_from_file_location(
        "frozen_usdt_preflight", PACK / "frozen_usdt_preflight.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["frozen_usdt_preflight"] = mod
    spec.loader.exec_module(mod)
    return mod


def _token() -> USDTLike:
    t = USDTLike(owner=OWNER, initial_supply=10000)
    t.balances[WALLET] = 10000
    t.addBlackList(WALLET, OWNER)
    return t


def test_flags_the_frozen_wallet_before_any_transfer() -> None:
    mod = _preflight()
    report = mod.check_transfer(_token(), WALLET, RECIPIENT)
    assert report["would_revert"] is True
    assert "blacklisted sender" in report["revert_reasons"]
    assert report["getBlackListStatus_sender"] is True


def test_flags_a_blacklisted_recipient() -> None:
    mod = _preflight()
    report = mod.check_transfer(_token(), CLEAN, WALLET)
    assert report["would_revert"] is True
    assert "blacklisted receiver" in report["revert_reasons"]


def test_clear_sender_and_recipient_pass_the_check() -> None:
    mod = _preflight()
    report = mod.check_transfer(_token(), CLEAN, RECIPIENT)
    assert report["would_revert"] is False
    assert report["revert_reasons"] == []


def test_paused_token_is_also_blocked() -> None:
    mod = _preflight()
    t = _token()
    t.pause(OWNER)
    report = mod.check_transfer(t, CLEAN, RECIPIENT)
    assert report["would_revert"] is True
    assert "paused" in report["revert_reasons"]


def test_cli_example_flags_the_scenario_wallet() -> None:
    """The documented example: the frozen wallet of the scenario is flagged."""
    mod = _preflight()
    rc = mod.main(["--json"])
    assert rc == 1
    out = mod.main(["--json"])  # idempotent, read-only


def test_preflight_makes_no_owner_call_as_holder() -> None:
    """The check must not clear the freeze, even by accident."""
    mod = _preflight()
    t = _token()
    before = t.getBlackListStatus(WALLET)
    mod.check_transfer(t, WALLET, RECIPIENT)
    assert t.getBlackListStatus(WALLET) == before is True


def test_no_secret_material_in_the_source() -> None:
    """No secret MATERIAL: the same rule the house checker applies.

    The naive substring "private key" is not a violation: the docstring says
    the script does NOT ask for one. The house rule (checker.SECRET_PATTERNS)
    is a secret followed by ':' or '=' and a value, plus raw 32-byte hex.
    """
    import re

    src = (PACK / "frozen_usdt_preflight.py").read_text(encoding="utf-8")
    patterns = (
        re.compile(r"0x[0-9a-fA-F]{64}"),                      # raw private key
        re.compile(r"(?i)\b(seed\s*phrase|private\s*key)\s*[:=]\s*\S+"),
        re.compile(r"(?i)mnemonic\s*[:=]\s*[a-z ]{12,}"),
    )
    assert not [p.pattern for p in patterns if p.search(src)]
    # the only owner-only call allowed is the SETUP of the initial state
    assert src.count("addBlackList") == 1
    # removeBlackList may appear in the prose (it is the documented clearing
    # route) but NEVER as a CALL in executable code: strip comments and
    # docstrings before looking for the call.
    code = "\n".join(
        line for line in src.splitlines()
        if not line.lstrip().startswith("#")
    )
    code = re.sub(r'""".*?"""', "", code, flags=re.S)
    # a CALL would look like `token.removeBlackList(`; the string in the
    # report ("removeBlackList(address, caller)") is documentation, not code.
    assert ".removeBlackList(" not in code
    assert ".destroyBlackFunds(" not in code
