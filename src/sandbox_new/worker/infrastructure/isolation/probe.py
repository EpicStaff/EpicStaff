"""Landlock ABI probe adapter.

The ABI cannot change while the process runs, so it is probed once and cached.
"""

from worker.application.ports.isolation_probe import AbstractIsolationProbe
from worker.infrastructure.isolation import landlock

__all__ = ["LandlockIsolationProbe"]


class LandlockIsolationProbe(AbstractIsolationProbe):
    def __init__(self) -> None:
        self._abi: int | None = None

    def landlock_abi(self) -> int:
        if self._abi is None:
            self._abi = landlock.abi_version()
        return self._abi
