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

_AGENT_FIELDS = ("llm_config_id", "fcm_llm_config_id")


class LLMConfigDeleteService(BaseDeleteService):
    """Delete service for LLMConfig: usage is agents, flows and collections.

    `TemplateAgent` and the global `DefaultModels` / `DefaultCrewConfig` /
    `DefaultAgentConfig` fields are not counted: they have no resource type to
    check the caller's visibility against. Agent and task nodes reach a config
    only through their AgentDefinition, already in the agents bucket.
    """

    model = LLMConfig

    def collect_usage(self, ids: list[int]) -> dict[int, UsageReport]:
        """Agents, flows and collections referencing each config."""
        agents = BucketCollector.for_resource(ResourceType.AGENTS, self.permissions)
        flows = BucketCollector.for_resource(ResourceType.FLOWS, self.permissions)
        collections = BucketCollector.for_resource(ResourceType.KNOWLEDGE_SOURCES, self.permissions)

        if ids:
            self._collect_agents(agents, ids)
            self._collect_flows(flows, ids)
            self._collect_collections(collections, ids)

        return build_reports(ids, [agents, flows, collections])

    def _collect_agents(self, bucket: BucketCollector, ids: list[int]) -> None:
        """`AgentDefinition`, via both of its LLM-config FKs."""
        for field in _AGENT_FIELDS:
            bucket.add_rows(
                AgentDefinition.objects.filter(
                    org_id=self.org_id, **{f"{field}__in": ids}
                ).values_list(field, "id", "name")
            )

    def _collect_flows(self, bucket: BucketCollector, ids: list[int]) -> None:
        """The containing Flow of each decision-table node, prompt and assistant."""
        bucket.add_rows(
            ClassificationDecisionTableNode.objects.filter(
                graph__org_id=self.org_id, default_llm_config_id__in=ids
            )
            .values_list("default_llm_config_id", "graph_id", "graph__name")
            .distinct()
        )
        bucket.add_rows(
            ClassificationDecisionTablePrompt.objects.filter(
                cdt_node__graph__org_id=self.org_id, llm_config_id__in=ids
            )
            .values_list("llm_config_id", "cdt_node__graph_id", "cdt_node__graph__name")
            .distinct()
        )
        bucket.add_rows(
            FlowAssistant.objects.filter(graph__org_id=self.org_id, llm_config_id__in=ids)
            .values_list("llm_config_id", "graph_id", "graph__name")
            .distinct()
        )

    def _collect_collections(self, bucket: BucketCollector, ids: list[int]) -> None:
        """The containing SourceCollection of each GraphRag using the config."""
        bucket.add_rows(
            GraphRag.objects.filter(
                base_rag_type__source_collection__org_id=self.org_id, llm_id__in=ids
            )
            .values_list(
                "llm_id",
                "base_rag_type__source_collection__collection_id",
                "base_rag_type__source_collection__collection_name",
            )
            .distinct()
        )
