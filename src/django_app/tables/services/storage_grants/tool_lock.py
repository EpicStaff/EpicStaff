from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from agents.models import (
    AgentDefaultSurface,
    AgentInlineSurfacePythonTool,
    InlineSurfacePythonTool,
    SurfacePythonTool,
    ToolMode,
)
from src.shared.models.storage_scope import StorageAction
from tables.models.graph_models import AgentNode, TaskNode
from tables.services.storage_grants.actor import GrantActor, permissions_behind
from tables.services.storage_grants.errors import PERMISSION_LABELS
from tables.services.storage_grants.flags import GrantFlags
from tables.services.storage_grants.flow_checks import assert_actor_holds
from tables.services.storage_grants.slots import STORAGE_GRANT_SLOTS
from tables.services.storage_grants.storage_use import nodes_using_storage_tools
from tables.services.storage_grants.write_checks import python_code_changed

_TOOL_NODE_MODELS = (AgentNode, TaskNode)


@dataclass(frozen=True)
class ToolGrantLock:
    """What editing a Python tool's code requires, because flows run it with a grant.

    Attributes:
        actions: Every action any node using the tool is granted.
        flow_names: The flows holding those nodes, sorted.
    """

    actions: frozenset[StorageAction]
    flow_names: tuple[str, ...]


def grant_locks_for_tools(
    tool_ids: Iterable[int], org_id: int, *, incoming_gives_storage: bool = False
) -> dict[int, ToolGrantLock]:
    """The lock of each given Python tool that a granted node of the org uses.

    A node uses a tool when the tool is allowed on a surface the node attaches, on one
    its agent has as a default, or on the node's own inline surface. A deny entry is
    ignored, which can only lock more. A tool no granted node uses has no entry.
    A node that is not configured counts as granted every action when it uses a tool
    with storage on (see `GrantFlags.held_for_lock`).
    The number of queries does not depend on the number of tools.

    Args:
        incoming_gives_storage: Treat the given tools as having storage on, for the lock of
            switching it on.
    """
    tool_ids = list(tool_ids)
    if not tool_ids:
        return {}
    node_ids_by_tool: dict[int, dict[type, set[int]]] = defaultdict(
        lambda: {model: set() for model in _TOOL_NODE_MODELS}
    )

    tool_ids_by_surface: dict[int, set[int]] = defaultdict(set)
    for tool_id, surface_id in SurfacePythonTool.objects.filter(
        mode=ToolMode.ALLOW, python_tool_id__in=tool_ids, surface__org_id=org_id
    ).values_list("python_tool_id", "surface_id"):
        tool_ids_by_surface[surface_id].add(tool_id)
    if tool_ids_by_surface:
        _collect_through_surfaces(tool_ids_by_surface, org_id, node_ids_by_tool)

    for tool_id, node_id in InlineSurfacePythonTool.objects.filter(
        mode=ToolMode.ALLOW, python_tool_id__in=tool_ids
    ).values_list("python_tool_id", "inline_surface__task_node_id"):
        node_ids_by_tool[tool_id][TaskNode].add(node_id)
    for tool_id, node_id in AgentInlineSurfacePythonTool.objects.filter(
        mode=ToolMode.ALLOW, python_tool_id__in=tool_ids
    ).values_list("python_tool_id", "agent_inline_surface__agent_node_id"):
        node_ids_by_tool[tool_id][AgentNode].add(node_id)

    return _locks_of_nodes(node_ids_by_tool, org_id, incoming_gives_storage=incoming_gives_storage)


