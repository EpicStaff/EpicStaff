from collections.abc import Iterable

from src.shared.models.storage_scope import StorageAction
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.errors import StorageGrantDeniedError
from tables.services.storage_grants.flags import GrantFlags, granted_actions
from tables.services.storage_grants.slots import STORAGE_GRANT_SLOTS


def actions_granted_in_flows(graph_ids: Iterable[int]) -> frozenset[StorageAction]:
    """The union of the actions any node or code slot of these flows is granted.

    One query per node model that carries grants, whatever the number of flows.
    """
    graph_ids = list(graph_ids)
    flags: list[GrantFlags] = []
    for model, slots in STORAGE_GRANT_SLOTS.items():
        columns = [name for slot in slots for name in slot.flag_names]
        for row in model.objects.filter(graph_id__in=graph_ids).values(*columns):
            flags.extend(GrantFlags.of(row, slot) for slot in slots)
    return granted_actions(flags)


def actions_granted_in_snapshot(nodes_data: Iterable[dict]) -> frozenset[StorageAction]:
    """The union of the actions granted by exported node data (an import file or a version snapshot)."""
    slots = [slot for model_slots in STORAGE_GRANT_SLOTS.values() for slot in model_slots]
    return granted_actions(
        GrantFlags.of(node_data, slot) for node_data in nodes_data for slot in slots
    )


def snapshot_has_unconfigured_slot(nodes_data: Iterable[dict]) -> bool:
    """Whether exported node data holds a grant slot that is not configured.

    Such a slot runs with every action, so applying it hands out all three. Only nodes
    of a type that carries grants count: other node types have no slot to configure.
    """
    from tables.import_export.registry import entity_registry
    from tables.import_export.strategies.nodes.node_maps import NODE_TYPE_TO_ENTITY_TYPE

    for node_data in nodes_data:
        entity_type = NODE_TYPE_TO_ENTITY_TYPE.get(node_data.get("node_type"))
        if entity_type is None or not entity_registry.has_strategy(entity_type):
            continue
        model = entity_registry.get_strategy(entity_type).serializer_class.Meta.model
        if any(
            not GrantFlags.of(node_data, slot).configured
            for slot in STORAGE_GRANT_SLOTS.get(model, ())
        ):
            return True
    return False


def assert_actor_holds(actor: GrantActor | None, actions: frozenset[StorageAction]) -> None:
    """Require the Files permissions behind `actions`.

    Raises:
        StorageGrantDeniedError: The actor lacks one or more of them; all are named.
    """
    if not actions:
        return
    missing = actions if actor is None else actor.missing(actions)
    if missing:
        raise StorageGrantDeniedError.for_actor(actor, missing)
