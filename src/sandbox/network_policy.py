"""Decides what network confinement a sandboxed execution's child should get.

Pure decision maker: no I/O, no syscalls. Callers (`launcher.py`) apply the
decision via `seccomp.py` and/or `landlock.py`.

`BLOCK_ALL` uses seccomp because Landlock net can't express a total block (no
UDP coverage, so DNS would stay open). `ALLOW_PORTS` uses Landlock because
seccomp can't inspect `connect()`'s `sockaddr`, so it can't say "only the storage port".
Neither primitive alone covers both cases.

`REFUSE` (instead of `BLOCK_ALL`/`UNRESTRICTED`) is returned when storage
access was requested but the kernel's Landlock ABI is too old to grant the
port carve-out -- failing open there would silently drop network confinement
for exactly the execution that asked for it.
"""

from dataclasses import dataclass
from enum import Enum, auto


class NetworkPolicy(Enum):
    UNRESTRICTED = auto()
    BLOCK_ALL = auto()
    ALLOW_PORTS = auto()
    REFUSE = auto()


@dataclass(frozen=True)
class NetworkDecision:
    policy: NetworkPolicy
    allowed_tcp_ports: tuple[int, ...] = ()


_MIN_LANDLOCK_ABI_FOR_NET = 4

_UNRESTRICTED = NetworkDecision(policy=NetworkPolicy.UNRESTRICTED)
_BLOCK_ALL = NetworkDecision(policy=NetworkPolicy.BLOCK_ALL)
_REFUSE = NetworkDecision(policy=NetworkPolicy.REFUSE)


def decide_network_policy(
    *,
    block_network: bool,
    use_storage: bool,
    landlock_abi: int,
    storage_port: int,
) -> NetworkDecision:
    """Pick the network confinement for one execution.

    Refuses (rather than degrading to BLOCK_ALL or UNRESTRICTED) when
    `use_storage=True` but `landlock_abi` is too old for the port carve-out.
    """
    if not block_network:
        return _UNRESTRICTED

    if not use_storage:
        return _BLOCK_ALL

    if landlock_abi < _MIN_LANDLOCK_ABI_FOR_NET:
        return _REFUSE

    return NetworkDecision(
        policy=NetworkPolicy.ALLOW_PORTS,
        allowed_tcp_ports=(storage_port,),
    )
