"""Flow copy and create-flow-from-version pick the new flow name from the
caller's own organization only.

Before the fix both paths deduplicated the generated name against EVERY
organization's flow names, so the returned name revealed whether another tenant
had a flow with that name. Flow names are unique per organization among active
(not soft-deleted) rows, so that is exactly the set the generated name is checked
against.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.graph_versioning.services import GraphVersioningService
from tables.models import Graph
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def acme_admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _copy_flow(client, graph, **payload):
    return client.post(reverse("graphs-copy", args=[graph.id]), payload, format="json")


def _create_flow_from_version(client, version):
    return client.post(
        reverse("graph-versions-create-graph", args=[version.id]), format="json"
    )


# ---- flow copy -------------------------------------------------------------


@pytest.mark.django_db
def test_copy_name_ignores_flow_names_of_another_org(acme_admin_client, acme, beta):
    source = Graph.objects.create(name="Shared Flow", org=acme)
    for name in ("Shared Flow", "Shared Flow #2", "Shared Flow #3"):
        Graph.objects.create(name=name, org=beta)

    response = _copy_flow(acme_admin_client, source)

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert response.data["name"] == "Shared Flow #2"


@pytest.mark.django_db
def test_copy_with_explicit_name_used_only_by_another_org_keeps_that_name(
    acme_admin_client, acme, beta
):
    source = Graph.objects.create(name="Acme Flow", org=acme)
    Graph.objects.create(name="Beta Secret Project", org=beta)

    response = _copy_flow(acme_admin_client, source, name="Beta Secret Project")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert response.data["name"] == "Beta Secret Project"


@pytest.mark.django_db
def test_copy_name_is_deduplicated_against_same_org_flows(acme_admin_client, acme):
    source = Graph.objects.create(name="Acme Flow", org=acme)
    Graph.objects.create(name="Acme Flow #2", org=acme)

    response = _copy_flow(acme_admin_client, source)

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert response.data["name"] == "Acme Flow #3"


@pytest.mark.django_db
def test_copy_name_reuses_name_of_soft_deleted_same_org_flow(acme_admin_client, acme):
    """unique_graph_name_per_org only covers active rows, so a soft-deleted flow's
    name is free and must not push the copy to a higher number."""
    source = Graph.objects.create(name="Acme Flow", org=acme)
    deleted = Graph.objects.create(name="Acme Flow #2", org=acme)
    deleted.soft_delete()
    assert Graph.all_objects.get(pk=deleted.pk).active is False

    response = _copy_flow(acme_admin_client, source)

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert response.data["name"] == "Acme Flow #2"


# ---- create flow from version (restore as new flow) ------------------------


@pytest.mark.django_db
def test_create_flow_from_version_name_ignores_flow_names_of_another_org(
    acme_admin_client, acme, beta
):
    source = Graph.objects.create(name="Shared Flow", org=acme)
    version = GraphVersioningService().save_version(source, name="v1")
    for name in ("Shared Flow from v1", "Shared Flow from v1 #2"):
        Graph.objects.create(name=name, org=beta)

    response = _create_flow_from_version(acme_admin_client, version)

    assert response.status_code == status.HTTP_201_CREATED, response.content
    new_graph = Graph.objects.get(id=response.data["graph_id"])
    assert new_graph.name == "Shared Flow from v1"
    assert new_graph.org_id == acme.id


@pytest.mark.django_db
def test_create_flow_from_version_name_is_deduplicated_against_same_org_flows(
    acme_admin_client, acme, beta
):
    source = Graph.objects.create(name="Acme Flow", org=acme)
    version = GraphVersioningService().save_version(source, name="v1")
    Graph.objects.create(name="Acme Flow from v1", org=acme)
    Graph.objects.create(name="Acme Flow from v1 #2", org=beta)

    response = _create_flow_from_version(acme_admin_client, version)

    assert response.status_code == status.HTTP_201_CREATED, response.content
    new_graph = Graph.objects.get(id=response.data["graph_id"])
    assert new_graph.name == "Acme Flow from v1 #2"
