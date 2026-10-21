"""What a bulk restore or purge did, item by item. Kept import-free so every bin can use it."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BulkFailure:
    id: int
    name: str
    message: str


@dataclass
class BulkRestoreResult:
    restored: list = field(default_factory=list)  # RestoreResult items
    failed: list[BulkFailure] = field(default_factory=list)


@dataclass
class BulkPurgeResult:
    purged: list[int] = field(default_factory=list)
    failed: list[BulkFailure] = field(default_factory=list)
