from agents.models import AgentDefinition
from rbac.models.enums import ResourceType
from tables.models import ClassificationDecisionTablePrompt, LLMConfig
from tables.models.flow_assistant_models import FlowAssistant
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    UsageReport,
    build_reports,
)


class LLMConfigDeleteService(BaseDeleteService):
    """Delete service for LLMConfig entities.

    Three buckets over six FK columns in five models. Several paths routinely
    reach the same parent -- an AgentDefinition naming one config as both its
    primary and its tool-call model, a Flow reaching it through both a
    decision-table node and an assistant -- and BucketCollector folds each such
    parent into one reference.

    Deliberately not counted: `TemplateAgent.*` and the global `DefaultModels` /
    `DefaultCrewConfig` / `DefaultAgentConfig` singleton fields -- they have no
    ViewSet or resource type to check the caller's visibility against.

    Flow nodes that run an agent (`AgentNode` / `TaskNode`) need no FLOWS source
    of their own: they reach an LLM config through `AgentDefinition.llm_config` /
    `fcm_llm_config`, already in AGENTS.
    """

    model = LLMConfig
    agent_fields = ("llm_config_id", "fcm_llm_config_id")

    def collect_usage(self, ids: list[int]) -> dict[int, UsageReport]:
        """Agents, flows and collections referencing each config."""
        agents = BucketCollector.for_resource(ResourceType.AGENTS, self.effective)
        flows = BucketCollector.for_resource(ResourceType.FLOWS, self.effective)
        collections = BucketCollector.for_resource(ResourceType.KNOWLEDGE_SOURCES, self.effective)

        if ids:
            self._collect_agents(agents, ids, self.org_id)
            self._collect_flows(flows, ids, self.org_id)
            self._collect_collections(collections, ids, self.org_id)

        return build_reports(ids, [agents, flows, collections])

    @classmethod
    def _collect_agents(cls, bucket: BucketCollector, ids: list[int], org_id: int) -> None:
        """`AgentDefinition`, via both of its LLM-config FKs."""
        for field in cls.agent_fields:
            bucket.add_rows(
                AgentDefinition.objects.filter(org_id=org_id, **{f"{field}__in": ids}).values_list(
                    field, "id", "name"
                ),
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
        )
        bucket.add_rows(
            ClassificationDecisionTablePrompt.objects.filter(
                cdt_node__graph__org_id=org_id, llm_config_id__in=ids
            )
            .values_list("llm_config_id", "cdt_node__graph_id", "cdt_node__graph__name")
            .distinct(),
        )
        bucket.add_rows(
            FlowAssistant.objects.filter(graph__org_id=org_id, llm_config_id__in=ids)
            .values_list("llm_config_id", "graph_id", "graph__name")
            .distinct(),
        )

    @staticmethod
    def _collect_collections(bucket: BucketCollector, ids: list[int], org_id: int) -> None:
        """The containing SourceCollection of each GraphRag using the config.

        The collection, not the internal GraphRag row, is the unit a caller
        recognises and holds permissions on.
        """
        bucket.add_rows(
            GraphRag.objects.filter(base_rag_type__source_collection__org_id=org_id, llm_id__in=ids)
            .values_list(
                "llm_id",
                "base_rag_type__source_collection__collection_id",
                "base_rag_type__source_collection__collection_name",
            )
            .distinct(),
        )
