"""Tests for the persistent-state model consolidation (EST-3056).

Covers the 1:1 GraphOrganization<->Graph relationship (org derived from
graph.org, no `organization` FK) and the renamed Graph.enable_persistent_variables
boolean flag.
"""

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models import Graph, GraphOrganization


@pytest.fixture
def org_client(regular_user, default_org):
    """Org-scoped API client for an Org Admin of default_org.

    Test settings set DEFAULT_AUTHENTICATION_CLASSES = [], so JWT bearer auth
    is inert; the suite authenticates via force_authenticate. The active-org
    header makes org-scoped endpoints resolve and authorize.
    """
    client = APIClient()
    client.force_authenticate(user=regular_user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@pytest.mark.django_db
def test_flow_creation_creates_single_graph_organization_owned_by_graph_org(
    org_client, default_org
):
    """Creating a flow makes exactly one GraphOrganization row, whose owning
    org is derived from graph.org (no separate organization FK)."""
    url = reverse("graphs-list")

    response = org_client.post(url, {"name": "consolidation flow"}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    graph = Graph.objects.get(id=response.data["id"])

    graph_orgs = GraphOrganization.objects.filter(graph=graph)
    assert graph_orgs.count() == 1
    # Ownership is expressed through the graph itself, not a GraphOrganization FK.
    assert graph.org == default_org


@pytest.mark.django_db
def test_graph_organization_unique_per_graph(org_client):
    """A graph may own at most one GraphOrganization row (unique(graph))."""
    url = reverse("graphs-list")
    response = org_client.post(url, {"name": "unique flow"}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.content

    graph = Graph.objects.get(id=response.data["id"])
    # One row already exists (created alongside the graph); a second must fail
    # on the unique_persistent_state_per_flow constraint.
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            GraphOrganization.objects.create(graph=graph)


@pytest.mark.django_db
def test_graph_organization_api_has_no_organization_field(org_client):
    """The /graph-organizations/ payload no longer exposes an `organization`
    field; org is implied by the flow."""
    graphs_url = reverse("graphs-list")
    response = org_client.post(graphs_url, {"name": "payload flow"}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.content
    graph_id = response.data["id"]

    graph_org = GraphOrganization.objects.get(graph_id=graph_id)
    detail_url = reverse("graphorganization-detail", args=[graph_org.id])

    detail = org_client.get(detail_url)

    assert detail.status_code == status.HTTP_200_OK, detail.content
    assert "organization" not in detail.data
    assert set(detail.data.keys()) == {
        "id",
        "graph",
        "persistent_variables",
        "user_variables",
    }


@pytest.mark.django_db
def test_graph_enable_persistent_variables_round_trips(org_client):
    """The renamed boolean flag round-trips through create and update; the old
    `persistent_variables` name is absent from the graph payload."""
    url = reverse("graphs-list")

    created = org_client.post(
        url,
        {"name": "flag flow", "enable_persistent_variables": True},
        format="json",
    )
    assert created.status_code == status.HTTP_201_CREATED, created.content
    assert created.data["enable_persistent_variables"] is True
    assert "persistent_variables" not in created.data

    graph = Graph.objects.get(id=created.data["id"])
    assert graph.enable_persistent_variables is True

    detail_url = reverse("graphs-detail", args=[graph.id])
    patched = org_client.patch(
        detail_url,
        {"enable_persistent_variables": False, "save_version": graph.save_version},
        format="json",
    )
    assert patched.status_code == status.HTTP_200_OK, patched.content
    assert patched.data["enable_persistent_variables"] is False
    graph.refresh_from_db()
    assert graph.enable_persistent_variables is False
