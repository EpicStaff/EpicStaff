from rest_framework.fields import BooleanField
from src.shared.models.storage_scope import StorageAction
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.slots import (
    STORAGE_GRANT_SLOTS,
    GrantSlot,
)

_GRANT_COLUMN_MARKER = "storage_grant_"
_ALL_ACTIONS = frozenset(StorageAction)


def cap_grant_data(data: dict, actor: GrantActor | None, *, model: type) -> dict:
    """Return node `data` with every slot of `model` limited to what the actor may hand out.

    For node data of an import file or a version snapshot, keyed by column name. A slot
    that is not configured (all flags null, or the keys missing as in an export that
    predates grants) holds every action, so it is kept as it is only for an actor who
    holds all three; for anyone else it becomes explicit, holding the actions the
    actor holds. A configured slot keeps each flag only if the actor holds it. Flags
    are read the way the serializer will read them (`"true"`, 1, "on"), so a value that
    would turn out true is capped too. With no actor nothing is held. Everything that is
    not a grant flag of `model` is left alone.
    """
    capped = dict(data)
    held = _held_actions(actor)
    for slot in STORAGE_GRANT_SLOTS.get(model, ()):
        _cap_slot(capped, slot, held)
    return capped


def copied_grant_fields(node, actor: GrantActor | None) -> dict:
    """The grant columns of `node` for its copy, limited to what the actor may hand out (see `cap_grant_data`)."""
    columns = {
        field.name: getattr(node, field.name)
        for field in node._meta.fields
        if _GRANT_COLUMN_MARKER in field.name
    }
    return cap_grant_data(columns, actor, model=type(node))


def _cap_slot(data: dict, slot: GrantSlot, held: frozenset[StorageAction]) -> None:
    names = slot.flag_names
    values = [_as_flag(data.get(name)) for name in names]
    if all(value is None for value in values):
        if held == _ALL_ACTIONS:
            return
        values = [True] * len(names)
    for action, name, value in zip(slot.actions, names, values, strict=True):
        data[name] = bool(value) and action in held


def _as_flag(value) -> bool | None:
    """None for no value, else whether the serializer's boolean parsing reads `value` as true."""
    if value is None:
        return None
    try:
        return value in BooleanField.TRUE_VALUES
    except TypeError:
        return False


def _held_actions(actor: GrantActor | None) -> frozenset[StorageAction]:
    return frozenset() if actor is None else actor.held_actions()
