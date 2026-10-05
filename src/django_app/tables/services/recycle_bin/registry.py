"""The models that have a recycle bin, and how to name and scope their rows."""

from dataclasses import dataclass, field
from functools import cache

from django.db.models import Model, Q
from rbac.models.enums import ResourceType


@dataclass(frozen=True)
class BinResource:
    """A recycle-bin root model.

    Attributes:
        name_field: The column a restore renames when the name is taken.
        org_field: The FK to the owning organization. `org` here; the agents app's
            models (agents, surfaces) name it `organization`.
        resource_type: The RBAC resource the bin actions are checked against.
        also_taken: Rows outside the org whose names count as taken on restore
            (built-in tools are visible to every org).
        owner_field: An FK to another recycle-bin root that owns the row (a
            surface's `owner_agent`). A row whose owner is binned can't be
            restored on its own.
    """

    model: type[Model]
    name_field: str
    org_field: str
    resource_type: ResourceType
    also_taken: Q | None = field(default=None)
    owner_field: str | None = field(default=None)


@cache
def bin_resources() -> dict[str, BinResource]:
    """Every recycle-bin resource, keyed by the name the bin API uses."""
    from agents.models import AgentDefinition, Surface
    from tables.models import Graph, SourceCollection
    from tables.models.mcp_models import McpTool
    from tables.models.python_models import PythonCodeTool

    return {
        "flow": BinResource(Graph, "name", "org", ResourceType.FLOWS),
        "python_tool": BinResource(
            PythonCodeTool, "name", "org", ResourceType.TOOLS, also_taken=Q(built_in=True)
        ),
        "mcp_tool": BinResource(McpTool, "name", "org", ResourceType.TOOLS),
        "agent": BinResource(AgentDefinition, "name", "organization", ResourceType.AGENTS),
        "surface": BinResource(
            Surface, "name", "organization", ResourceType.SURFACES, owner_field="owner_agent"
        ),
        "collection": BinResource(
            SourceCollection, "collection_name", "org", ResourceType.KNOWLEDGE_SOURCES
        ),
    }


def bin_resource_for(model: type[Model]) -> BinResource:
    """The resource for `model`. Raises LookupError for a model without a recycle bin."""
    for resource in bin_resources().values():
        if resource.model is model:
            return resource
    raise LookupError(f"{model.__name__} has no recycle bin")
