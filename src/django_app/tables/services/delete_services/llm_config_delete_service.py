from agents.models import AgentDefinition
from tables.models import Agent, ClassificationDecisionTablePrompt, Crew, LLMConfig
from tables.models.flow_assistant_models import FlowAssistant
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.rbac_models.rbac_enums import ResourceType
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    RefKind,
    UsageReport,
    build_reports,
)
from tables.services.rbac.effective_permissions import EffectivePermissions

_AGENT_FIELDS = ("llm_config_id", "fcm_llm_config_id")
_CREW_FIELDS = (
    "manager_llm_config_id",
    "memory_llm_config_id",
    "planning_llm_config_id",
)


class LLMConfigDeleteService(BaseDeleteService):
    """Delete service for LLMConfig entities.

    Four buckets over eleven FK columns in seven models. Several paths routinely
    reach the same parent -- a Crew naming one config as manager, memory and
    planning model, a Flow reaching it through both a decision-table node and an
    assistant -- and BucketCollector folds each such parent into one reference.

    The AGENTS bucket merges the deprecated `tables.Agent` with
    `agents.AgentDefinition`. Their ids come from different sequences, which is
    why references are keyed on `(kind, id)`: Agent#5 and AgentDefinition#5 are
    two parents. `tables.Agent` and `tables.Crew` still count as usage despite
    having no API or UI: existing flows with a CrewNode keep executing, so a
    config they reference is a live dependency.

    Deliberately not counted: `TemplateAgent.*` and the global `DefaultModels` /
    `DefaultCrewConfig` / `DefaultAgentConfig` singleton fields -- they have no
    ViewSet or resource type to check the caller's visibility against.

    Flow nodes that run an agent (`AgentNode` / `TaskNode`) need no FLOWS source
    of their own: they reach an LLM config through `AgentDefinition.llm_config` /
    `fcm_llm_config`, already in AGENTS.
    """

    model = LLMConfig

    def collect_usage(
        self, ids: list[int], org_id: int, effective: EffectivePermissions
    ) -> dict[int, UsageReport]:
        """Agents, crews, flows and collections referencing each config."""
        agents = BucketCollector.for_resource(ResourceType.AGENTS, effective)
        crews = BucketCollector.for_resource(ResourceType.PROJECTS, effective)
        flows = BucketCollector.for_resource(ResourceType.FLOWS, effective)
        collections = BucketCollector.for_resource(
            ResourceType.KNOWLEDGE_SOURCES, effective
        )

        if ids:
            self._collect_agents(agents, ids, org_id)
            self._collect_crews(crews, ids, org_id)
            self._collect_flows(flows, ids, org_id)
            self._collect_collections(collections, ids, org_id)

        return build_reports(ids, [agents, crews, flows, collections])

    @staticmethod
    def _collect_agents(bucket: BucketCollector, ids: list[int], org_id: int) -> None:
        """Legacy `tables.Agent` and `AgentDefinition`, each via two FK fields."""
        for field in _AGENT_FIELDS:
            bucket.add_rows(
                Agent.objects.filter(
                    org_id=org_id, **{f"{field}__in": ids}
                ).values_list(field, "id", "role"),
                kind=RefKind.AGENT,
            )
            bucket.add_rows(
                AgentDefinition.objects.filter(
                    organization_id=org_id, **{f"{field}__in": ids}
                ).values_list(field, "id", "name"),
                kind=RefKind.AGENT_DEFINITION,
            )

    @staticmethod
    def _collect_crews(bucket: BucketCollector, ids: list[int], org_id: int) -> None:
        """Deprecated `tables.Crew`, via its manager, memory and planning FKs."""
        for field in _CREW_FIELDS:
            bucket.add_rows(
                Crew.objects.filter(org_id=org_id, **{f"{field}__in": ids}).values_list(
                    field, "id", "name"
                ),
                kind=RefKind.CREW,
            )

    @staticmethod
    def _collect_flows(bucket: BucketCollector, ids: list[int], org_id: int) -> None:
        """The containing Flow, reached through three sources.

        The sample names the Flow, not the node, prompt or assistant row -- the
        Flow is the unit a caller recognises and holds permissions on.
        """
        bucket.add_rows(
            ClassificationDecisionTableNode.objects.filter(
                graph__org_id=org_id, default_llm_config_id__in=ids
            )
            .values_list("default_llm_config_id", "graph_id", "graph__name")
            .distinct(),
            kind=RefKind.FLOW,
        )
        bucket.add_rows(
            ClassificationDecisionTablePrompt.objects.filter(
                cdt_node__graph__org_id=org_id, llm_config_id__in=ids
            )
            .values_list("llm_config_id", "cdt_node__graph_id", "cdt_node__graph__name")
            .distinct(),
            kind=RefKind.FLOW,
        )
        bucket.add_rows(
            FlowAssistant.objects.filter(graph__org_id=org_id, llm_config_id__in=ids)
            .values_list("llm_config_id", "graph_id", "graph__name")
            .distinct(),
            kind=RefKind.FLOW,
        )

    @staticmethod
    def _collect_collections(
        bucket: BucketCollector, ids: list[int], org_id: int
    ) -> None:
        """The containing SourceCollection of each GraphRag using the config.

        The collection, not the internal GraphRag row, is the unit a caller
        recognises and holds permissions on.
        """
        bucket.add_rows(
            GraphRag.objects.filter(
                base_rag_type__source_collection__org_id=org_id, llm_id__in=ids
            )
            .values_list(
                "llm_id",
                "base_rag_type__source_collection__collection_id",
                "base_rag_type__source_collection__collection_name",
            )
            .distinct(),
            kind=RefKind.COLLECTION,
        )
