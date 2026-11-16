from collections.abc import Callable, Iterable
from dataclasses import dataclass

from src.shared.models.storage_scope import StorageAction
from tables.services.secrets.secret_use_checks import _installed
from tables.services.storage_grants.actor import GrantActor, permissions_behind
from tables.services.storage_grants.errors import describe_permissions
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


def grant_locks_for_venvs(binding_ids: Iterable[int], org_id: int) -> dict[int, ToolGrantLock]:
    """What editing each virtualenv (its libraries) requires, keyed by binding id.

    The grants of every code that runs in a venv: the Python node, webhook and
    classification table slots set to it. One query per code slot, whatever the number
    of venvs; a venv no granted code runs in has no entry.
    """
    from tables.services.secrets.python_code_sites import GRAPH_PYTHON_CODE_SITES

    binding_ids = list(binding_ids)
    locks: dict[int, list[ToolGrantLock]] = {}
    if not binding_ids:
        return {}
    for site in GRAPH_PYTHON_CODE_SITES:
        (slot,) = (
            slot for slot in STORAGE_GRANT_SLOTS[site.model] if site.code_field in slot.code_fields
        )
        venv_column = f"{site.code_field}__venv"
        rows = site.model.objects.filter(
            graph__org_id=org_id, **{f"{venv_column}__in": binding_ids}
        ).values(venv_column, "graph__name", *slot.flag_names)
        for row in rows:
            granted = GrantFlags.of(row, slot).granted
            if granted:
                locks.setdefault(row[venv_column], []).append(
                    ToolGrantLock(granted, (row["graph__name"],))
                )
    return {binding_id: _merge_locks(found) for binding_id, found in locks.items()}


def grant_lock_for_venv(binding, org_id: int) -> ToolGrantLock | None:
    """What editing a virtualenv (its libraries) requires: the grants of every code that runs in it."""
    return grant_locks_for_venvs([binding.pk], org_id).get(binding.pk)


def libs_lock_message(actor: GrantActor | None, lock: ToolGrantLock | None) -> str | None:
    """Tell `actor` why they cannot change a venv's libraries, or None when they can.

    None for a venv no granted code runs in, and for an actor who holds every
    permission behind the grants, which is when `check_venv_write` lets the change through.
    """
    if lock is None:
        return None
    missing = (
        permissions_behind(lock.actions)
        if actor is None
        else actor.missing_permissions(lock.actions)
    )
    if not missing:
        return None
    return (
        f"Code that runs in this virtual environment has {describe_permissions(missing)}, "
        "which you don't have. You can rename it, but not change its libraries."
    )


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
