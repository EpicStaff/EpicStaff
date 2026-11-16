from dataclasses import dataclass

from rest_framework.fields import BooleanField
from src.shared.models.storage_scope import StorageAction
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.slots import (
    GRANT_ACTION_NAMES,
    STORAGE_GRANT_SLOTS,
    GrantSlot,
)

_GRANT_COLUMN_MARKER = "storage_grant_"
_RETIRED_SWITCH_NAME = "use_storage"


@dataclass(frozen=True)
class DroppedGrants:
    """The boxes of one slot that capping unticked because the actor lacks the permission.

    Attributes:
        code_field: The slot's nested PythonCode field, the way `venv_ref_cleared` names a slot.
        actions: The dropped actions, in the order read, write, delete.
    """

    code_field: str
    actions: tuple[StorageAction, ...]


def cap_grant_data(data: dict, actor: GrantActor | None, *, model: type) -> dict:
    """Return node `data` with every slot of `model` limited to what the actor may hand out.

    For node data of an import file or a version snapshot, keyed by column name. A flag
    that is null or missing, as in an export that predates grants, reads as ticked, the
    way the migration ticked every existing node; each flag is then kept only if the
    actor holds the permissions behind it. Flags are read the way the serializer will
    read them (`"true"`, 1, "on"), so a value that would turn out true is capped too.
    With no actor nothing is held. A slot whose retired storage switch is explicitly off
    has every box off, whatever the boxes say (see `_switch_is_off`); the switch itself is
    dropped. Everything that is not a grant flag of `model` is left alone.
    """
    return cap_grant_data_reporting(data, actor, model=model)[0]


def cap_grant_data_reporting(
    data: dict, actor: GrantActor | None, *, model: type
) -> tuple[dict, list[DroppedGrants]]:
    """Cap `data` as `cap_grant_data` does, and report what the actor's permissions dropped.

    A box counts as dropped only when it read as ticked and the actor lacks the
    permission behind it. A box turned off by the retired switch is not reported: the
    node never had storage, so nobody lost anything.

    Returns:
        The capped data, and one entry per slot that lost a box, in slot order.
    """
    capped = dict(data)
    held = _held_actions(actor)
    dropped: list[DroppedGrants] = []
    for slot in STORAGE_GRANT_SLOTS.get(model, ()):
        slot_dropped = _cap_slot(capped, slot, held)
        if slot_dropped is not None:
            dropped.append(slot_dropped)
    return capped, dropped


def copied_grant_fields(node, actor: GrantActor | None) -> dict:
    """The grant columns of `node` for its copy, limited to what the actor may hand out (see `cap_grant_data`)."""
    columns = {
        field.name: getattr(node, field.name)
        for field in node._meta.fields
        if _GRANT_COLUMN_MARKER in field.name
    }
    return cap_grant_data(columns, actor, model=type(node))


def _cap_slot(data: dict, slot: GrantSlot, held: frozenset[StorageAction]) -> DroppedGrants | None:
    switch_is_off = _switch_is_off(data.pop(f"{slot.prefix}{_RETIRED_SWITCH_NAME}", None))
    dropped: list[StorageAction] = []
    for (action, _), name in zip(GRANT_ACTION_NAMES, slot.flag_names, strict=True):
        ticked = not switch_is_off and _is_ticked(data.get(name))
        data[name] = ticked and action in held
        if ticked and action not in held:
            dropped.append(action)
    if not dropped:
        return None
    return DroppedGrants(code_field=slot.code_fields[0], actions=tuple(dropped))


def _switch_is_off(value) -> bool:
    """Whether the retired `use_storage` switch of a slot is explicitly off.

    Import files and version snapshots made before the switch was removed carry it. A node
    whose switch was off got no storage, but the migration that introduced grants ticked
    every box on it, so without this its boxes would read as ticked and the node would
    gain access to the flow's files. A missing or null switch says nothing.
    """
    if value is None:
        return False
    if isinstance(value, str):
        value = value.lower()
    try:
        return value in BooleanField.FALSE_VALUES
    except TypeError:
        return False


def _is_ticked(value) -> bool:
    """Whether the serializer's boolean parsing reads `value` as true; no value reads as ticked."""
    if value is None:
        return True
    try:
        return value in BooleanField.TRUE_VALUES
    except TypeError:
        return False


def _held_actions(actor: GrantActor | None) -> frozenset[StorageAction]:
    return frozenset() if actor is None else actor.held_actions()
