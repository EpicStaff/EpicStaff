"""The flow list endpoints are paginated, so their order must be deterministic.

Without an explicit ordering Postgres returns rows in heap order, which shifts
after an UPDATE; a client walking the pages then sees some flows twice and
others never.
"""

import pytest
from rest_framework import status

from tables.models import Graph
from tables.models.label_models import Label

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


GRAPH_LIGHT_URL = "/api/graph-light/"
GRAPHS_URL = "/api/graphs/"
LIST_URLS = [GRAPH_LIGHT_URL, GRAPHS_URL]
GRAPH_COUNT = 7
PAGE_LIMIT = 3


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def acme_graphs(acme):
    return [
        Graph.objects.create(name=f"ordering-flow-{index}", org=acme)
        for index in range(GRAPH_COUNT)
    ]


@pytest.fixture
def expected_ids(acme_graphs):
    return sorted((graph.id for graph in acme_graphs), reverse=True)


def _listed_ids(client, url, **params):
    response = client.get(url, params)
    assert response.status_code == status.HTTP_200_OK, response.content
    return [item["id"] for item in response.data["results"]]


def _all_pages_ids(client, url, **params):
    collected_ids = []
    offset = 0
    while True:
        response = client.get(url, {**params, "limit": PAGE_LIMIT, "offset": offset})
        assert response.status_code == status.HTTP_200_OK, response.content
        page_ids = [item["id"] for item in response.data["results"]]
        collected_ids.extend(page_ids)
        if response.data["next"] is None:
            return collected_ids
        offset += PAGE_LIMIT


@pytest.mark.django_db
@pytest.mark.parametrize("url", LIST_URLS)
class TestGraphListOrdering:
    def test_list_is_ordered_by_id_descending(self, url, acme_client, expected_ids):
        assert _listed_ids(acme_client, url) == expected_ids

    def test_repeated_requests_return_the_same_order(self, url, acme_client, expected_ids):
        first_ids = _listed_ids(acme_client, url)
        second_ids = _listed_ids(acme_client, url)

        assert first_ids == second_ids == expected_ids

    def test_pages_cover_every_flow_exactly_once_in_order(self, url, acme_client, expected_ids):
        collected_ids = _all_pages_ids(acme_client, url)

        assert len(collected_ids) == len(set(collected_ids))
        assert collected_ids == expected_ids

    def test_order_is_stable_after_renaming_a_flow(
        self, url, acme_client, acme_graphs, expected_ids
    ):
        renamed_graph = acme_graphs[0]
        response = acme_client.patch(
            f"{GRAPHS_URL}{renamed_graph.id}/",
            {"name": "renamed-ordering-flow", "save_version": renamed_graph.save_version},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content

        assert _all_pages_ids(acme_client, url) == expected_ids

    def test_order_is_stable_after_relabeling_a_flow(
        self, url, acme_client, acme, acme_graphs, expected_ids
    ):
        label = Label.objects.create(name="ordering-label", org=acme, scope=Label.Scope.FLOW)
        relabeled_graph = acme_graphs[GRAPH_COUNT // 2]
        response = acme_client.patch(
            f"{GRAPHS_URL}{relabeled_graph.id}/",
            {"label_ids": [label.id], "save_version": relabeled_graph.save_version},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK, response.content

        assert _all_pages_ids(acme_client, url) == expected_ids

    def test_label_filter_keeps_order_without_duplicates(
        self, url, acme_client, acme, acme_graphs
    ):
        parent_label = Label.objects.create(name="ordering-parent", org=acme, scope=Label.Scope.FLOW)
        child_label = Label.objects.create(
            name="ordering-child", org=acme, scope=Label.Scope.FLOW, parent=parent_label
        )
        labeled_graphs = acme_graphs[::2]
        for graph in labeled_graphs:
            # Two matching labels per flow: the label join yields duplicate rows
            # unless the filter's distinct() still works alongside the ordering.
            graph.labels.set([parent_label, child_label])

        collected_ids = _all_pages_ids(acme_client, url, label_id=parent_label.id)

        assert collected_ids == sorted((graph.id for graph in labeled_graphs), reverse=True)

    def test_list_excludes_other_organization_flows(
        self, url, acme_client, beta, expected_ids
    ):
        other_org_graph = Graph.objects.create(name="beta-ordering-flow", org=beta)

        collected_ids = _all_pages_ids(acme_client, url)

        assert other_org_graph.id not in collected_ids
        assert collected_ids == expected_ids
