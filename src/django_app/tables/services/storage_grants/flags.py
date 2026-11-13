from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from src.shared.models.storage_scope import StorageAction, StorageGrant
from tables.services.storage_grants.slots import GRANT_ACTION_NAMES, GrantSlot


@dataclass(frozen=True)
class GrantFlags:
    """The three flags of one slot as stored."""

    read: bool = False
    write: bool = False
    delete: bool = False

    @property
    def granted(self) -> frozenset[StorageAction]:
        """The actions the flags grant."""
        return frozenset(
            action
            for (action, _), value in zip(GRANT_ACTION_NAMES, self._values(), strict=True)
            if value
        )

    @classmethod
    def of(cls, source, slot: GrantSlot) -> "GrantFlags":
        """The flags of `slot` read from a model instance, or from a dict keyed by column name."""
        read = source.get if isinstance(source, Mapping) else lambda name: getattr(source, name)
        return cls(*(read(name) for name in slot.flag_names))

    def _values(self) -> tuple[bool, bool, bool]:
        return self.read, self.write, self.delete


def granted_actions(flag_sources: Iterable[GrantFlags]) -> frozenset[StorageAction]:
    """The union of the actions granted by all of `flag_sources`."""
    actions: set[StorageAction] = set()
    for flags in flag_sources:
        actions |= flags.granted
    return frozenset(actions)


def storage_grant_of(node, *, prefix: str = "") -> StorageGrant:
    """The grant of a node's slot for the session payload."""
    return StorageGrant(
        **{name: getattr(node, f"{prefix}storage_grant_{name}") for _, name in GRANT_ACTION_NAMES}
    )
