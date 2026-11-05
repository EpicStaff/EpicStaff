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


def snapshot_unconfigures_explicit_slot(nodes_data: Iterable[dict], graph_id: int) -> bool:
    """Whether restoring this node data would replace an explicit grant slot with an unconfigured one.

    An unconfigured slot runs with every action, so it widens access only over a slot
    of the flow that is explicit. Over an unconfigured slot, or a node the flow has no
    counterpart for, it changes nothing. Only nodes of a type that carries grants count.

    A restore deletes and recreates every node, so ids do not identify a node across it.
    The slot's counterpart is the current node of the same model with the same
    `node_number`: a graph-scoped number that never changes after a node is created and
    that a restore hands back to the node it stored it for. A snapshot node without a
    usable number has no counterpart.
    """
    explicit_slots = _explicit_slots_of_flow(graph_id)
    if not explicit_slots:
        return False
    for node_data in nodes_data:
        model = _grant_model_of(node_data)
        node_number = node_data.get("node_number")
        if model is None or type(node_number) is not int:
            continue
        for slot in STORAGE_GRANT_SLOTS[model]:
            if (
                not GrantFlags.of(node_data, slot).configured
                and (model, node_number, slot.prefix) in explicit_slots
            ):
                return True
    return False


def _explicit_slots_of_flow(graph_id: int) -> set[tuple[type, int, str]]:
    """The (model, node_number, slot prefix) of every configured grant slot of the flow."""
    explicit_slots = set()
    for model, slots in STORAGE_GRANT_SLOTS.items():
        columns = [name for slot in slots for name in slot.flag_names]
        for row in model.objects.filter(graph_id=graph_id, node_number__isnull=False).values(
            "node_number", *columns
        ):
            explicit_slots.update(
                (model, row["node_number"], slot.prefix)
                for slot in slots
                if GrantFlags.of(row, slot).configured
            )
    return explicit_slots


def _grant_model_of(node_data: dict) -> type | None:
    """The node model of exported node data, None for a type that carries no grants."""
    from tables.import_export.registry import entity_registry
    from tables.import_export.strategies.nodes.node_maps import NODE_TYPE_TO_ENTITY_TYPE

    entity_type = NODE_TYPE_TO_ENTITY_TYPE.get(node_data.get("node_type"))
    if entity_type is None or not entity_registry.has_strategy(entity_type):
        return None
    model = entity_registry.get_strategy(entity_type).serializer_class.Meta.model
    return model if model in STORAGE_GRANT_SLOTS else None


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
