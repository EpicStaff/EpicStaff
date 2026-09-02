"""Iteration 5 of the backend bulk-delete rollout: LLMConfigReadWriteViewSet.

Unlike Graph/Crew/Agent, LLMConfig has FOUR referencing resource-type
buckets: AGENTS (old Agent + new agents.AgentDefinition, merged),
PROJECTS (Crew's three llm_config-ish fields, merged), FLOWS
(ClassificationDecisionTableNode/Prompt + FlowAssistant, merged), and
KNOWLEDGE_SOURCES (GraphRag.llm). `blocked` is true if ANY bucket has a
hidden portion; each bucket's `visible_sample` is independent.
"""

import pytest
from rest_framework.test import APIClient

from agents.models import AgentDefinition
from tables.models import (
    Agent,
    ClassificationDecisionTablePrompt,
    Crew,
    Graph,
    LLMConfig,
)
from tables.models.flow_assistant_models import FlowAssistant
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.models.knowledge_models.collection_models import BaseRagType, SourceCollection
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.rbac_models import Organization, OrganizationUser, Role, RolePermission
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission, ResourceType


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _org_admin_client(django_user_model, org, email):
    role = Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


def _custom_role_client(django_user_model, org, email, **resource_permissions):
    role = Role.objects.create(name=f"custom-{email}", is_built_in=False, org=org)
    for resource_type, permissions in resource_permissions.items():
        RolePermission.objects.create(
            role=role, resource_type=resource_type, permissions=int(permissions)
        )
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


def _config(org, name="cfg"):
    return LLMConfig.objects.create(org=org, custom_name=name)


def _graph(org, name="g"):
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


def by_type(usage, resource_type):
    return next(
        s for s in usage["by_resource_type"] if s["resource_type"] == resource_type
    )


