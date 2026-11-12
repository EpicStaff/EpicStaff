import json
from collections.abc import Callable

from agents.models import ToolMode
from src.shared.models.storage_scope import StorageAction
from tables.models.graph_models import AgentNode, TaskNode
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.errors import StorageGrantDeniedError
from tables.services.storage_grants.flags import GrantFlags
from tables.services.storage_grants.slots import (
    GRANT_ACTION_NAMES,
    PYTHON_CODE_STEERING_FIELDS,
    STORAGE_GRANT_SLOTS,
    GrantSlot,
    StorageUse,
)
from tables.services.storage_grants.storage_use import (
    model_uses_tools_for_storage,
    nodes_using_storage_tools,
    surfaces_allow_storage_tool,
    switch_uses_storage,
    with_uses_storage_tool,
)

# What the steering comparison reads from the stored node of a kind, so a bulk save loads
# it for all of a kind's nodes at once instead of once per node.
STEERING_PREFETCHES: dict[type, tuple[str, ...]] = {
    AgentNode: ("surface_list", "inline_surface__python_tools", "tasks"),
    TaskNode: ("surface_list", "inline_surface__python_tools"),
}


def annotate_for_steering_check(queryset):
    """Load into `queryset` what the steering check needs of a stored node beyond its prefetches."""
    if model_uses_tools_for_storage(queryset.model):
        return with_uses_storage_tool(queryset)
    return queryset


StorageGrantCheck = Callable[[GrantActor | None, object, dict], None]


def storage_grant_check_for(model: type) -> StorageGrantCheck:
    """The write check of `model`, with the shape of a `check_<entity>_write` of the secrets."""

    def check(actor: GrantActor | None, instance, data: dict) -> None:
        check_storage_grant_write(actor, instance, data, model=model)

    return check


def check_storage_grant_write(
    actor: GrantActor | None, instance, data: dict, *, model: type
) -> None:
    """Refuse a write of a node that the actor's Files permissions do not cover.

    Two things need permissions, per grant slot of the node:

    - Changing a flag needs the permission behind it. A node that is not configured
      counts as holding every action, as that is what its runs get; a node being
      created counts as holding none, so creating one with the default flags is free.
    - Changing what the code does (`GrantSlot.steering_fields`, the nested code) needs
      every permission the slot grants, before or after the write. A slot that is not
      configured counts as granting every action when it touches storage (its unattended
      runs get them all, see `GrantFlags.held_for_lock`), and is not locked otherwise.

    A missing permission is never worked around by lowering the flags: the write is
    refused whole, naming every missing permission of every slot.

    Args:
        actor: The writer. None holds nothing.
        instance: The persisted node, or None when the write creates it.
        data: The serializer's validated data, keyed by model attribute names; a key
            absent from it is unchanged.
        model: The node's model, which picks its slots.

    Raises:
        StorageGrantDeniedError: The write needs a permission the actor lacks.
    """
    missing_for_flags: set[StorageAction] = set()
    missing_for_code: set[StorageAction] = set()
    for slot in STORAGE_GRANT_SLOTS[model]:
        current = GrantFlags.of(instance, slot) if instance is not None else GrantFlags.nothing()
        incoming = _incoming_flags(current, data, slot)
        changed = {
            action
            for action in StorageAction
            if (action in current.effective) != (action in incoming.effective)
        }
        needed_for_code = _needed_for_code(instance, data, slot, current, incoming)
        missing_for_flags |= _missing(actor, changed)
        missing_for_code |= _missing(actor, needed_for_code)
    missing = missing_for_flags | missing_for_code
    if missing:
        raise StorageGrantDeniedError.for_actor(actor, missing, change=not missing_for_code)


def _needed_for_code(
    instance, data: dict, slot: GrantSlot, current: GrantFlags, incoming: GrantFlags
) -> frozenset[StorageAction]:
    """The actions the writer must hold to change what the slot's code does, none if it does not."""
    if instance is None:
        return frozenset()
    # A slot that is configured and grants nothing locks nothing: skipping the comparison
    # also keeps a bulk save from loading each node's surfaces and tools.
    if not (current.granted | incoming.granted) and current.configured and incoming.configured:
        return frozenset()
    if not (_moved_to_another_flow(instance, data) or _steering_changed(instance, data, slot)):
        return frozenset()
    # Asked only for a slot that is not configured, and only once the write changes
    # something: it may cost queries.
    uses_storage = not (current.configured and incoming.configured) and slot_uses_storage(
        instance, data, slot
    )
    return current.held_for_lock(uses_storage=uses_storage) | incoming.held_for_lock(
        uses_storage=uses_storage
    )


