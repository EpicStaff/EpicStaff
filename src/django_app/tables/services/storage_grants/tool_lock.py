from collections.abc import Callable, Iterable
from dataclasses import dataclass

from src.shared.models.storage_scope import StorageAction
from tables.services.secrets.secret_use_checks import _installed
from tables.services.storage_grants.actor import GrantActor
from tables.services.storage_grants.flags import GrantFlags
from tables.services.storage_grants.flow_checks import assert_actor_holds
from tables.services.storage_grants.slots import STORAGE_GRANT_SLOTS


@dataclass(frozen=True)
class ToolGrantLock:
    """What editing a virtualenv requires, because flows run code in it with a grant.

    Attributes:
        actions: Every action any code running in the venv is granted.
        flow_names: The flows holding those nodes, sorted.
    """

    actions: frozenset[StorageAction]
    flow_names: tuple[str, ...]


def _merge_locks(locks: Iterable[ToolGrantLock]) -> ToolGrantLock | None:
    locks = list(locks)
    if not locks:
        return None
    return ToolGrantLock(
        actions=frozenset().union(*(lock.actions for lock in locks)),
        flow_names=tuple(sorted({name for lock in locks for name in lock.flow_names})),
    )


def grant_lock_for_venv(binding, org_id: int) -> ToolGrantLock | None:
    """What editing a virtualenv (its libraries) requires: the grants of every code that runs in it.

    That is the Python node, webhook and classification table slots set to the venv.
    """
    from tables.services.secrets.python_code_sites import GRAPH_PYTHON_CODE_SITES

    locks: list[ToolGrantLock] = []
    for site in GRAPH_PYTHON_CODE_SITES:
        (slot,) = (
            slot for slot in STORAGE_GRANT_SLOTS[site.model] if site.code_field in slot.code_fields
        )
        rows = site.model.objects.filter(
            graph__org_id=org_id, **{f"{site.code_field}__venv": binding}
        ).values("graph__name", *slot.flag_names)
        for row in rows:
            granted = GrantFlags.of(row, slot).granted
            if granted:
                locks.append(ToolGrantLock(granted, (row["graph__name"],)))
    return _merge_locks(locks)


def check_venv_write(
    actor: GrantActor | None,
    binding,
    data: dict,
    *,
    org_id: int,
    read_current_libs: Callable[[], list],
) -> None:
    """Refuse a change of a virtualenv's libraries that code run with a grant uses, unless the actor holds that grant.

    Only the libraries are locked: a write that leaves them as they are, a rename for
    one, needs nothing. The current libraries live in the sandbox, so `read_current_libs`
    is called only for a venv such code runs in. Libraries are compared as the secrets
    check compares them.
    """
    if "libs" not in data:
        return
    lock = grant_lock_for_venv(binding, org_id)
    if lock is None:
        return
    if _installed(read_current_libs()) == _installed(data["libs"]):
        return
    assert_actor_holds(actor, lock.actions)
