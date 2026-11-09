from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from agents.models import AgentDefaultSurface, SurfacePythonTool, ToolMode
from django.db.models import BooleanField, Case, Exists, OuterRef, Q, QuerySet, Value, When
from tables.services.storage_grants.slots import STORAGE_GRANT_SLOTS, GrantSlot, StorageUse

_ALLOWED_STORAGE_TOOL = {
    "mode": ToolMode.ALLOW,
    "python_tool__use_storage": True,
}


def _nodes_with_storage_tool(model: type) -> QuerySet:
    allowed = {f"python_tools__{key}": value for key, value in _ALLOWED_STORAGE_TOOL.items()}
    through_surfaces = Q(**{f"surface_list__{key}": value for key, value in allowed.items()})
    through_agent = Q(
        **{
            f"agent_definition__default_surfaces__surface__{key}": value
            for key, value in allowed.items()
        }
    )
    through_inline = Q(**{f"inline_surface__{key}": value for key, value in allowed.items()})
    return model.objects.filter(through_surfaces | through_agent | through_inline)


def nodes_using_storage_tools(model: type, node_ids: Iterable[int]) -> set[int]:
    """The ids, among `node_ids` of an agent or task node model, of nodes using a Python tool with storage on.

    A node uses a tool allowed on a surface it attaches, on a default surface of its
    agent, or on its inline surface. A deny entry is ignored, which can only lock more.
    One query, whatever the number of nodes.
    """
    node_ids = list(node_ids)
    if not node_ids:
        return set()
    return set(_nodes_with_storage_tool(model).filter(pk__in=node_ids).values_list("pk", flat=True))


def with_uses_storage_tool(queryset: QuerySet) -> QuerySet:
    """Annotate the agent or task nodes of `queryset` with `uses_storage_tool`.

    Lets a bulk save learn it for all the stored nodes in the query that loads them,
    instead of asking once per node. It is worked out only for nodes whose slot is not
    configured, the only ones whose lock depends on it; for the others it is None.
    """
    (slot,) = STORAGE_GRANT_SLOTS[queryset.model]
    nodes = _nodes_with_storage_tool(queryset.model).filter(pk=OuterRef("pk"))
    return queryset.annotate(
        uses_storage_tool=Case(
            When(**{f"{slot.flag_names[0]}__isnull": True}, then=Exists(nodes)),
            default=Value(None),
            output_field=BooleanField(null=True),
        )
    )


def model_uses_tools_for_storage(model: type) -> bool:
    """Whether the slot of `model` touches storage through the tools its node uses."""
    return any(slot.storage_use is StorageUse.TOOLS for slot in STORAGE_GRANT_SLOTS.get(model, ()))


def switch_uses_storage(source, slot: GrantSlot) -> bool:
    """Whether a slot that touches storage by itself does, from a node or its exported data.

    True for `StorageUse.ALWAYS`, the switch's value for `StorageUse.SWITCH`.
    """
    if slot.storage_use is StorageUse.ALWAYS:
        return True
    if isinstance(source, Mapping):
        return bool(source.get(slot.use_storage_field))
    return bool(getattr(source, slot.use_storage_field))


class _StorageToolIndex:
    """Which surfaces allow a tool with storage on, and which agents default to one, in an org."""

    def __init__(self, org_id: int) -> None:
        self._org_id = org_id
        self._surface_ids: set[int] | None = None
        self._agent_ids: set[int] = set()

    def allows(self, surface_ids: set[int], agent_definition_ids: set[int]) -> bool:
        if self._surface_ids is None:
            self._surface_ids = set(
                SurfacePythonTool.objects.filter(
                    Q(surface__org_id=self._org_id) | Q(surface__org__isnull=True),
                    **_ALLOWED_STORAGE_TOOL,
                ).values_list("surface_id", flat=True)
            )
            self._agent_ids = set(
                AgentDefaultSurface.objects.filter(surface_id__in=self._surface_ids).values_list(
                    "agent_definition_id", flat=True
                )
            )
        return bool(surface_ids & self._surface_ids) or bool(agent_definition_ids & self._agent_ids)


_active_index: ContextVar[_StorageToolIndex | None] = ContextVar("storage_tool_index", default=None)


@contextmanager
def storage_tool_index(org_id: int) -> Iterator[None]:
    """Answer `surfaces_allow_storage_tool` from two queries run on first use, for a bulk save.

    Without it each call is its own pair of queries. The surfaces' tools must not change
    while it is active.
    """
    token = _active_index.set(_StorageToolIndex(org_id))
    try:
        yield
    finally:
        _active_index.reset(token)


def surfaces_allow_storage_tool(
    surface_ids: Iterable[int], agent_definition_ids: Iterable[int | None]
) -> bool:
    """Whether any of the surfaces, or a default surface of any of the agents, allows a tool with storage on."""
    surface_ids = set(surface_ids)
    agent_definition_ids = {pk for pk in agent_definition_ids if pk is not None}
    index = _active_index.get()
    if index is not None:
        return index.allows(surface_ids, agent_definition_ids)
    surface_ids |= set(
        AgentDefaultSurface.objects.filter(
            agent_definition_id__in=agent_definition_ids
        ).values_list("surface_id", flat=True)
    )
    return SurfacePythonTool.objects.filter(
        surface_id__in=surface_ids, **_ALLOWED_STORAGE_TOOL
    ).exists()
