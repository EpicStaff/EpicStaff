"""Domain services: the sandbox's isolation decisions.

Pure domain logic -- no I/O, no syscalls, no framework, no environment reads. Each
function takes the kernel's Landlock ABI and the configured requirement flags
(gathered by an application step from infrastructure and settings) and returns a
domain value describing how to confine one execution. The infrastructure launcher
later APPLIES these decisions via seccomp/Landlock; here we only DECIDE.

ABI thresholds live here, not in the Landlock binding: which kernels can enforce
what is a fact of the policy, so the decision owns it rather than reaching into
infrastructure for it.
"""

from pathlib import Path

from worker.domain.enums import (
    FilesystemIsolationPolicy,
    NetworkPolicy,
    SignalIsolationPolicy,
)
from worker.domain.models import Jail, NetworkDecision

__all__ = [
    "MIN_ABI_FOR_SIGNAL_ISOLATION",
    "build_jail",
    "decide_filesystem_isolation_policy",
    "decide_network_policy",
    "decide_signal_isolation_policy",
]

MIN_ABI_FOR_SIGNAL_ISOLATION = 6
_MIN_ABI_FOR_NET = 4

_UNRESTRICTED = NetworkDecision(policy=NetworkPolicy.UNRESTRICTED)
_BLOCK_ALL = NetworkDecision(policy=NetworkPolicy.BLOCK_ALL)
_REFUSE = NetworkDecision(policy=NetworkPolicy.REFUSE)


def build_jail(*, exec_dir: Path, venv_path: Path, savefiles_root: Path) -> Jail:
    """The filesystem allowlist one confined execution is restricted to.

    Widening any of these lists is a security-relevant change and requires review.
    """
    read_write = (
        str(exec_dir.absolute()),
        str((exec_dir / "home").absolute()),
        str((exec_dir / "tmp").absolute()),
        str(savefiles_root.absolute()),
    )
    read_exec = (
        str(venv_path.absolute()),
        "/usr",
        "/lib",
        "/lib64",
        "/bin",
    )
    read_only = (
        "/etc/ld.so.cache",
        "/etc/ssl",
        "/etc/resolv.conf",
        "/etc/hosts",
        "/etc/nsswitch.conf",
        "/etc/localtime",
        "/dev/null",
        "/dev/zero",
        "/dev/urandom",
        "/dev/random",
    )
    return Jail(read_write=read_write, read_only=read_only, read_exec=read_exec)


def decide_network_policy(
    *,
    block_network: bool,
    use_storage: bool,
    landlock_abi: int,
    storage_port: int,
) -> NetworkDecision:
    """Pick the network confinement for one execution.

    ``BLOCK_ALL`` is applied with seccomp (Landlock net can't block UDP, so DNS
    would leak); ``ALLOW_PORTS`` with Landlock (seccomp can't inspect the connect
    sockaddr to allow only the storage port). Refuses (rather than degrading) when
    ``use_storage`` is set but ``landlock_abi`` is too old for the port carve-out,
    so the execution that asked for storage never silently loses confinement.
    """
    if not block_network:
        return _UNRESTRICTED

    if not use_storage:
        return _BLOCK_ALL

    if landlock_abi < _MIN_ABI_FOR_NET:
        return _REFUSE

    return NetworkDecision(
        policy=NetworkPolicy.ALLOW_PORTS,
        allowed_tcp_ports=(storage_port,),
    )


def decide_signal_isolation_policy(
    *, landlock_abi: int, require_signal_isolation: bool
) -> SignalIsolationPolicy:
    """Pick the signal isolation for one execution.

    All executions run as the same uid in one container, so without this any job
    can signal another tenant's job or reach its abstract UNIX sockets. Landlock
    ABI 6+ closes both paths. Refuses (rather than degrading to UNISOLATED) when
    the kernel has Landlock but is too old and ``require_signal_isolation`` is set.
    """
    if landlock_abi < 1:
        return SignalIsolationPolicy.NOT_APPLICABLE

    if landlock_abi >= MIN_ABI_FOR_SIGNAL_ISOLATION:
        return SignalIsolationPolicy.ENFORCE

    if require_signal_isolation:
        return SignalIsolationPolicy.REFUSE

    return SignalIsolationPolicy.UNISOLATED


def decide_filesystem_isolation_policy(
    *, landlock_abi: int, require_isolation: bool
) -> FilesystemIsolationPolicy:
    """Pick the filesystem confinement for one execution.

    Any Landlock (ABI 1+) can enforce the jail. On a kernel with no Landlock at
    all, ``require_isolation`` decides between refusing the execution (the default,
    fail closed) and running it fully unconfined.
    """
    if landlock_abi >= 1:
        return FilesystemIsolationPolicy.ENFORCE

    if require_isolation:
        return FilesystemIsolationPolicy.REFUSE

    return FilesystemIsolationPolicy.UNCONFINED
