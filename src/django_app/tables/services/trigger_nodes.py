"""Trigger nodes (webhook, Telegram, schedule): who may write them, and where they are.

Which node types are triggers is declared once, by `starts_runs` in the bulk-save
NODE_TYPE_REGISTRY; everything here derives from it. A trigger node starts flow runs
by itself, so writing one — directly, or by copying, importing or restoring a flow
that holds one — requires USE on flows (`TriggerNodeAccess`, shared as
`trigger_node_access`). `TriggerNodeInspector` answers whether a source holds a
trigger node, and which flows hold one on a webhook trigger. The module-level
functions answer whether running a piece of code needs USE because a trigger node
owns it.
"""

from collections.abc import Iterable

from django.db.models import Q, QuerySet
from rbac.access.effective import EffectivePermissions
from rbac.access.resolver import PermissionResolver
from rbac.models.enums import Permission, ResourceType
from tables.exceptions import (
    FlowWithTriggerNodesRequiresUsePermissionError,
    TriggerNodesRequireUsePermissionError,
)
from tables.import_export.enums import EntityType
from tables.import_export.strategies.nodes.node_maps import NODE_RELATIONS
from tables.models import Graph, PythonCode, WebhookTrigger
from tables.services.graph_bulk_save_service.registry import (
    TRIGGER_NODE_LIST_KEYS,
    TRIGGER_NODE_MODELS,
)

# The trigger node types as an export file or a version snapshot names them, in a
# node's `node_type` (full flow export, snapshot) or as a top-level key (partial export).
TRIGGER_NODE_TYPES: frozenset[str] = frozenset(
    node_type
    for node_type, relation_name in NODE_RELATIONS.items()
    if relation_name in TRIGGER_NODE_LIST_KEYS
)


class TriggerNodeAccess:
    """Who may write trigger nodes: the flows:USE gates around them.

    The resolver decides; superadmin passes through it, never through a check here.
    """

    def __init__(self, resolver: PermissionResolver | None = None):
        self._resolver = resolver or PermissionResolver()

    def assert_may_write(self, user, org_id: int) -> None:
        """Assert `user` may create or edit trigger nodes in `org_id`.

        For the bulk flow save and the trigger node endpoints. Deleting a trigger node
        needs no USE: it stops runs.

        Raises:
            OrgMembershipRequiredError (403): `user` is not a member of `org_id`.
            TriggerNodesRequireUsePermissionError (403): the role lacks USE on flows.
        """
        effective_permissions = self._resolver.resolve(user=user, org_id=org_id)
        if not effective_permissions.can(ResourceType.FLOWS, Permission.USE):
            raise TriggerNodesRequireUsePermissionError()

    def assert_may_recreate(self, effective_permissions: EffectivePermissions) -> None:
        """Assert the caller may copy, import or restore a flow that holds trigger nodes.

        Call it only once the source is known to hold a trigger node, before writing.
        For callers that already hold resolved permissions (the import services).

        Raises:
            FlowWithTriggerNodesRequiresUsePermissionError (403): the role lacks USE on
                flows.
        """
        if not effective_permissions.can(ResourceType.FLOWS, Permission.USE):
            raise FlowWithTriggerNodesRequiresUsePermissionError()

    def assert_user_may_recreate(self, user, org_id: int) -> None:
        """Resolve `user` in `org_id`, then apply `assert_may_recreate`."""
        self.assert_may_recreate(self._resolver.resolve(user=user, org_id=org_id))


trigger_node_access = TriggerNodeAccess()


# (model, field) for every WebhookTrigger foreign key on a trigger node type.
_TRIGGER_NODE_WEBHOOK_TRIGGER_FIELDS: tuple[tuple[type, str], ...] = tuple(
    (model, field.name)
    for model in TRIGGER_NODE_MODELS
    for field in model._meta.get_fields()
    if field.many_to_one and field.related_model is WebhookTrigger
)