def _collect_through_surfaces(
    tool_ids_by_surface: dict[int, set[int]],
    org_id: int,
    node_ids_by_tool: dict[int, dict[type, set[int]]],
) -> None:
    surface_ids = list(tool_ids_by_surface)
    agent_ids_by_surface: dict[int, set[int]] = defaultdict(set)
    for surface_id, agent_definition_id in AgentDefaultSurface.objects.filter(
        surface_id__in=surface_ids
    ).values_list("surface_id", "agent_definition_id"):
        agent_ids_by_surface[surface_id].add(agent_definition_id)
    for model in _TOOL_NODE_MODELS:
        for node_id, surface_id in model.objects.filter(
            graph__org_id=org_id, surface_list__in=surface_ids
        ).values_list("id", "surface_list"):
            for tool_id in tool_ids_by_surface[surface_id]:
                node_ids_by_tool[tool_id][model].add(node_id)
        agent_definition_ids = {
            agent_definition_id
            for agent_ids in agent_ids_by_surface.values()
            for agent_definition_id in agent_ids
        }
        for node_id, agent_definition_id in model.objects.filter(
            graph__org_id=org_id, agent_definition_id__in=agent_definition_ids
        ).values_list("id", "agent_definition_id"):
            for surface_id, agent_ids in agent_ids_by_surface.items():
                if agent_definition_id in agent_ids:
                    for tool_id in tool_ids_by_surface[surface_id]:
                        node_ids_by_tool[tool_id][model].add(node_id)


def _locks_of_nodes(
    node_ids_by_tool: dict[int, dict[type, set[int]]],
    org_id: int,
    *,
    incoming_gives_storage: bool = False,
) -> dict[int, ToolGrantLock]:
    """The lock of each key of `node_ids_by_tool` from the grants of the nodes it maps to.

    Args:
        incoming_gives_storage: Count every given node as using storage, for a write that gives
            the tools it reaches storage.
    """
    grants_by_node: dict[tuple[type, int], tuple[frozenset[StorageAction], str]] = {}
    for model in _TOOL_NODE_MODELS:
        wanted = {
            node_id for per_model in node_ids_by_tool.values() for node_id in per_model[model]
        }
        (slot,) = STORAGE_GRANT_SLOTS[model]
        rows = list(
            model.objects.filter(pk__in=wanted, graph__org_id=org_id).values(
                "pk", "graph__name", *slot.flag_names
            )
        )
        not_configured = [row["pk"] for row in rows if not GrantFlags.of(row, slot).configured]
        using_storage = (
            set(not_configured)
            if incoming_gives_storage
            else nodes_using_storage_tools(model, not_configured)
        )
        for row in rows:
            grants_by_node[(model, row["pk"])] = (
                GrantFlags.of(row, slot).held_for_lock(uses_storage=row["pk"] in using_storage),
                row["graph__name"],
            )

    locks: dict[int, ToolGrantLock] = {}
    for tool_id, per_model in node_ids_by_tool.items():
        entries = [
            grants_by_node[(model, node_id)]
            for model, node_ids in per_model.items()
            for node_id in node_ids
            if (model, node_id) in grants_by_node
        ]
        actions = frozenset().union(*(granted for granted, _ in entries))
        if actions:
            locks[tool_id] = ToolGrantLock(
                actions=actions,
                flow_names=tuple(sorted({name for granted, name in entries if granted})),
            )
    return locks


def check_python_tool_write(actor: GrantActor | None, tool, data: dict, *, org_id: int) -> None:
    """Refuse an edit of a Python tool's code that the actor's Files permissions do not cover.

    Editing the code (its source, entrypoint, arguments, environment), its variables or
    switching `use_storage` changes what every flow node using the tool runs with its grant, so it
    needs every permission any of those nodes is granted. Other edits are free.

    Raises:
        StorageGrantDeniedError: A granted node uses the tool and the actor lacks one of
            its permissions; all missing ones are named.
    """
    code_edited = "python_code" in data and python_code_changed(
        tool.python_code, data["python_code"]
    )
    storage_switched = "use_storage" in data and data["use_storage"] != tool.use_storage
    # The variables' names and defaults become the keyword arguments the code is called with.
    variables_edited = "variables" in data and data["variables"] != tool.variables
    if not (code_edited or storage_switched or variables_edited):
        return
    # Switching storage on is locked by the nodes that reach the tool as if it already
    # had it, as those nodes then run with storage. Switching it off while editing the
    # code stays locked: the stored state counts too.
    incoming_gives_storage = tool.use_storage or bool(data.get("use_storage"))
    lock = grant_locks_for_tools(
        [tool.pk], org_id, incoming_gives_storage=incoming_gives_storage
    ).get(tool.pk)
    if lock is not None:
        assert_actor_holds(actor, lock.actions)