@pytest.mark.django_db
def test_bulk_delete_happy_path(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    c1, c2 = _config(org_a, "c1"), _config(org_a, "c2")

    resp = client.post(
        "/api/llm-configs/bulk-delete/", {"ids": [c1.id, c2.id]}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert sorted(resp.data["deleted_ids"]) == sorted([c1.id, c2.id])
    assert not LLMConfig.objects.filter(id__in=[c1.id, c2.id]).exists()


@pytest.mark.django_db
def test_bulk_delete_cross_org_id_not_found(django_user_model, org_a, org_b):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    other = _config(org_b, "other")

    resp = client.post(
        "/api/llm-configs/bulk-delete/", {"ids": [other.id]}, format="json"
    )

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [other.id]


@pytest.mark.django_db
def test_bulk_delete_nonexistent_id_not_found(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/llm-configs/bulk-delete/", {"ids": [999999]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["not_found_ids"] == [999999]


@pytest.mark.django_db
def test_bulk_delete_empty_ids_rejected(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")

    resp = client.post("/api/llm-configs/bulk-delete/", {"ids": []}, format="json")

    assert resp.status_code == 400


@pytest.mark.django_db
def test_bulk_delete_without_delete_permission_forbidden(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "viewer@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.READ},
    )
    c = _config(org_a, "c")

    resp = client.post("/api/llm-configs/bulk-delete/", {"ids": [c.id]}, format="json")

    assert resp.status_code == 403
    assert LLMConfig.objects.filter(id=c.id).exists()


@pytest.mark.django_db
def test_bulk_delete_agents_bucket_old_agent_visible_proceeds(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    config = _config(org_a, "c")
    agent = Agent.objects.create(
        org=org_a, role="r", goal="g", backstory="b", llm_config=config
    )

    resp = client.post("/api/llm-configs/bulk-delete/", {"ids": [config.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert not LLMConfig.objects.filter(id=config.id).exists()
    agent.refresh_from_db()
    assert agent.llm_config_id is None
    usage = resp.data["usage"][str(config.id)]
    agents_usage = by_type(usage, "agents")
    assert agents_usage["visible_count"] == 1
    assert agents_usage["visible_sample"] == [{"id": agent.id, "name": "r"}]


@pytest.mark.django_db
def test_bulk_delete_agents_bucket_new_agent_definition_visible_proceeds(
    django_user_model, org_a
):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    config = _config(org_a, "c")
    agent_def = AgentDefinition.objects.create(
        organization=org_a, name="ad1", llm_config=config
    )

    resp = client.post("/api/llm-configs/bulk-delete/", {"ids": [config.id]}, format="json")

    assert resp.status_code == 200, resp.data
    assert not LLMConfig.objects.filter(id=config.id).exists()
    agent_def.refresh_from_db()
    assert agent_def.llm_config_id is None
    usage = resp.data["usage"][str(config.id)]
    agents_usage = by_type(usage, "agents")
    assert agents_usage["visible_count"] == 1
    assert agents_usage["visible_sample"] == [{"id": agent_def.id, "name": "ad1"}]


@pytest.mark.django_db
def test_bulk_delete_agents_bucket_hidden_blocked(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "deleter@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE},
    )
    config = _config(org_a, "c")
    Agent.objects.create(org=org_a, role="r", goal="g", backstory="b", llm_config=config)

    resp = client.post("/api/llm-configs/bulk-delete/", {"ids": [config.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [{"id": config.id, "reason": "in_use_restricted"}]
    assert LLMConfig.objects.filter(id=config.id).exists()
    usage = resp.data["usage"][str(config.id)]
    assert usage["blocked"] is True
    assert by_type(usage, "agents")["visible_count"] == 0


@pytest.mark.django_db
def test_bulk_delete_projects_bucket_visible_proceeds(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    config = _config(org_a, "c")
    crew = Crew.objects.create(org=org_a, name="crew", manager_llm_config=config)

    resp = client.post("/api/llm-configs/bulk-delete/", {"ids": [config.id]}, format="json")

    assert resp.status_code == 200, resp.data
    crew.refresh_from_db()
    assert crew.manager_llm_config_id is None
    usage = resp.data["usage"][str(config.id)]
    projects_usage = by_type(usage, "projects")
    assert projects_usage["visible_sample"] == [{"id": crew.id, "name": crew.name}]


@pytest.mark.django_db
def test_bulk_delete_flows_bucket_visible_proceeds(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    config = _config(org_a, "c")
    graph = _graph(org_a, "flow")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph, default_llm_config=config
    )

    resp = client.post("/api/llm-configs/bulk-delete/", {"ids": [config.id]}, format="json")

    assert resp.status_code == 200, resp.data
    node.refresh_from_db()
    assert node.default_llm_config_id is None
    usage = resp.data["usage"][str(config.id)]
    flows_usage = by_type(usage, "flows")
    assert flows_usage["visible_sample"] == [{"id": graph.id, "name": graph.name}]


@pytest.mark.django_db
def test_bulk_delete_knowledge_sources_bucket_visible_and_hidden(django_user_model, org_a):
    admin = _org_admin_client(django_user_model, org_a, "admin@example.com")
    config = _config(org_a, "c")
    collection = SourceCollection.objects.create(org=org_a, collection_name="Docs")
    rag_type = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(base_rag_type=rag_type, llm=config)

    resp = admin.post("/api/llm-configs/bulk-delete/", {"ids": [config.id]}, format="json")
    assert resp.status_code == 200, resp.data
    usage = resp.data["usage"][str(config.id)]
    ks_usage = by_type(usage, "knowledge_sources")
    assert ks_usage["visible_sample"] == [
        {"id": collection.collection_id, "name": "Docs"}
    ]

    # Same setup, but the deleting user has no KNOWLEDGE_SOURCES:READ -> blocked.
    config2 = _config(org_a, "c2")
    collection2 = SourceCollection.objects.create(org=org_a, collection_name="Docs2")
    rag_type2 = BaseRagType.objects.create(
        source_collection=collection2, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(base_rag_type=rag_type2, llm=config2)
    deleter = _custom_role_client(
        django_user_model, org_a, "deleter2@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE},
    )
    resp2 = deleter.post(
        "/api/llm-configs/bulk-delete/", {"ids": [config2.id]}, format="json"
    )
    assert resp2.status_code == 207, resp2.data
    assert resp2.data["skipped_ids"] == [
        {"id": config2.id, "reason": "in_use_restricted"}
    ]


@pytest.mark.django_db
def test_bulk_delete_mixed_buckets_one_hidden_still_blocked(django_user_model, org_a):
    # Visible in AGENTS, hidden in KNOWLEDGE_SOURCES -> still blocked overall.
    client = _custom_role_client(
        django_user_model, org_a, "deleter3@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE, ResourceType.AGENTS: Permission.READ},
    )
    config = _config(org_a, "c")
    agent = Agent.objects.create(org=org_a, role="r", goal="g", backstory="b", llm_config=config)
    collection = SourceCollection.objects.create(org=org_a, collection_name="Docs")
    rag_type = BaseRagType.objects.create(
        source_collection=collection, rag_type=BaseRagType.RagType.GRAPH
    )
    GraphRag.objects.create(base_rag_type=rag_type, llm=config)

    resp = client.post("/api/llm-configs/bulk-delete/", {"ids": [config.id]}, format="json")

    assert resp.status_code == 207, resp.data
    assert resp.data["skipped_ids"] == [{"id": config.id, "reason": "in_use_restricted"}]
    usage = resp.data["usage"][str(config.id)]
    assert usage["blocked"] is True
    agents_usage = by_type(usage, "agents")
    assert agents_usage["visible_count"] == 1
    assert agents_usage["visible_sample"] == [{"id": agent.id, "name": "r"}]
    assert by_type(usage, "knowledge_sources")["visible_count"] == 0


@pytest.mark.django_db
def test_bulk_delete_dry_run_does_not_delete(django_user_model, org_a):
    client = _org_admin_client(django_user_model, org_a, "admin@example.com")
    config = _config(org_a, "c")

    resp = client.post(
        "/api/llm-configs/bulk-delete/", {"ids": [config.id], "dry_run": True}, format="json"
    )

    assert resp.status_code == 200, resp.data
    assert resp.data["dry_run"] is True
    assert LLMConfig.objects.filter(id=config.id).exists()


@pytest.mark.django_db
def test_single_destroy_hidden_usage_blocked(django_user_model, org_a):
    client = _custom_role_client(
        django_user_model, org_a, "deleter4@example.com",
        **{ResourceType.LLM_CONFIGS: Permission.DELETE},
    )
    config = _config(org_a, "c")
    Agent.objects.create(org=org_a, role="r", goal="g", backstory="b", llm_config=config)

    resp = client.delete(f"/api/llm-configs/{config.id}/")

    assert resp.status_code == 403, resp.data
    assert LLMConfig.objects.filter(id=config.id).exists()
