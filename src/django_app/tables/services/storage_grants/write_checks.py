from collections.abc import Callable

from src.shared.models.storage_scope import StorageAction
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.errors import StorageGrantDeniedError
from tables.services.storage_grants.flags import GrantFlags
from tables.services.storage_grants.slots import (
    FILE_NODE_MODELS,
    PYTHON_CODE_STEERING_FIELDS,
    STORAGE_GRANT_SLOTS,
    GrantSlot,
)

StorageGrantCheck = Callable[[GrantActor | None, object, dict], None]


def storage_grant_check_for(model: type) -> StorageGrantCheck:
    """The write check of `model`, with the shape of a `check_<entity>_write` of the secrets."""

    def check(actor: GrantActor | None, instance, data: dict) -> None:
        check_storage_grant_write(actor, model, instance, data)

    return check


def check_storage_grant_write(
    actor: GrantActor | None, model: type, instance, data: dict
) -> None:
    """Refuse a write of a node that the actor's Files permissions do not cover.

    The rule, per grant slot of the node:

    1. Raising a box needs the Files permissions behind that box.
    2. Changing what the code does (`GrantSlot.steering_fields`, the nested code, moving
       the node to another flow) needs every box the node currently has ticked.
    3. Lowering a box is always allowed.
    4. File Extractor and Audio to Text carry no boxes: creating one, or changing any of its
       fields (moving it to another flow included), needs the permissions behind Read.
       Deleting one needs nothing, and a save that changes nothing is not checked.

    A create counts as raising from all boxes off. A slot in which nothing changed is
    never checked. A request that lowers a box and changes the code is refused whole:
    rule 2 reads the boxes as they are stored, not as the request leaves them.

    Args:
        actor: The writer. None holds nothing.
        model: The node's model, which picks its slots.
        instance: The persisted node, or None when the write creates it.
        data: The serializer's validated data, keyed by model attribute names; a key
            absent from it is unchanged.

    Raises:
        StorageGrantDeniedError: The write needs a permission the actor lacks, and every
            missing one of every slot is named.
    """
    if model in FILE_NODE_MODELS:
        if instance is None or _fields_changed(instance, data):
            assert_can_write_file_node(actor)
        return
    missing_for_raise: set[StorageAction] = set()
    missing_for_code: set[StorageAction] = set()
    for slot in STORAGE_GRANT_SLOTS[model]:
        current = GrantFlags.of(instance, slot) if instance is not None else GrantFlags()
        incoming = _incoming_flags(current, data, slot)
        raised = incoming.granted - current.granted
        code_changed = instance is not None and (
            _moved_to_another_flow(instance, data) or _steering_changed(instance, data, slot)
        )
        needed_for_code = set(current.granted) if code_changed else set()
        missing_for_raise |= _missing(actor, raised)
        missing_for_code |= _missing(actor, needed_for_code)
    missing = missing_for_raise | missing_for_code
    if missing:
        raise StorageGrantDeniedError.for_actor(actor, missing, change=not missing_for_code)


def assert_can_write_file_node(actor: GrantActor | None) -> None:
    """Require the Files permission behind Read, for writing a File Extractor or Audio to Text node.

    Raises:
        StorageGrantDeniedError: The actor lacks it.
    """
    missing = _missing(actor, {StorageAction.READ})
    if missing:
        raise StorageGrantDeniedError.for_actor(actor, missing, file_node=True)


def _fields_changed(instance, data: dict) -> bool:
    """Whether any model field in `data` differs from the persisted node.

    Keys that are not fields of the node (a bulk save's `temp_id`) are not changes.
    """
    model_fields = {field.name: field for field in instance._meta.concrete_fields}
    for field_name, incoming in data.items():
        field = model_fields.get(field_name)
        if field is None:
            continue
        stored = getattr(instance, field.attname)
        if stored != (incoming.pk if field.is_relation and incoming is not None else incoming):
            return True
    return False


def _missing(actor: GrantActor | None, actions) -> frozenset[StorageAction]:
    if not actions:
        return frozenset()
    if actor is None:
        return frozenset(actions)
    return actor.missing(actions)


def _incoming_flags(current: GrantFlags, data: dict, slot: GrantSlot) -> GrantFlags:
    return GrantFlags(
        *(
            data.get(name, stored)
            for name, stored in zip(
                slot.flag_names, (current.read, current.write, current.delete), strict=True
            )
        )
    )


def _moved_to_another_flow(instance, data: dict) -> bool:
    """Whether the write moves the node to another flow, whose files and runs its grant then reaches."""
    return "graph" in data and getattr(data["graph"], "pk", data["graph"]) != instance.graph_id


def _steering_changed(instance, data: dict, slot: GrantSlot) -> bool:
    for field_name in slot.steering_fields:
        if field_name in data and getattr(instance, field_name) != data[field_name]:
            return True
    return any(
        field_name in data and python_code_changed(getattr(instance, field_name), data[field_name])
        for field_name in slot.code_fields
    )


def python_code_changed(current, incoming) -> bool:
    """Whether the nested PythonCode data differs from the persisted code in what it runs."""
    if current is None or incoming is None:
        return current is not incoming
    for field_name in PYTHON_CODE_STEERING_FIELDS:
        if field_name not in incoming:
            continue
        if field_name == "venv":
            if getattr(incoming["venv"], "pk", incoming["venv"]) != current.venv_id:
                return True
        elif incoming[field_name] != getattr(current, field_name):
            return True
    return False