class TriggerNodeInspector:
    """Whether a source holds a trigger node, one question per source shape.

    Stateless: a stored flow, a stored webhook trigger, a list of exported node
    entries, one exported flow or version snapshot, or a full import file. For a
    webhook trigger it also names the flows holding those nodes.
    """

    @staticmethod
    def has_any_in_graph(graph: Graph) -> bool:
        """Return whether a stored flow has a live trigger node.

        Uses the graph's prefetched node lists when present; otherwise one EXISTS query
        per trigger node type, stopping at the first hit.
        """
        return any(
            getattr(graph, relation_name).exists() for relation_name in TRIGGER_NODE_LIST_KEYS
        )

    @staticmethod
    def has_any_attached_to_webhook_trigger(webhook_trigger: WebhookTrigger) -> bool:
        """Return whether a live trigger node receives deliveries through this trigger.

        Changing such a trigger's auth, path or tunnel can bring those nodes live, so
        it is a trigger-node write. Soft-deleted nodes don't count. One EXISTS query
        per trigger node type that can point at a webhook trigger.
        """
        return any(
            model.objects.filter(**{field_name: webhook_trigger}).exists()
            for model, field_name in _TRIGGER_NODE_WEBHOOK_TRIGGER_FIELDS
        )

    @staticmethod
    def graphs_attached_to_webhook_trigger(webhook_trigger: WebhookTrigger) -> QuerySet[Graph]:
        """Return the live flows of the trigger's org with a live trigger node on this trigger.

        Each flow appears once, however many of its trigger nodes use the trigger.
        Soft-deleted flows and nodes don't count. Unevaluated and unordered: one
        query per evaluation, each node type joined in as an `IN` subquery.
        """
        # Starts as match-nothing: an empty Q() would match every flow of the org if no
        # trigger node type pointed at a webhook trigger.
        attached_to_trigger = Q(pk__in=[])
        for model, field_name in _TRIGGER_NODE_WEBHOOK_TRIGGER_FIELDS:
            attached_to_trigger |= Q(
                id__in=model.objects.filter(**{field_name: webhook_trigger}).values("graph_id")
            )
        return Graph.objects.filter(attached_to_trigger, org_id=webhook_trigger.org_id)

    @staticmethod
    def has_any_in_node_entries(node_entries: Iterable[dict]) -> bool:
        """Return whether any exported node entry, tagged with its `node_type`, is a trigger."""
        return any(node.get("node_type") in TRIGGER_NODE_TYPES for node in node_entries)

    @classmethod
    def has_any_in_flow_entry(cls, flow_entry: dict) -> bool:
        """Return whether one exported flow, or a version snapshot, holds a trigger node."""
        return cls.has_any_in_node_entries(flow_entry.get("nodes", []))

    @classmethod
    def has_any_in_export(cls, export_data: dict) -> bool:
        """Return whether a full import file holds a trigger node, in any flow or loose.

        `ImportService` imports both: the flows under `Flow` (subflows included) and any
        top-level node list. A partial import imports only its collected node entries,
        so it judges those with `has_any_in_node_entries` instead.
        """
        if any(export_data.get(node_type) for node_type in TRIGGER_NODE_TYPES):
            return True
        return any(
            cls.has_any_in_flow_entry(flow) for flow in export_data.get(EntityType.GRAPH, [])
        )


def is_trigger_node_model(model: type) -> bool:
    """Return whether `model` is a trigger node type; running its code needs FLOWS.USE."""
    return model in TRIGGER_NODE_MODELS


# (model, field) for every PythonCode foreign key on a trigger node type.
_TRIGGER_NODE_PYTHON_CODE_FIELDS: tuple[tuple[type, str], ...] = tuple(
    (model, field.name)
    for model in TRIGGER_NODE_MODELS
    for field in model._meta.get_fields()
    if field.many_to_one and field.related_model is PythonCode
)


def trigger_node_owns_python_code(python_code_id: int, org_id: int) -> bool:
    """Return whether a live trigger node in `org_id` holds this PythonCode.

    Running such code needs FLOWS.USE however the request names it, by the code's id
    or by the node's code slot. One EXISTS query per trigger PythonCode field.
    """
    return any(
        model.objects.filter(graph__org_id=org_id, **{field_name: python_code_id}).exists()
        for model, field_name in _TRIGGER_NODE_PYTHON_CODE_FIELDS
    )
