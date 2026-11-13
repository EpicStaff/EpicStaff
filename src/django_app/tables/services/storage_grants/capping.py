from rest_framework.fields import BooleanField
from src.shared.models.storage_scope import StorageAction
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.slots import (
    GRANT_ACTION_NAMES,
    STORAGE_GRANT_SLOTS,
    GrantSlot,
)

_GRANT_COLUMN_MARKER = "storage_grant_"


def cap_grant_data(data: dict, actor: GrantActor | None, *, model: type) -> dict:
    """Return node `data` with every slot of `model` limited to what the actor may hand out.

    For node data of an import file or a version snapshot, keyed by column name. A flag
    that is null or missing, as in an export that predates grants, reads as ticked, the
    way the migration ticked every existing node; each flag is then kept only if the
    actor holds the permissions behind it. Flags are read the way the serializer will
    read them (`"true"`, 1, "on"), so a value that would turn out true is capped too.
    With no actor nothing is held. Everything that is not a grant flag of `model` is
    left alone.
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
    for (action, _), name in zip(GRANT_ACTION_NAMES, slot.flag_names, strict=True):
        data[name] = _is_ticked(data.get(name)) and action in held


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
