from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from src.shared.models.storage_scope import StorageAction, StorageGrant
from tables.services.storage_grants.slots import GRANT_ACTION_NAMES, GrantSlot

_ALL_ACTIONS = frozenset(StorageAction)


@dataclass(frozen=True)
class GrantFlags:
    """The three flags of one slot as stored: `None` for each means not configured."""

    read: bool | None = None
    write: bool | None = None
    delete: bool | None = None

    @property
    def configured(self) -> bool:
        return self.read is not None

    @property
    def granted(self) -> frozenset[StorageAction]:
        """The actions the flags grant; nothing for a slot that is not configured."""
        return frozenset(
            action
            for (action, _), value in zip(GRANT_ACTION_NAMES, self._values(), strict=True)
            if value
        )

    @property
    def effective(self) -> frozenset[StorageAction]:
        """What an unattended run lets the code do: everything when not configured."""
        return self.granted if self.configured else _ALL_ACTIONS

    def held_for_lock(self, *, uses_storage: bool) -> frozenset[StorageAction]:
        """What a writer must hold to change the code of a slot with these flags.

        The granted actions; for a slot that is not configured, every action when the
        slot touches storage (its unattended runs get them all) and nothing otherwise.
        """
        if self.configured:
            return self.granted
        return _ALL_ACTIONS if uses_storage else frozenset()

    @classmethod
    def of(cls, source, slot: GrantSlot) -> "GrantFlags":
        """The flags of `slot` read from a model instance, or from a dict keyed by column name."""
        names = slot.flag_names
        if isinstance(source, Mapping):
            return cls(*(source.get(name) for name in names))
        return cls(*(getattr(source, name) for name in names))

    @classmethod
    def nothing(cls) -> "GrantFlags":
        """Configured, all off: what a node created without flags gets."""
        return cls(False, False, False)

    def _values(self) -> tuple[bool | None, bool | None, bool | None]:
        return self.read, self.write, self.delete


def granted_actions(flag_sources: Iterable[GrantFlags]) -> frozenset[StorageAction]:
    """The union of the actions granted by all of `flag_sources`."""
    actions: set[StorageAction] = set()
    for flags in flag_sources:
        actions |= flags.granted
    return frozenset(actions)


def storage_grant_of(node, *, prefix: str = "") -> StorageGrant | None:
    """The grant of a node's slot for the session payload, None when it is not configured."""
    flags = GrantFlags(
        *(getattr(node, f"{prefix}storage_grant_{name}") for _, name in GRANT_ACTION_NAMES)
    )
    if not flags.configured:
        return None
    return StorageGrant(read=flags.read, write=flags.write, delete=flags.delete)
