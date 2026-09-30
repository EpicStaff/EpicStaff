"""Service-level tests for LLMConfigDeleteService.

LLMConfig is where the usage rules earn their keep: four buckets over eleven FK
columns, the same parent reachable several ways, and an AGENTS bucket that
merges two tables whose ids overlap -- the `(kind, id)` case.
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
from tables.models.rbac_models import Organization
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.delete_services import LLMConfigDeleteService
from tables.services.delete_services.usage import RefKind, SkipEntry, SkipReason
from tables.services.rbac.effective_permissions import EffectivePermissions


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
    ResourceType.PROJECTS,
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
def test_agent_and_agent_definition_sharing_an_id_stay_two_references(org_a):
    """The `(kind, id)` key, end to end.

    `tables.Agent` and `AgentDefinition` ids come from different sequences.
    Pinning both to the same id is exactly the collision a bare-id dedup key
    would silently fold into one reference.
    """
    config = _config(org_a)
    Agent.objects.create(
        id=9001, org=org_a, role="legacy", goal="g", backstory="b", llm_config=config
    )
    AgentDefinition.objects.create(
        id=9001, organization=org_a, name="current", llm_config=config
    )

    result = LLMConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read(*_ALL_BUCKETS), dry_run=True
    )

    agents = _bucket(result, config.id, ResourceType.AGENTS)
    assert agents.visible_count == 2
    assert {(ref.kind, ref.id) for ref in agents.visible_refs} == {
        (RefKind.AGENT, 9001),
        (RefKind.AGENT_DEFINITION, 9001),
    }


@pytest.mark.django_db
def test_crew_using_one_config_three_ways_is_one_project(org_a):
    """Manager, memory and planning on the same config are one crew, not three."""
    config = _config(org_a)
    Crew.objects.create(
        org=org_a,
        name="crew",
        manager_llm_config=config,
        memory_llm_config=config,
        planning_llm_config=config,
    )

    result = LLMConfigDeleteService().bulk_delete(
        [config.id], org_a.id, _can_read(*_ALL_BUCKETS), dry_run=True
    )

    projects = _bucket(result, config.id, ResourceType.PROJECTS)
    assert projects.visible_count == 1
    assert projects.visible_refs[0].kind == RefKind.CREW


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
        [config.id], org_a.id, _can_read(*_ALL_BUCKETS), dry_run=True
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
        [config.id], org_a.id, _can_read(*_ALL_BUCKETS), dry_run=True
    )

    knowledge = _bucket(result, config.id, ResourceType.KNOWLEDGE_SOURCES)
    assert [(ref.kind, ref.name) for ref in knowledge.visible_refs] == [
        (RefKind.COLLECTION, "Docs")
    ]


@pytest.mark.django_db
def test_deprecated_agent_the_caller_cannot_see_still_blocks(org_a):
    """Legacy `tables.Agent` counts: old flows with a CrewNode still execute."""
    config = _config(org_a)
    Agent.objects.create(
        org=org_a, role="r", goal="g", backstory="b", llm_config=config
    )
    everything_but_agents = _can_read(
        ResourceType.PROJECTS, ResourceType.FLOWS, ResourceType.KNOWLEDGE_SOURCES
    )

    result = LLMConfigDeleteService().bulk_delete(
        [config.id], org_a.id, everything_but_agents
    )

    assert result.deleted_ids == []
    assert result.skipped == [
        SkipEntry(id=config.id, reason=SkipReason.IN_USE_RESTRICTED)
    ]
    assert LLMConfig.objects.filter(id=config.id).exists()


@pytest.mark.django_db
def test_unreferenced_configs_are_removed_on_the_queryset_path(org_a):
    """LLMConfig is not a soft-delete root, so the whole batch goes in one delete."""
    first, second = _config(org_a, "a"), _config(org_a, "b")

    result = LLMConfigDeleteService().bulk_delete(
        [first.id, second.id], org_a.id, _can_read(*_ALL_BUCKETS)
    )

    assert sorted(result.deleted_ids) == sorted([first.id, second.id])
    assert not LLMConfig.objects.filter(id__in=[first.id, second.id]).exists()


@pytest.mark.django_db
def test_another_orgs_references_are_not_usage(org_a, org_b):
    """Every one of the 11 source queries filters the referencing row by org.

    Each source below lives in org B and points at org A's config. Cross-org
    FKs cannot be created through the API, but the guard must not depend on
    that: a single missing `org_id=` filter would put another org's agent,
    crew, flow or collection name in this org's preview.
    """
    config = _config(org_a)
    Agent.objects.create(
        org=org_b,
        role="foreign",
        goal="g",
        backstory="b",
        llm_config=config,
        fcm_llm_config=config,
    )
    AgentDefinition.objects.create(
        organization=org_b, name="foreign", llm_config=config, fcm_llm_config=config
    )
    Crew.objects.create(
        org=org_b,
        name="foreign",
        manager_llm_config=config,
        memory_llm_config=config,
        planning_llm_config=config,
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
        [config.id], org_a.id, _can_read(*_ALL_BUCKETS), dry_run=True
    )
    assert {
        bucket.resource_type: bucket.total_count
        for bucket in preview.usage[config.id].buckets
    } == {resource_type.value: 0 for resource_type in _ALL_BUCKETS}

    result = LLMConfigDeleteService().bulk_delete([config.id], org_a.id, _can_read())
    assert result.deleted_ids == [config.id]
