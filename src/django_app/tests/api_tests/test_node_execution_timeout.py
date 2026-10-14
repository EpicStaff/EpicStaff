"""`execution_timeout` (minutes) on the five code-running nodes, through the node
endpoints and the graph bulk save.

Invariant: the stored value is always a whole number of minutes between 1 and the
sandbox ceiling (`SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES`). Omitting the field on
create stores the ceiling; a value above the ceiling is saved as the ceiling, not
rejected, because the ceiling is deployment configuration that can be lowered after a
flow was built; a value below 1, null or not a whole number is a 400 and changes
nothing. Nodes stay org-scoped: another organization's node is a 404.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import Graph
from tests.execution_timeout_node_specs import (
    EXECUTION_TIMEOUT_NODE_SPEC_IDS,
    EXECUTION_TIMEOUT_NODE_SPECS,
    INVALID_EXECUTION_TIMEOUT_IDS,
    INVALID_EXECUTION_TIMEOUTS,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

CEILING_MINUTES = 7
STORED_MINUTES = 4


@pytest.fixture(autouse=True)
def sandbox_ceiling(settings):
    settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = CEILING_MINUTES


@pytest.fixture(params=EXECUTION_TIMEOUT_NODE_SPECS, ids=EXECUTION_TIMEOUT_NODE_SPEC_IDS)
def spec(request):
    return request.param


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="execution-timeout-flow", org=acme)


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def acme_node(spec, acme_graph):
    return spec.create(acme_graph, execution_timeout=STORED_MINUTES)


def _patch(client, spec, node, body: dict):
    return client.patch(reverse(f"{spec.basename}-detail", args=[node.id]), body, format="json")


def _bulk_save(client, graph: Graph, list_key: str, entry: dict):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, list_key: [entry]},
        format="json",
    )


@pytest.mark.django_db
class TestNodeEndpoint:
    def test_create_without_the_field_stores_the_ceiling(self, acme_client, acme_graph, spec):
        response = acme_client.post(
            reverse(f"{spec.basename}-list"), spec.request_body(acme_graph), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.data["execution_timeout"] == CEILING_MINUTES
        assert spec.model.objects.get(pk=response.data["id"]).execution_timeout == CEILING_MINUTES

    def test_value_within_the_ceiling_is_saved_and_returned(self, acme_client, spec, acme_node):
        response = _patch(acme_client, spec, acme_node, {"execution_timeout": 2})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["execution_timeout"] == 2
        acme_node.refresh_from_db()
        assert acme_node.execution_timeout == 2

    @pytest.mark.parametrize("requested", [CEILING_MINUTES + 1, 10_000])
    def test_value_above_the_ceiling_is_saved_as_the_ceiling(
        self, acme_client, spec, acme_node, requested
    ):
        response = _patch(acme_client, spec, acme_node, {"execution_timeout": requested})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["execution_timeout"] == CEILING_MINUTES
        acme_node.refresh_from_db()
        assert acme_node.execution_timeout == CEILING_MINUTES

    @pytest.mark.parametrize(
        "invalid", INVALID_EXECUTION_TIMEOUTS, ids=INVALID_EXECUTION_TIMEOUT_IDS
    )
    def test_invalid_value_is_rejected_and_nothing_changes(
        self, acme_client, spec, acme_node, invalid
    ):
        response = _patch(acme_client, spec, acme_node, {"execution_timeout": invalid})

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "execution_timeout" in response.content.decode()
        acme_node.refresh_from_db()
        assert acme_node.execution_timeout == STORED_MINUTES

    def test_node_of_another_organization_is_not_found(self, acme_client, beta, spec):
        beta_node = spec.create(
            Graph.objects.create(name="beta-execution-timeout-flow", org=beta),
            execution_timeout=STORED_MINUTES,
        )

        response = _patch(acme_client, spec, beta_node, {"execution_timeout": 1})

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        beta_node.refresh_from_db()
        assert beta_node.execution_timeout == STORED_MINUTES


@pytest.mark.django_db
class TestBulkSave:
    def test_new_node_without_the_field_stores_the_ceiling(self, acme_client, acme_graph, spec):
        response = _bulk_save(
            acme_client, acme_graph, spec.graph_list_key, spec.request_body(acme_graph)
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        node = getattr(acme_graph, spec.graph_list_key).get()
        assert node.execution_timeout == CEILING_MINUTES

    @pytest.mark.parametrize(
        ("requested", "stored"), [(2, 2), (CEILING_MINUTES + 50, CEILING_MINUTES)]
    )
    def test_existing_node_saves_the_value_clamped_to_the_ceiling(
        self, acme_client, acme_graph, spec, acme_node, requested, stored
    ):
        entry = spec.request_body(acme_graph, id=acme_node.id, execution_timeout=requested)

        response = _bulk_save(acme_client, acme_graph, spec.graph_list_key, entry)

        assert response.status_code == status.HTTP_200_OK, response.content
        acme_node.refresh_from_db()
        assert acme_node.execution_timeout == stored

    @pytest.mark.parametrize(
        "invalid", INVALID_EXECUTION_TIMEOUTS, ids=INVALID_EXECUTION_TIMEOUT_IDS
    )
    def test_invalid_value_is_rejected_and_nothing_changes(
        self, acme_client, acme_graph, spec, acme_node, invalid
    ):
        entry = spec.request_body(acme_graph, id=acme_node.id, execution_timeout=invalid)

        response = _bulk_save(acme_client, acme_graph, spec.graph_list_key, entry)

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "execution_timeout" in response.content.decode()
        acme_node.refresh_from_db()
        assert acme_node.execution_timeout == STORED_MINUTES


@pytest.mark.django_db
class TestReadClamp:
    """A row stored above the ceiling (the ceiling was lowered and the startup clamp
    has not run yet) is never shown above it."""

    @pytest.fixture
    def node_above_the_ceiling(self, spec, acme_node):
        spec.model._base_manager.filter(pk=acme_node.pk).update(
            execution_timeout=CEILING_MINUTES + 20
        )
        return acme_node

    def test_node_endpoint_returns_the_ceiling(self, acme_client, spec, node_above_the_ceiling):
        response = acme_client.get(
            reverse(f"{spec.basename}-detail", args=[node_above_the_ceiling.id])
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["execution_timeout"] == CEILING_MINUTES

    def test_graph_endpoint_returns_the_ceiling(
        self, acme_client, acme_graph, spec, node_above_the_ceiling
    ):
        response = acme_client.get(reverse("graphs-detail", args=[acme_graph.id]))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [node["execution_timeout"] for node in response.data[spec.graph_list_key]] == [
            CEILING_MINUTES
        ]

    def test_value_within_the_ceiling_is_returned_as_stored(self, acme_client, spec, acme_node):
        response = acme_client.get(reverse(f"{spec.basename}-detail", args=[acme_node.id]))

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.data["execution_timeout"] == STORED_MINUTES