def describe_lock(lock: ToolGrantLock | None, *, show_flow_names: bool) -> dict | None:
    """The lock as the tool API shows it, or None for a tool nothing locks.

    Flow names are shown only to a caller who may read flows; others get an empty list.
    """
    if lock is None:
        return None
    ordered = [action for action in StorageAction if action in lock.actions]
    return {
        "required_grants": [action.value for action in ordered],
        "required_permissions": [
            PERMISSION_LABELS[permission] for permission in permissions_behind(lock.actions)
        ],
        "flow_names": list(lock.flow_names) if show_flow_names else [],
    }


def _merge_locks(locks: Iterable[ToolGrantLock]) -> ToolGrantLock | None:
    locks = list(locks)
    if not locks:
        return None
    return ToolGrantLock(
        actions=frozenset().union(*(lock.actions for lock in locks)),
        flow_names=tuple(sorted({name for lock in locks for name in lock.flow_names})),
    )


def grant_lock_for_surfaces(
    surface_ids: Iterable[int], org_id: int, *, incoming_gives_storage: bool = False
) -> ToolGrantLock | None:
    """What editing these surfaces requires: the grants of the nodes that attach them or whose agent defaults to them.

    Args:
        incoming_gives_storage: The edit gives the surfaces a tool with storage on, so the nodes
            reaching them count as using storage.
    """
    surface_ids = list(surface_ids)
    if not surface_ids:
        return None
    node_ids: dict[int, dict[type, set[int]]] = defaultdict(
        lambda: {model: set() for model in _TOOL_NODE_MODELS}
    )
    _collect_through_surfaces(
        {surface_id: {surface_id} for surface_id in surface_ids}, org_id, node_ids
    )
    return _merge_locks(
        _locks_of_nodes(node_ids, org_id, incoming_gives_storage=incoming_gives_storage).values()
    )


def grant_lock_for_agent_definition(
    agent_definition_id: int, org_id: int, *, incoming_gives_storage: bool = False
) -> ToolGrantLock | None:
    """What editing an agent definition requires: the grants of the nodes that run it.

    Args:
        incoming_gives_storage: The edit gives the agent a tool with storage on, so the nodes
            running it count as using storage.
    """
    node_ids = {agent_definition_id: {model: set() for model in _TOOL_NODE_MODELS}}
    for model in _TOOL_NODE_MODELS:
        node_ids[agent_definition_id][model].update(
            model.objects.filter(
                graph__org_id=org_id, agent_definition_id=agent_definition_id
            ).values_list("pk", flat=True)
        )
    return _merge_locks(
        _locks_of_nodes(node_ids, org_id, incoming_gives_storage=incoming_gives_storage).values()
    )


def grant_lock_for_venv(binding, org_id: int) -> ToolGrantLock | None:
    """What editing a virtualenv (its libraries) requires: the grants of every code that runs in it.

    That is the Python node, webhook and classification table slots set to the venv, and
    the granted agent and task nodes that use a Python tool set to it.
    """
    from tables.models import PythonCodeTool
    from tables.services.secrets.python_code_sites import GRAPH_PYTHON_CODE_SITES

    locks: list[ToolGrantLock] = []
    for site in GRAPH_PYTHON_CODE_SITES:
        (slot,) = (
            slot for slot in STORAGE_GRANT_SLOTS[site.model] if site.code_field in slot.code_fields
        )
        rows = site.model.objects.filter(
            graph__org_id=org_id, **{f"{site.code_field}__venv": binding}
        ).values("graph__name", slot.use_storage_field, *slot.flag_names)
        for row in rows:
            granted = GrantFlags.of(row, slot).held_for_lock(
                uses_storage=row[slot.use_storage_field]
            )
            if granted:
                locks.append(ToolGrantLock(granted, (row["graph__name"],)))
    tool_ids = PythonCodeTool.objects.filter(org_id=org_id, python_code__venv=binding).values_list(
        "pk", flat=True
    )
    locks.extend(grant_locks_for_tools(tool_ids, org_id).values())
    return _merge_locks(locks)


