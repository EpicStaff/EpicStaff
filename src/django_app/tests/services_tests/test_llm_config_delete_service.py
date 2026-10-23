"""Service-level tests for LLMConfigDeleteService.

LLMConfig is where the usage rules earn their keep: three buckets over six FK
columns, and the same parent reachable several ways.
"""

import pytest

from agents.models import AgentDefinition
from tables.models import (
    Agent,
    Crew,
    Graph,
    LLMConfig,
)
from tables.models.flow_assistant_models import FlowAssistant
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
)
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.knowledge_models.graphrag_models import GraphRag
from rbac.models import Organization
from rbac.models.enums import Permission, ResourceType
from tables.services.delete_services import LLMConfigDeleteService
from tables.services.delete_services.usage import RefKind, SkipEntry, SkipReason
from rbac.access.effective import EffectivePermissions


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _config(org, name="cfg"):
    return LLMConfig.objects.create(org=org, custom_name=name)


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


def _can_read(*resource_types):
    return EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={rt.value: int(Permission.READ) for rt in resource_types},
    )


_ALL_BUCKETS = (
    ResourceType.AGENTS,
    ResourceType.FLOWS,
    ResourceType.KNOWLEDGE_SOURCES,
)


def _bucket(result, config_id, resource_type):
    return next(
        bucket
        for bucket in result.usage[config_id].buckets
        if bucket.resource_type == resource_type.value
    )


@pytest.mark.django_db
def test_agent_using_one_config_as_both_models_is_one_agent(org_a):
    """`llm_config` and `fcm_llm_config` on the same config are one agent, not two."""
    config = _config(org_a)
    agent = AgentDefinition.objects.create(
        org=org_a, name="bot", llm_config=config, fcm_llm_config=config
    )

    result = LLMConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read(*_ALL_BUCKETS), dry_run=True, deleted_by=None
    )

    agents = _bucket(result, config.id, ResourceType.AGENTS)
    assert [(ref.kind, ref.id, ref.name) for ref in agents.visible_refs] == [
        (RefKind.AGENT, agent.id, "bot")
    ]


@pytest.mark.django_db
def test_flow_reached_through_a_node_and_an_assistant_is_one_flow(org_a):
    """The containing flow is reported once, whichever path found it."""
    config = _config(org_a)
    graph = _graph(org_a, "support")
    ClassificationDecisionTableNode.objects.create(
        graph=graph, default_llm_config=config
    )
    FlowAssistant.objects.create(graph=graph, llm_config=config)

    result = LLMConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read(*_ALL_BUCKETS), dry_run=True, deleted_by=None
    )

    flows = _bucket(result, config.id, ResourceType.FLOWS)
    assert flows.visible_count == 1
    assert (flows.visible_refs[0].kind, flows.visible_refs[0].id) == (
        RefKind.FLOW,
        graph.id,
    )


@pytest.mark.django_db
def test_graph_rag_reports_its_collection(org_a):
    config = _config(org_a)
    collection = SourceCollection.objects.create(org=org_a, collection_name="Docs")
    rag_type = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(base_rag_type=rag_type, llm=config)

    result = LLMConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read(*_ALL_BUCKETS), dry_run=True, deleted_by=None
    )

    knowledge = _bucket(result, config.id, ResourceType.KNOWLEDGE_SOURCES)
    assert [(ref.kind, ref.name) for ref in knowledge.visible_refs] == [
        (RefKind.COLLECTION, "Docs")
    ]


@pytest.mark.django_db
def test_an_agent_the_caller_cannot_see_blocks(org_a):
    config = _config(org_a)
    AgentDefinition.objects.create(org=org_a, name="hidden", llm_config=config)
    everything_but_agents = _can_read(
        ResourceType.FLOWS, ResourceType.KNOWLEDGE_SOURCES
    )

    result = LLMConfigDeleteService().bulk_delete(
        [config.id], org_a.id, everything_but_agents, deleted_by=None
    )

    assert result.deleted_ids == []
    assert result.skipped == [
        SkipEntry(id=config.id, reason=SkipReason.IN_USE_RESTRICTED)
    ]
    assert LLMConfig.objects.filter(id=config.id).exists()


@pytest.mark.django_db
def test_deprecated_agent_and_crew_are_not_usage(org_a):
    """`tables.Agent` and `tables.Crew` have no API or UI, so they never block.

    A caller who can read nothing still deletes the config, and SET_NULL
    clears every legacy link.
    """
    config = _config(org_a)
    agent = Agent.objects.create(
        org=org_a,
        role="legacy",
        goal="g",
        backstory="b",
        llm_config=config,
        fcm_llm_config=config,
    )
    crew = Crew.objects.create(
        org=org_a,
        name="legacy",
        manager_llm_config=config,
        memory_llm_config=config,
        planning_llm_config=config,
    )

    result = LLMConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read(), deleted_by=None
    )

    assert result.deleted_ids == [config.id]
    agent.refresh_from_db()
    crew.refresh_from_db()
    assert (agent.llm_config_id, agent.fcm_llm_config_id) == (None, None)
    assert (
        crew.manager_llm_config_id,
        crew.memory_llm_config_id,
        crew.planning_llm_config_id,
    ) == (None, None, None)


@pytest.mark.django_db
def test_unreferenced_configs_are_removed_on_the_queryset_path(org_a):
    """LLMConfig is not a soft-delete root, so the whole batch goes in one delete."""
    first, second = _config(org_a, "a"), _config(org_a, "b")

    result = LLMConfigDeleteService().bulk_delete(
        [first.id, second.id], org_a.id, _can_read(*_ALL_BUCKETS), deleted_by=None
    )

    assert sorted(result.deleted_ids) == sorted([first.id, second.id])
    assert not LLMConfig.objects.filter(id__in=[first.id, second.id]).exists()


@pytest.mark.django_db
def test_another_orgs_references_are_not_usage(org_a, org_b):
    """Every one of the 6 source queries filters the referencing row by org.

    Each source below lives in org B and points at org A's config. Cross-org
    FKs cannot be created through the API, but the guard must not depend on
    that: a single missing `org_id=` filter would put another org's agent,
    flow or collection name in this org's preview.
    """
    config = _config(org_a)
    AgentDefinition.objects.create(
        org=org_b, name="foreign", llm_config=config, fcm_llm_config=config
    )
    graph = _graph(org_b, "foreign")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph, default_llm_config=config
    )
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=node, prompt_key="p", llm_config=config
    )
    FlowAssistant.objects.create(graph=graph, llm_config=config)
    collection = SourceCollection.objects.create(org=org_b, collection_name="foreign")
    rag_type = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(base_rag_type=rag_type, llm=config)

    preview = LLMConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read(*_ALL_BUCKETS), dry_run=True, deleted_by=None
    )
    assert {
        bucket.resource_type: bucket.total_count
        for bucket in preview.usage[config.id].buckets
    } == {resource_type.value: 0 for resource_type in _ALL_BUCKETS}

    result = LLMConfigDeleteService().bulk_delete([config.id], org_a.id, _can_read(), deleted_by=None)
    assert result.deleted_ids == [config.id]
