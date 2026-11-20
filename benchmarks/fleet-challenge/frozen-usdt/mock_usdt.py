#!/usr/bin/env python3
"""In-memory USDT-like contract: verified TetherToken/BlackList surface only.

Synthetic addresses, no chain, no keys, no network. The point is to make the
fleet reason about the real constraint: clearing a blacklist is onlyOwner.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


class Revert(Exception):
    """EVM-style revert, with a short reason."""


@dataclass
class USDTLike:
    """Faithful subset of TetherToken.sol / BlackList.sol.

    Ethereum contract reference: 0xdAC17F958D2ee523a2206206994597C13D831ec7
    Functions mirrored:
      isBlackListed (public mapping), getBlackListStatus (view),
      addBlackList / removeBlackList / destroyBlackFunds (onlyOwner),
      pause / unpause (onlyOwner), transfer (Pausable + BlackList guard).
    No other write function exists. There is deliberately NO holder-callable
    unblacklist, no bridge hook, and no AMM hook.
    """

    owner: str
    initial_supply: int = 0
    balances: Dict[str, int] = field(default_factory=dict)
    isBlackListed: Dict[str, bool] = field(default_factory=dict)
    paused: bool = False

    def __post_init__(self) -> None:
        self.balances[self.owner] = self.initial_supply
        self.totalSupply = self.initial_supply

    # ---- view -----------------------------------------------------------
    def getBlackListStatus(self, addr: str) -> bool:  # noqa: N802 (contract ABI)
        """Public read-only getter; same result as the mapping."""
        return bool(self.isBlackListed.get(addr, False))

    def getOwner(self) -> str:  # noqa: N802
        return self.owner

    #---- onlyOwner --------------------------------------------------------
    def _only_owner(self, caller: str) -> None:
        if caller != self.owner:
            raise Revert("onlyOwner")

    def addBlackList(self, addr: str, caller: str) -> None:  # noqa: N802
        self._only_owner(caller)
        self.isBlackListed[addr] = True

    def removeBlackList(self, addr: str, caller: str) -> None:  # noqa: N802
        """The ONLY way to clear a freeze, and only the issuer can do it."""
        self._only_owner(caller)
        self.isBlackListed[addr] = False

    def destroyBlackFunds(self, addr: str, caller: str) -> int:  # noqa: N802
        self._only_owner(caller)
        if not self.getBlackListStatus(addr):
            raise Revert("address not blacklisted")
        dirty = self.balances.get(addr, 0)
        self.balances[addr] = 0
        self.totalSupply -= dirty
        return dirty

    def pause(self, caller: str) -> None:
        self._only_owner(caller)
        self.paused = True

    def unpause(self, caller: str) -> None:
        self._only_owner(caller)
        self.paused = False

    #---- token ------------------------------------------------------------
    def transfer(self, src: str, dst: str, value: int) -> None:
        if self.paused:
            raise Revert("paused")
        if self.getBlackListStatus(src):
            raise Revert("blacklisted sender")
        if self.getBlackListStatus(dst):
            raise Revert("blacklisted receiver")
        if self.balances.get(src, 0) < value:
            raise Revert("insufficient balance")
        self.balances[src] -= value
        self.balances[dst] = self.balances.get(dst, 0) + value

    def balanceOf(self, addr: str) -> int:  # noqa: N802
        return self.balances.get(addr, 0)

    #---- explicit non-routes ---------------------------------------------
    def bridge(self, src: str, dst_chain: str) -> None:  # noqa: ARG002
        """A bridge observes the token; it has no authority over the list."""
        if self.getBlackListStatus(src):
            raise Revert("bridge cannot clear blacklist")

    def amm_swap(self, src: str, pool: str) -> None:  # noqa: ARG002
        """An AMM cannot clear the list; it can only forward/return/revert."""
        if self.getBlackListStatus(src):
            raise Revert("amm cannot clear blacklist")
