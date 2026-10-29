"""Stand-in for the Landlock ABI probe.

The ABI is the single input every isolation decision turns on, so the tests set it
directly instead of depending on the kernel the suite happens to run on.
"""

from worker.application.ports import AbstractIsolationProbe

__all__ = ["FakeIsolationProbe"]


class FakeIsolationProbe(AbstractIsolationProbe):
    def __init__(self, abi: int = 6) -> None:
        self.abi = abi
        self.calls = 0

    def landlock_abi(self) -> int:
        self.calls += 1
        return self.abi
