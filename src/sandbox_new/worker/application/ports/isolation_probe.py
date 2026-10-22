"""The port the isolation-plan step uses to learn the kernel's Landlock ABI.

The ABI is a host fact, so probing it is infrastructure. The step depends on this
port and stays pure; the adapter runs the actual syscall. The isolation domain
services take the ABI as a plain ``int``, so this is the one seam that feeds it in.
"""

import abc

__all__ = ["AbstractIsolationProbe"]


class AbstractIsolationProbe(abc.ABC):
    @abc.abstractmethod
    def landlock_abi(self) -> int:
        """The kernel's Landlock ABI version, or 0 when Landlock is unavailable."""
