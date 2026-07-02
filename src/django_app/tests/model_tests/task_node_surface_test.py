"""
Integration tests for TaskNode.surface_list (catalog Surface M2M).

Covers:
- Create with / without surfaces
- Update replaces the set; PATCH without key keeps; PATCH [] clears
- Reject cross-org surface, agent-owned surface mismatch, duplicates, nonexistent pk
- GET returns surface pks
- Idempotent create (IdempotentNodeCreateMixin) replaces the surface set
- content_hash is unaffected by surface_list edits
- Direct SurfaceValidator.validate_task_node_surfaces unit tests
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from tables.exceptions import SurfaceValidationError
from tables.models.agent_models import AgentDefinition, Surface
from tables.models.graph_models import Graph, TaskNode
from tables.models.rbac_models import Organization
from tables.validators.surface_validator import SurfaceValidator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return APIClient()


@pytest.fixture
def org(db):
    from tables.constants.organization_constants import DEFAULT_ORGANIZATION_NAME

    return Organization.objects.get_or_create(name=DEFAULT_ORGANIZATION_NAME)[0]


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="other-org")


@pytest.fixture
def graph(db, org):
    return Graph.objects.create(name="task-node-surface-graph")


@pytest.fixture
def agent(db, org):
    return AgentDefinition.objects.create(
        organization=org,
        name="task-node-agent",
        instructions="do things",
    )


@pytest.fixture
def agent_b(db, org):
    return AgentDefinition.objects.create(
        organization=org,
        name="task-node-agent-b",
        instructions="do other things",
    )


@pytest.fixture
def shared_surface(db, org):
    return Surface.objects.create(
        organization=org,
        name="task-node-shared-surface",
        owner_agent=None,
    )


@pytest.fixture
def shared_surface_b(db, org):
    return Surface.objects.create(
        organization=org,
        name="task-node-shared-surface-b",
        owner_agent=None,
    )


@pytest.fixture
def other_org_surface(db, other_org):
    return Surface.objects.create(
        organization=other_org,
        name="task-node-other-org-surface",
        owner_agent=None,
    )


@pytest.fixture
def agent_owned_surface(db, org, agent):
    return Surface.objects.create(
        organization=org,
        name="task-node-agent-owned-surface",
        owner_agent=agent,
    )


@pytest.fixture
def agent_b_owned_surface(db, org, agent_b):
    return Surface.objects.create(
        organization=org,
        name="task-node-agent-b-owned-surface",
        owner_agent=agent_b,
    )


# ---------------------------------------------------------------------------
# API integration tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_with_surfaces_returns_201_and_pks(
    client, graph, shared_surface, shared_surface_b
):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": graph.pk,
            "node_name": "task-with-surfaces",
            "surface_list": [shared_surface.pk, shared_surface_b.pk],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert set(response.data["surface_list"]) == {
        shared_surface.pk,
        shared_surface_b.pk,
    }

    node = TaskNode.objects.get(node_name="task-with-surfaces")
    assert set(node.surface_list.values_list("pk", flat=True)) == {
        shared_surface.pk,
        shared_surface_b.pk,
    }


@pytest.mark.django_db
def test_create_without_surface_list_returns_201(client, graph):
    response = client.post(
        "/api/tasknodes/",
        {"graph": graph.pk, "node_name": "task-no-surfaces"},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["surface_list"] == []


@pytest.mark.django_db
def test_create_with_empty_surface_list_returns_201(client, graph):
    response = client.post(
        "/api/tasknodes/",
        {"graph": graph.pk, "node_name": "task-empty-surfaces", "surface_list": []},
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["surface_list"] == []


@pytest.mark.django_db
def test_update_replaces_surface_set(client, graph, shared_surface, shared_surface_b):
    node = TaskNode.objects.create(graph=graph, node_name="task-update")
    node.surface_list.add(shared_surface)

    response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"surface_list": [shared_surface_b.pk]},
        format="json",
    )

    assert response.status_code == 200, response.data
    node.refresh_from_db()
    assert set(node.surface_list.values_list("pk", flat=True)) == {shared_surface_b.pk}


@pytest.mark.django_db
def test_patch_without_surface_list_keeps_existing(client, graph, shared_surface):
    node = TaskNode.objects.create(graph=graph, node_name="task-patch-keep")
    node.surface_list.add(shared_surface)

    response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"instructions": "updated instructions"},
        format="json",
    )

    assert response.status_code == 200, response.data
    node.refresh_from_db()
    assert list(node.surface_list.values_list("pk", flat=True)) == [shared_surface.pk]


@pytest.mark.django_db
def test_patch_empty_surface_list_clears(client, graph, shared_surface):
    node = TaskNode.objects.create(graph=graph, node_name="task-patch-clear")
    node.surface_list.add(shared_surface)

    response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"surface_list": []},
        format="json",
    )

    assert response.status_code == 200, response.data
    node.refresh_from_db()
    assert node.surface_list.count() == 0


@pytest.mark.django_db
def test_reject_cross_org_surface(client, graph, other_org_surface):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": graph.pk,
            "node_name": "task-cross-org",
            "surface_list": [other_org_surface.pk],
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "surface_list" in response.data["message"]


@pytest.mark.django_db
def test_reject_surface_owned_by_other_agent(
    client, graph, agent, agent_b_owned_surface
):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": graph.pk,
            "node_name": "task-wrong-agent",
            "agent_definition": agent.pk,
            "surface_list": [agent_b_owned_surface.pk],
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "surface_list" in response.data["message"]


@pytest.mark.django_db
def test_accept_surface_owned_by_matching_agent(
    client, graph, agent, agent_owned_surface
):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": graph.pk,
            "node_name": "task-matching-agent",
            "agent_definition": agent.pk,
            "surface_list": [agent_owned_surface.pk],
        },
        format="json",
    )

    assert response.status_code == 201, response.data
    assert response.data["surface_list"] == [agent_owned_surface.pk]


@pytest.mark.django_db
def test_reject_owned_surface_on_agent_less_node(client, graph, agent_owned_surface):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": graph.pk,
            "node_name": "task-no-agent-owned-surface",
            "surface_list": [agent_owned_surface.pk],
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "surface_list" in response.data["message"]


@pytest.mark.django_db
def test_reject_duplicate_surface_ids(client, graph, shared_surface):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": graph.pk,
            "node_name": "task-dup-surfaces",
            "surface_list": [shared_surface.pk, shared_surface.pk],
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "surface_list" in response.data["message"]


@pytest.mark.django_db
def test_reject_nonexistent_surface_pk(client, graph):
    response = client.post(
        "/api/tasknodes/",
        {
            "graph": graph.pk,
            "node_name": "task-bad-surface-pk",
            "surface_list": [999999],
        },
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "surface_list" in response.data["message"]


@pytest.mark.django_db
def test_get_returns_surface_pks(client, graph, shared_surface):
    node = TaskNode.objects.create(graph=graph, node_name="task-get")
    node.surface_list.add(shared_surface)

    response = client.get(f"/api/tasknodes/{node.pk}/")

    assert response.status_code == 200, response.data
    assert response.data["surface_list"] == [shared_surface.pk]


@pytest.mark.django_db
def test_idempotent_create_replaces_surface_set(
    client, graph, shared_surface, shared_surface_b
):
    """Same (graph, node_name) POSTed again updates instead of creating —
    exercises IdempotentNodeCreateMixin with a surface_list payload change."""

    first = client.post(
        "/api/tasknodes/",
        {
            "graph": graph.pk,
            "node_name": "task-idempotent",
            "surface_list": [shared_surface.pk],
        },
        format="json",
    )
    assert first.status_code == 201, first.data

    second = client.post(
        "/api/tasknodes/",
        {
            "graph": graph.pk,
            "node_name": "task-idempotent",
            "surface_list": [shared_surface_b.pk],
        },
        format="json",
    )

    assert second.status_code == 200, second.data
    assert (
        TaskNode.objects.filter(graph=graph, node_name="task-idempotent").count() == 1
    )
    node = TaskNode.objects.get(graph=graph, node_name="task-idempotent")
    assert set(node.surface_list.values_list("pk", flat=True)) == {shared_surface_b.pk}


@pytest.mark.django_db
def test_content_hash_unchanged_by_surface_edit(graph, shared_surface):
    """ContentHashMixin.generate_hash iterates _meta.fields only — M2M excluded."""
    node = TaskNode.objects.create(graph=graph, node_name="task-hash")
    hash_before = node.content_hash

    node.surface_list.add(shared_surface)
    node.refresh_from_db()

    assert node.content_hash == hash_before


# ---------------------------------------------------------------------------
# SurfaceValidator.validate_task_node_surfaces — unit tests
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_validator_shared_surface_passes(org, shared_surface):
    SurfaceValidator.validate_task_node_surfaces(
        surfaces=[shared_surface], agent_definition=None, organization=org
    )


@pytest.mark.django_db
def test_validator_rejects_cross_org_surface(org, other_org_surface):
    with pytest.raises(SurfaceValidationError) as exc_info:
        SurfaceValidator.validate_task_node_surfaces(
            surfaces=[other_org_surface], agent_definition=None, organization=org
        )

    assert "surface_list" in exc_info.value.detail


@pytest.mark.django_db
def test_validator_rejects_surface_owned_by_other_agent(
    org, agent, agent_b_owned_surface
):
    with pytest.raises(SurfaceValidationError) as exc_info:
        SurfaceValidator.validate_task_node_surfaces(
            surfaces=[agent_b_owned_surface],
            agent_definition=agent,
            organization=org,
        )

    assert "surface_list" in exc_info.value.detail


@pytest.mark.django_db
def test_validator_accepts_surface_owned_by_matching_agent(
    org, agent, agent_owned_surface
):
    SurfaceValidator.validate_task_node_surfaces(
        surfaces=[agent_owned_surface], agent_definition=agent, organization=org
    )


@pytest.mark.django_db
def test_validator_rejects_owned_surface_when_agent_definition_none(
    org, agent_owned_surface
):
    with pytest.raises(SurfaceValidationError) as exc_info:
        SurfaceValidator.validate_task_node_surfaces(
            surfaces=[agent_owned_surface], agent_definition=None, organization=org
        )

    assert "surface_list" in exc_info.value.detail


@pytest.mark.django_db
def test_validator_rejects_duplicate_ids(org, shared_surface):
    with pytest.raises(SurfaceValidationError) as exc_info:
        SurfaceValidator.validate_task_node_surfaces(
            surfaces=[shared_surface, shared_surface],
            agent_definition=None,
            organization=org,
        )

    assert "surface_list" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Agent-change re-validates existing attached surfaces (no surface_list in payload)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_patch_agent_definition_without_surface_list_rejects_stale_owned_surface(
    client, graph, agent, agent_b, agent_owned_surface
):
    node = TaskNode.objects.create(
        graph=graph, node_name="task-agent-change-stale-owned", agent_definition=agent
    )
    node.surface_list.add(agent_owned_surface)

    response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"agent_definition": agent_b.pk},
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "surface_list" in response.data["message"]

    node.refresh_from_db()
    assert set(node.surface_list.values_list("pk", flat=True)) == {
        agent_owned_surface.pk
    }


@pytest.mark.django_db
def test_patch_agent_definition_to_null_without_surface_list_rejects_stale_owned_surface(
    client, graph, agent, agent_owned_surface
):
    node = TaskNode.objects.create(
        graph=graph, node_name="task-agent-clear-stale-owned", agent_definition=agent
    )
    node.surface_list.add(agent_owned_surface)

    response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"agent_definition": None},
        format="json",
    )

    assert response.status_code == 400, response.data
    assert "surface_list" in response.data["message"]


@pytest.mark.django_db
def test_patch_agent_definition_without_surface_list_accepts_shared_surfaces_only(
    client, graph, agent, agent_b, shared_surface
):
    node = TaskNode.objects.create(
        graph=graph, node_name="task-agent-change-shared-only", agent_definition=agent
    )
    node.surface_list.add(shared_surface)

    response = client.patch(
        f"/api/tasknodes/{node.pk}/",
        {"agent_definition": agent_b.pk},
        format="json",
    )

    assert response.status_code == 200, response.data
    node.refresh_from_db()
    assert node.agent_definition_id == agent_b.pk
    assert set(node.surface_list.values_list("pk", flat=True)) == {shared_surface.pk}
