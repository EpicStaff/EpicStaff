"""What suspending a grant would stop, for the SuperAdmin to read before confirming.

The flows, realtime agents and voice channels it lists are matched by the run guard's rule
(`OwnedResourceIndex`), against every row owned under the grant: with this grant the only
non-active one in its organization, the guard refuses exactly the flows listed here.
"""

from dataclasses import dataclass
from datetime import datetime

from agents.models import AgentDefinition
from django.db.models import Exists, ForeignKey, OuterRef
from django.db.models.functions import Lower
from django.utils import timezone
from tables.models import (
    DefaultModels,
    Graph,
    RealtimeAgentDefinition,
    RealtimeChannel,
    ScheduleTriggerNode,
    Session,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.services.run_admission import RunKind
from tables.services.run_resources import RunResourceCollector

from plugins.configuration.grace_period import grace_period
from plugins.exceptions import GrantNotFoundError
from plugins.lifecycle.suspended_run_stopper import OPEN_SESSION_STATES
from plugins.models import PluginGrant
from plugins.ownership.owned_resource_summary import (
    OWNED_RESOURCE_LABELS,
    owned_resource_summary,
)
from plugins.runs.owned_resource_index import OwnedResourceIndex

PREVIEW_LIST_LIMIT = 100
GRAPH = Graph._meta.label


@dataclass(frozen=True)
class NamedRow:
    id: int
    name: str


@dataclass(frozen=True)
class PreviewList:
    """At most `PREVIEW_LIST_LIMIT` items of a list, sorted by name then id, and its length."""

    total: int
    items: list


@dataclass(frozen=True)
class PreviewSession:
    id: int
    flow: NamedRow
    status: str
    created_at: datetime


@dataclass(frozen=True)
class PreviewTrigger:
    kind: str
    node_id: int
    node_name: str
    flow: NamedRow


@dataclass(frozen=True)
class PreviewDefaultModel:
    setting: str
    config: NamedRow


@dataclass(frozen=True)
class SuspendPreview:
    grant: PluginGrant
    data_kept_until: datetime
    owned_resources: list[dict]
    organization_flows: PreviewList
    plugin_flows: PreviewList
    running_sessions: PreviewList
    triggers: PreviewList
    realtime_agents: PreviewList
    voice_channels: PreviewList
    default_models: list[PreviewDefaultModel]


# Trigger nodes a stopping flow keeps receiving events on, and which of them count: an
# inactive schedule never fires.
_TRIGGER_NODES = (
    ("schedule", ScheduleTriggerNode, {"is_active": True}),
    ("webhook", WebhookTriggerNode, {}),
    ("telegram", TelegramTriggerNode, {}),
)


class SuspendPreviewService:
    def build(self, identifier: str, grant_id: int) -> SuspendPreview:
        """What suspending the grant stops, in any state of it; reads only, creates nothing.

        The number of queries does not depend on how many flows, agents, channels or owned
        rows there are.

        Raises:
            GrantNotFoundError: No such grant of this plugin.
        """
        grant = (
            PluginGrant.objects.select_related("plugin", "org")
            .filter(pk=grant_id, plugin__identifier=identifier)
            .first()
        )
        if grant is None:
            raise GrantNotFoundError()
        index = OwnedResourceIndex.for_grant(grant)
        organization_id = grant.org_id
        stopping_flows = _matching(
            index, RunKind.FLOW, Graph.objects.filter(org_id=organization_id)
        )
        # The plugin's own flows are the ones whose row it owns; the rest are the
        # organization's, and stop only because they use something the plugin owns.
        plugin_flows = [flow for flow in stopping_flows if index.holds(GRAPH, flow.id)]
        organization_flows = [flow for flow in stopping_flows if not index.holds(GRAPH, flow.id)]
        realtime_agents = _matching(
            index,
            RunKind.REALTIME,
            AgentDefinition.objects.filter(org_id=organization_id).filter(
                Exists(RealtimeAgentDefinition.objects.filter(agent_definition=OuterRef("pk")))
            ),
        )
        voice_channels = _matching(
            index, RunKind.VOICE_CHANNEL, RealtimeChannel.objects.filter(org_id=organization_id)
        )
        return SuspendPreview(
            grant=grant,
            data_kept_until=grant.purge_after or timezone.now() + grace_period(),
            owned_resources=owned_resource_summary(grant),
            organization_flows=_limited(organization_flows),
            plugin_flows=_limited(plugin_flows),
            running_sessions=_running_sessions(stopping_flows),
            triggers=_triggers(stopping_flows),
            realtime_agents=_limited(realtime_agents),
            voice_channels=_limited(voice_channels),
            default_models=_default_models(index, organization_id),
        )


def _matching(index: OwnedResourceIndex, kind: RunKind, rows) -> list[NamedRow]:
    """The rows whose run would use something the index holds, sorted by name then id."""
    if index.is_empty:
        return []
    named = [NamedRow(id=pk, name=name) for pk, name in rows.values_list("pk", "name")]
    resources = RunResourceCollector().collect_many(kind, [row.id for row in named])
    return _sorted(row for row in named if index.first_owner(resources[row.id]) is not None)


def _sorted(rows) -> list[NamedRow]:
    return sorted(rows, key=lambda row: (row.name.casefold(), row.id))


def _limited(items: list) -> PreviewList:
    return PreviewList(total=len(items), items=items[:PREVIEW_LIST_LIMIT])


def _running_sessions(flows: list[NamedRow]) -> PreviewList:
    if not flows:
        return PreviewList(total=0, items=[])
    flows_by_id = {flow.id: flow for flow in flows}
    sessions = Session.objects.filter(graph_id__in=flows_by_id, status__in=OPEN_SESSION_STATES)
    page = sessions.order_by(Lower("graph__name"), "graph_id", "pk").values_list(
        "pk", "graph_id", "status", "created_at"
    )[:PREVIEW_LIST_LIMIT]
    return PreviewList(
        total=sessions.count(),
        items=[
            PreviewSession(id=pk, flow=flows_by_id[graph_id], status=status, created_at=created_at)
            for pk, graph_id, status, created_at in page
        ],
    )


def _triggers(flows: list[NamedRow]) -> PreviewList:
    if not flows:
        return PreviewList(total=0, items=[])
    flows_by_id = {flow.id: flow for flow in flows}
    triggers = [
        PreviewTrigger(kind=kind, node_id=pk, node_name=node_name, flow=flows_by_id[graph_id])
        for kind, model, conditions in _TRIGGER_NODES
        for pk, node_name, graph_id in model.objects.filter(
            graph_id__in=flows_by_id, **conditions
        ).values_list("pk", "node_name", "graph_id")
    ]
    triggers.sort(key=lambda trigger: (trigger.node_name.casefold(), trigger.node_id, trigger.kind))
    return _limited(triggers)


def _default_models(index: OwnedResourceIndex, organization_id: int) -> list[PreviewDefaultModel]:
    """The organization's default-model settings that point at a config the index holds.

    Read with `filter().first()`, never `load_for_org`, so a preview never creates the row.
    """
    if index.is_empty:
        return []
    settings = [
        field
        for field in DefaultModels._meta.concrete_fields
        if isinstance(field, ForeignKey)
        and field.related_model._meta.label in OWNED_RESOURCE_LABELS
    ]
    row = (
        DefaultModels.objects.filter(org_id=organization_id)
        .select_related(*(field.name for field in settings))
        .first()
    )
    if row is None:
        return []
    return [
        PreviewDefaultModel(
            setting=field.name,
            config=NamedRow(id=config.pk, name=config.custom_name),
        )
        for field in settings
        if (config := getattr(row, field.name)) is not None
        and index.holds(field.related_model._meta.label, config.pk)
    ]
