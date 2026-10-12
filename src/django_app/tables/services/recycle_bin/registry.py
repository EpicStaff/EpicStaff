"""The models that have a recycle bin, and how to name and scope their rows.

Adding a resource to the recycle bin, and the test that fails if a step is missed:

1. Model: add SoftDeleteMixin with its three managers (caught by
   test_soft_delete_managers.py) and run `make django-makemigrations` by hand: no
   test or CI job catches a missing migration. Decide `soft_delete_keeps_references`:
   True when other rows keep their link to it while it's binned (a secret), so a
   restore reconnects them. The cost: every writable PrimaryKeyRelatedField pointing
   at the model must become a KeptLinkPrimaryKeyRelatedField or get an EXEMPT entry,
   caught by test_kept_reference_coverage.py.
2. Registry: a BinResource in `bin_resources()` below.
3. Presentation: a BinPresentation in `presentation.bin_presentations()` under the
   same key, even with no contents. Caught by
   test_recycle_bin_api.py::test_every_bin_resource_has_a_presentation.
4. Viewset: RecycleBinActionsMixin, `recycle_bin_resource_key` and
   RECYCLE_BIN_ACTION_MAP in its `rbac_action_map`. Add it to WIRED_VIEWSETS and a
   BinCase to CASES in test_recycle_bin_api.py: test_every_bin_resource_has_a_viewset
   and test_every_bin_resource_has_a_lifecycle_case fail until you do, and the
   cases then run the restore, purge and cross-org checks.
5. Empty order: the key in `empty_service.EMPTY_ORDER`. Caught by
   test_recycle_bin_empty.py::test_empty_names_every_bin_the_registry_has.
6. Frontend: the key in RecycleBinSourceKey and the maps in
   frontend/src/app/features/recycle-bin/constants (source path and kind, tab).
   The TypeScript build fails on a map that misses it.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache

from django.db.models import Model, Q
from rbac.models.enums import ResourceType
from tables.services.soft_delete import keeps_references as model_keeps_references


@dataclass(frozen=True)
class BinResource:
    """A recycle-bin root model.

    Attributes:
        name_field: The column a restore renames when the name is taken.
        org_field: The FK to the owning organization.
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

    @property
    def keeps_references(self) -> bool:
        """Rows that link to a binned row keep the link, so a restore reconnects them."""
        return model_keeps_references(self.model)


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
        "agent": BinResource(AgentDefinition, "name", "org", ResourceType.AGENTS),
        "surface": BinResource(
            Surface, "name", "org", ResourceType.SURFACES, owner_field="owner_agent"
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
