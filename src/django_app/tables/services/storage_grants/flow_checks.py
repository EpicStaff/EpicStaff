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
