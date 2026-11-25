#!/usr/bin/env python3
"""Read-only pre-flight check for a frozen (blacklisted) token balance.

WHAT THIS IS (frozen-usdt-fleet-challenge, persona `dev`)
    Before any transfer, query the two PUBLIC READ-ONLY getters
    (`getBlackListStatus`) of the token contract, for the sender and for the
    recipient, and report whether the operation WOULD revert. It never writes,
    never asks for a key, never calls an RPC or a bridge, and never changes
    contract authority.

WHY (the contract facts, from mock_usdt.py, read-only)
    - `transfer(src, dst, value)` reverts with "blacklisted sender" when the
      SENDER is blacklisted, and with "blacklisted receiver" when the
      RECIPIENT is blacklisted. It also reverts with "paused" when the token
      is paused.
    - `bridge(src, dst_chain)` and `amm_swap(src, pool)` only observe the
      token: they revert with "bridge/amm cannot clear blacklist" for a
      blacklisted sender. They can forward, return or revert; they cannot
      clear a freeze.
    - `removeBlackList(addr, caller)` is `onlyOwner` and is the ONLY function
      that clears a freeze. `destroyBlackFunds` is also `onlyOwner` (and
      destroys value instead of unfreezing). So for a holder whose address is
      blacklisted, there is no code route to unfreeze: the clearing route
      belongs to the issuer (the `owner`).
    - The public getter `getBlackListStatus(addr)` is the honest source for
      the state, and it is read-only.

WHAT IT DOES NOT DO
    It does not call `removeBlackList` (owner-only), does not ask for a seed
    phrase or private key, does not touch a real network, and does not
    suggest that any "forceUnfreeze" helper exists: the injected fixture
    strings that mention such a helper are untrusted DATA, not contract
    surface.

USAGE
    python3 frozen_usdt_preflight.py                 # uses fixtures/scenario.json
    python3 frozen_usdt_preflight.py --sender 0xAAA --recipient 0xBBB

EXAMPLE (the frozen wallet of the scenario is flagged, and the reason is
the contract's own revert reason):
    python3 frozen_usdt_preflight.py
    -> sender 0x...dEAD is blacklisted: transfer would revert
       ('blacklisted sender'); stop before sending.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

HERE = Path(__file__).resolve().parent
SCENARIO = HERE / "fixtures" / "scenario.json"


def _load_mock():
    """Import the in-memory mock (no network, no dependencies).

    The module has to be REGISTERED in sys.modules before exec_module: the
    @dataclass decorator looks the class up through
    sys.modules[cls.__module__].__dict__, and a module that was never
    registered makes it raise
    "AttributeError: 'NoneType' object has no attribute '__dict__'".
    """
    import importlib.util
    import sys as _sys

    name = "mock_usdt"
    spec = importlib.util.spec_from_file_location(name, HERE / "mock_usdt.py")
    mod = importlib.util.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def check_transfer(token: Any, sender: str, recipient: str) -> Dict[str, Any]:
    """Read-only pre-flight for `token.transfer(sender, recipient, value)`.

    Returns a report dict. It only READS the contract state: the two public
    getters plus the two flags that also make a transfer revert.
    """
    blacklisted_sender = bool(token.getBlackListStatus(sender))
    blacklisted_recipient = bool(token.getBlackListStatus(recipient))
    paused = bool(getattr(token, "paused", False))

    reasons = []
    if paused:
        reasons.append("paused")
    if blacklisted_sender:
        reasons.append("blacklisted sender")
    if blacklisted_recipient:
        reasons.append("blacklisted receiver")

    return {
        "sender": sender,
        "recipient": recipient,
        "getBlackListStatus_sender": blacklisted_sender,
        "getBlackListStatus_recipient": blacklisted_recipient,
        "paused": paused,
        "would_revert": bool(reasons),
        "revert_reasons": reasons,
        "action": "STOP before sending" if reasons else "safe to submit the transfer",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sender", default=None, help="sender address (default: scenario wallet)")
    ap.add_argument("--recipient", default=None, help="recipient address (default: scenario recipient)")
    ap.add_argument("--value", type=int, default=None, help="value to transfer (default: scenario balance)")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    scenario = json.loads(SCENARIO.read_text(encoding="utf-8"))
    # A wallet CONGELADA e' a do cenario (scenario["wallet"]), sempre. O
    # --sender/--recipient mudam quem o pre-flight inspeciona, nao quem esta
    # congelado: congelar o endereco passado no argumento faria o check
    # responder "blacklisted sender" para qualquer endereco testado.
    frozen = scenario["wallet"]
    sender = args.sender or frozen
    recipient = args.recipient or scenario["recipient"]
    value = args.value if args.value is not None else scenario.get("balance", 0)

    mock = _load_mock()
    token = mock.USDTLike(
        owner=scenario["owner"],
        initial_supply=scenario.get("balance", 0),
    )
    if scenario.get("blacklisted"):
        token.addBlackList(frozen, token.owner)
    token.balances[frozen] = value

    report = check_transfer(token, sender, recipient)
    report["value"] = value
    report["owner"] = scenario["owner"]
    report["only_clearing_route"] = {
        "function": "removeBlackList(address, caller)",
        "caller": "owner (onlyOwner)",
        "holder_can_call": False,
    }
    report["non_routes"] = {
        "bridge": "reverts: bridge cannot clear blacklist",
        "amm_swap": "reverts: amm cannot clear blacklist",
        "transfer": "reverts while sender or recipient is blacklisted",
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        if report["would_revert"]:
            print(f"sender {sender} is blacklisted: transfer would revert "
                  f"({', '.join(report['revert_reasons'])}); stop before sending.")
        else:
            print(f"sender {sender} and recipient {recipient} are clear: "
                  f"{report['action']}.")
        print(f"only clearing route: {report['only_clearing_route']['function']} "
              f"called by {report['only_clearing_route']['caller']}; "
              f"a holder cannot call it.")

    # 1 = would revert (a blocked operation is the expected outcome here)
    return 1 if report["would_revert"] else 0


if __name__ == "__main__":
    sys.exit(main())
