"""Decides whether a sandboxed execution's child gets Landlock signal isolation.

Pure decision maker: no I/O, no syscalls. `launcher.py` applies the decision
via `landlock.apply(isolate_signals=...)`.

All executions run as the same uid in one container, so without signal
isolation any job can `kill()` another tenant's job or connect to its
abstract UNIX sockets. Signal isolation (Landlock ABI 6+) gives each
execution its own domain and closes both paths.

There is no switch to turn signal isolation off where the kernel supports
it. `SANDBOX_REQUIRE_SIGNAL_ISOLATION` only decides what happens on an older
kernel: refuse (the default), or run without it.
"""

from enum import Enum, auto

from landlock import MIN_ABI_FOR_SIGNAL_ISOLATION


class SignalIsolationPolicy(Enum):
    ENFORCE = auto()
    REFUSE = auto()
    UNISOLATED = auto()
    # The kernel has no Landlock at all. The filesystem-isolation decision
    # (`SANDBOX_REQUIRE_ISOLATION`) has already refused the execution or
    # accepted running it fully unconfined, so signal isolation has nothing to add.
    NOT_APPLICABLE = auto()


def decide_signal_isolation_policy(
    *, landlock_abi: int, require_signal_isolation: bool
) -> SignalIsolationPolicy:
    """Pick the signal isolation for one execution.

    Refuses (rather than degrading to UNISOLATED) when the kernel has Landlock
    but is too old for signal isolation and `require_signal_isolation` is set.
    """
    if landlock_abi < 1:
        return SignalIsolationPolicy.NOT_APPLICABLE

    if landlock_abi >= MIN_ABI_FOR_SIGNAL_ISOLATION:
        return SignalIsolationPolicy.ENFORCE

    if require_signal_isolation:
        return SignalIsolationPolicy.REFUSE

    return SignalIsolationPolicy.UNISOLATED