def slot_uses_storage(instance, data: dict, slot: GrantSlot) -> bool:
    """Whether the slot of a persisted node touches storage before or after the write of `data`."""
    if slot.storage_use is StorageUse.TOOLS:
        return _uses_storage_tools(instance, data)
    if switch_uses_storage(instance, slot):
        return True
    return slot.storage_use is StorageUse.SWITCH and bool(data.get(slot.use_storage_field))


def _uses_storage_tools(instance, data: dict) -> bool:
    stored = getattr(instance, "uses_storage_tool", None)
    if stored is None:
        stored = bool(nodes_using_storage_tools(type(instance), [instance.pk]))
    if stored:
        return True
    tool_fields = ("surface_list", "inline_surface", "agent_definition")
    changed = [
        name for name in tool_fields if name in data and _field_changed(instance, name, data[name])
    ]
    if not changed:
        return False
    surfaces = data["surface_list"] if "surface_list" in changed else instance.surface_list.all()
    agent_definition = data.get("agent_definition", instance.agent_definition_id)
    if surfaces_allow_storage_tool(
        (surface.pk for surface in surfaces), [getattr(agent_definition, "pk", agent_definition)]
    ):
        return True
    return any(
        entry["mode"] == ToolMode.ALLOW and entry["python_tool"].use_storage
        for entry in (data.get("inline_surface") or {}).get("python_tools", [])
    )


def _missing(actor: GrantActor | None, actions) -> frozenset[StorageAction]:
    if not actions:
        return frozenset()
    if actor is None:
        return frozenset(actions)
    return actor.missing(actions)


def _incoming_flags(current: GrantFlags, data: dict, slot: GrantSlot) -> GrantFlags:
    current_by_action = {
        StorageAction.READ: current.read,
        StorageAction.WRITE: current.write,
        StorageAction.DELETE: current.delete,
    }
    names = dict(zip(slot.actions, slot.flag_names, strict=True))
    return GrantFlags(
        *(
            data.get(names[action], current_by_action[action]) if action in names else False
            for action, _ in GRANT_ACTION_NAMES
        )
    )


def _moved_to_another_flow(instance, data: dict) -> bool:
    """Whether the write moves the node to another flow, whose files and runs its grant then reaches."""
    return "graph" in data and getattr(data["graph"], "pk", data["graph"]) != instance.graph_id


def _steering_changed(instance, data: dict, slot: GrantSlot) -> bool:
    for field_name in slot.steering_fields:
        if field_name in data and _field_changed(instance, field_name, data[field_name]):
            return True
    return any(
        field_name in data and python_code_changed(getattr(instance, field_name), data[field_name])
        for field_name in slot.code_fields
    )


def _field_changed(instance, field_name: str, incoming) -> bool:
    comparator = _FIELD_COMPARATORS.get(field_name)
    if comparator is not None:
        return comparator(instance, incoming)
    return getattr(instance, field_name) != incoming


def _agent_definition_changed(instance, incoming) -> bool:
    return instance.agent_definition_id != getattr(incoming, "pk", incoming)


def _surface_list_changed(instance, incoming) -> bool:
    return {surface.pk for surface in instance.surface_list.all()} != {
        surface.pk for surface in incoming
    }


def _tasks_changed(instance, incoming) -> bool:
    """Whether an agent node's tasks differ in what steers the agent: name, order, instructions, schema."""

    def key(name, order, instructions, output_schema):
        return (name, order, instructions, json.dumps(output_schema or {}, sort_keys=True))

    current = {
        key(task.name, task.order, task.instructions, task.output_schema)
        for task in instance.tasks.all()
    }
    wanted = {
        key(
            task["name"],
            task["order"],
            task.get("instructions", ""),
            task.get("output_schema", {}),
        )
        for task in incoming
    }
    return current != wanted


def _inline_surface_changed(instance, incoming) -> bool:
    """Whether the node's inline surface differs in its python tools or its instructions."""
    inline_surface = getattr(instance, "inline_surface", None)
    current = (
        {(row.python_tool_id, row.mode) for row in inline_surface.python_tools.all()}
        if inline_surface is not None
        else set()
    )
    wanted = {
        (entry["python_tool"].pk, entry["mode"])
        for entry in (incoming or {}).get("python_tools", [])
    }
    current_instructions = inline_surface.instructions if inline_surface is not None else ""
    return current != wanted or (incoming or {}).get("instructions", "") != current_instructions


_FIELD_COMPARATORS: dict[str, Callable[[object, object], bool]] = {
    "agent_definition": _agent_definition_changed,
    "surface_list": _surface_list_changed,
    "inline_surface": _inline_surface_changed,
    "tasks": _tasks_changed,
}


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