def check_surface_write(actor: GrantActor | None, surface, data: dict, *, org_id: int) -> None:
    """Refuse an edit of a surface's python tools or instructions the actor's Files permissions do not cover.

    A surface's tools run with the grant of every node that reaches it, so changing which
    tools it holds, or the instructions that steer them, is gated like the tools' code.

    Raises:
        StorageGrantDeniedError: A granted node reaches the surface and the actor lacks a
            permission of its grant.
    """
    current_tools = {(row.python_tool_id, row.mode) for row in surface.python_tools.all()}
    tools_changed = "python_tools" in data and current_tools != {
        (entry["python_tool"].pk, entry["mode"]) for entry in data["python_tools"]
    }
    instructions_changed = "instructions" in data and data["instructions"] != surface.instructions
    if not (tools_changed or instructions_changed):
        return
    incoming_gives_storage = tools_changed and any(
        entry["mode"] == ToolMode.ALLOW and entry["python_tool"].use_storage
        for entry in data["python_tools"]
    )
    lock = grant_lock_for_surfaces(
        [surface.pk], org_id, incoming_gives_storage=incoming_gives_storage
    )
    if lock is not None:
        assert_actor_holds(actor, lock.actions)


def check_agent_definition_write(
    actor: GrantActor | None, agent_definition, data: dict, *, org_id: int
) -> None:
    """Refuse an edit of an agent definition's instructions or default surfaces the actor may not hand out.

    Both steer every node that runs the agent, which holds a grant.
    """
    surfaces_changed = "default_surfaces" in data and {
        (row.surface_id, row.place) for row in agent_definition.default_surfaces.all()
    } != {(entry["surface"].pk, entry["place"]) for entry in data["default_surfaces"]}
    instructions_changed = (
        "instruction_list" in data and data["instruction_list"] != agent_definition.instruction_list
    )
    if not (surfaces_changed or instructions_changed):
        return
    incoming_gives_storage = (
        surfaces_changed
        and SurfacePythonTool.objects.filter(
            surface_id__in=[entry["surface"].pk for entry in data["default_surfaces"]],
            mode=ToolMode.ALLOW,
            python_tool__use_storage=True,
        ).exists()
    )
    lock = grant_lock_for_agent_definition(
        agent_definition.pk, org_id, incoming_gives_storage=incoming_gives_storage
    )
    if lock is not None:
        assert_actor_holds(actor, lock.actions)


def check_venv_write(actor: GrantActor | None, binding, *, org_id: int) -> None:
    """Refuse an edit of a virtualenv that code run with a grant uses, unless the actor holds that grant."""
    lock = grant_lock_for_venv(binding, org_id)
    if lock is not None:
        assert_actor_holds(actor, lock.actions)


def check_agent_node_task_write(actor: GrantActor | None, agent_node) -> None:
    """Refuse a write of a task of an agent node whose grant the actor does not hold.

    The tasks' instructions are the prompt of an agent holding the node's tools.
    """
    (slot,) = STORAGE_GRANT_SLOTS[type(agent_node)]
    flags = GrantFlags.of(agent_node, slot)
    uses_storage = not flags.configured and bool(
        nodes_using_storage_tools(type(agent_node), [agent_node.pk])
    )
    assert_actor_holds(actor, flags.held_for_lock(uses_storage=uses_storage))
