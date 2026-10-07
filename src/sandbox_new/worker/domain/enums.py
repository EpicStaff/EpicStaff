from enum import Enum, auto

__all__ = [
    "FilesystemIsolationPolicy",
    "NetworkPolicy",
    "SignalIsolationPolicy",
]


class NetworkPolicy(Enum):
    UNRESTRICTED = auto()
    BLOCK_ALL = auto()
    ALLOW_PORTS = auto()
    REFUSE = auto()


class SignalIsolationPolicy(Enum):
    ENFORCE = auto()
    REFUSE = auto()
    UNISOLATED = auto()
    # The kernel has no Landlock at all. The filesystem-isolation decision has
    # already refused the execution or accepted running it fully unconfined, so
    # signal isolation has nothing to add.
    NOT_APPLICABLE = auto()


class FilesystemIsolationPolicy(Enum):
    ENFORCE = auto()
    REFUSE = auto()
    UNCONFINED = auto()
