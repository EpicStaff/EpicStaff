"""The models that have a recycle bin, and how to name and scope their rows."""

import uuid
from collections.abc import Callable
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
        case_insensitive_names: Names are unique regardless of case ("Report"
            and "report" clash), so a restore compares them that way.
        owner_field: An FK to another recycle-bin root that owns the row (a
            surface's `owner_agent`). Restoring the owner brings the row back
            with it; restoring the row on its own while its owner is binned
            brings it back without an owner.
        unique_names: False when the name isn't unique (voice channels), so a
            restore never renames.
        slug_names: The name is an identifier without spaces or "#" (a webhook
            path): a restore renames it to "name-2" instead of "name #2".
        global_names: The name is unique across all organizations (a webhook
            path), so a restore checks every org's live rows.
        before_restore: Frees unique values other than the name that a restore
            would collide on (a Twilio phone number). Called with the root and
            its batch, inside the restore's transaction.
        after_restore: Reconnects what the restore can't bring back by itself
            (a webhook trigger's Telegram bots). Called with the restored root
            once the restore has committed.
    """

    model: type[Model]
    name_field: str
    org_field: str
    resource_type: ResourceType
    also_taken: Q | None = field(default=None)
    owner_field: str | None = field(default=None)
    case_insensitive_names: bool = field(default=False)
    unique_names: bool = field(default=True)
    slug_names: bool = field(default=False)
    global_names: bool = field(default=False)
    before_restore: Callable[[Model, uuid.UUID], None] | None = field(default=None)
    after_restore: Callable[[Model], None] | None = field(default=None)


@cache
def bin_resources() -> dict[str, BinResource]:
    """Every recycle-bin resource, keyed by the name the bin API uses."""
    from agents.models import AgentDefinition, Surface
    from tables.models import (
        Graph,
        KeyValueTable,
        RealtimeChannel,
        Secret,
        SourceCollection,
        WebhookTrigger,
    )
    from tables.models.mcp_models import McpTool
    from tables.models.python_models import PythonCodeTool
    from tables.services.recycle_bin.restore_hooks import (
        drop_taken_phone_number,
        register_telegram_bots,
    )

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
        "key_value_table": BinResource(
            KeyValueTable, "name", "org", ResourceType.KEY_VALUE_TABLES, case_insensitive_names=True
        ),
        "collection": BinResource(
            SourceCollection, "collection_name", "org", ResourceType.KNOWLEDGE_SOURCES
        ),
        "secret": BinResource(Secret, "name", "org", ResourceType.SECRETS),
        "realtime_channel": BinResource(
            RealtimeChannel,
            "name",
            "org",
            ResourceType.VOICE,
            unique_names=False,
            before_restore=drop_taken_phone_number,
        ),
        "webhook_trigger": BinResource(
            WebhookTrigger,
            "path",
            "org",
            ResourceType.WEBHOOKS,
            slug_names=True,
            global_names=True,
            after_restore=register_telegram_bots,
        ),
    }


def bin_resource_for(model: type[Model]) -> BinResource:
    """The resource for `model`. Raises LookupError for a model without a recycle bin."""
    for resource in bin_resources().values():
        if resource.model is model:
            return resource
    raise LookupError(f"{model.__name__} has no recycle bin")
