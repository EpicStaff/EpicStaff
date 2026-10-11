"""The graph-version list is paginated, so its order must be deterministic.

`created_at` alone is not unique: versions saved in the same instant tie, and
Postgres may return tied rows in any order, so a client walking the pages could
see one version twice and miss another.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from tables.models import Graph, GraphVersion

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


PAGE_LIMIT = 2
TIED_VERSION_COUNT = 5


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="version-ordering-flow", org=acme)


def _create_version(graph, name, created_at):
    version = GraphVersion.objects.create(graph=graph, name=name, snapshot={})
    # created_at is auto_now_add, so the timestamp is set after the insert.
    GraphVersion.all_objects.filter(pk=version.pk).update(created_at=created_at)
    return version


def _all_pages_ids(client, url, **params):
    collected_ids = []
    offset = 0
    while True:
        response = client.get(url, {**params, "limit": PAGE_LIMIT, "offset": offset})
        assert response.status_code == status.HTTP_200_OK, response.content
        collected_ids.extend(item["id"] for item in response.data["results"])
        if response.data["next"] is None:
            return collected_ids
        offset += PAGE_LIMIT


@pytest.mark.django_db
class TestGraphVersionListOrdering:
    def test_list_returns_newest_version_first(self, acme_client, acme_graph):
        now = timezone.now()
        oldest = _create_version(acme_graph, "oldest", now - timedelta(hours=2))
        newest = _create_version(acme_graph, "newest", now)
        middle = _create_version(acme_graph, "middle", now - timedelta(hours=1))

        response = acme_client.get(reverse("graph-versions-list"), {"graph_id": acme_graph.id})

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [item["id"] for item in response.data["results"]] == [
            newest.id,
            middle.id,
            oldest.id,
        ]

    def test_versions_with_identical_created_at_are_ordered_by_id_descending(
        self, acme_client, acme_graph
    ):
        shared_created_at = timezone.now()
        tied_versions = [
            _create_version(acme_graph, f"tied-{index}", shared_created_at)
            for index in range(TIED_VERSION_COUNT)
        ]
        expected_ids = sorted((version.id for version in tied_versions), reverse=True)
        url = reverse("graph-versions-list")

        first_walk_ids = _all_pages_ids(acme_client, url, graph_id=acme_graph.id)
        second_walk_ids = _all_pages_ids(acme_client, url, graph_id=acme_graph.id)

        assert first_walk_ids == second_walk_ids == expected_ids
        assert len(first_walk_ids) == len(set(first_walk_ids))

    def test_pages_cover_every_version_exactly_once_with_mixed_timestamps(
        self, acme_client, acme_graph
    ):
        now = timezone.now()
        newer_tied = [_create_version(acme_graph, f"newer-{index}", now) for index in range(3)]
        older_tied = [
            _create_version(acme_graph, f"older-{index}", now - timedelta(minutes=5))
            for index in range(3)
        ]
        expected_ids = [
            *sorted((version.id for version in newer_tied), reverse=True),
            *sorted((version.id for version in older_tied), reverse=True),
        ]

        collected_ids = _all_pages_ids(
            acme_client, reverse("graph-versions-list"), graph_id=acme_graph.id
        )

        assert collected_ids == expected_ids

    def test_all_action_uses_the_same_order_including_soft_deleted(
        self, acme_client, acme_graph
    ):
        shared_created_at = timezone.now()
        tied_versions = [
            _create_version(acme_graph, f"all-{index}", shared_created_at) for index in range(4)
        ]
        GraphVersion.all_objects.filter(pk=tied_versions[1].pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )
        expected_ids = sorted((version.id for version in tied_versions), reverse=True)

        collected_ids = _all_pages_ids(
            acme_client, reverse("graph-versions-all"), graph_id=acme_graph.id
        )

        assert collected_ids == expected_ids

    def test_list_excludes_other_organization_versions(self, acme_client, acme_graph, beta):
        shared_created_at = timezone.now()
        acme_version = _create_version(acme_graph, "acme-version", shared_created_at)
        beta_graph = Graph.objects.create(name="beta-version-flow", org=beta)
        beta_version = _create_version(beta_graph, "beta-version", shared_created_at)
        url = reverse("graph-versions-list")

        unfiltered_ids = _all_pages_ids(acme_client, url)
        filtered_by_beta_graph_ids = _all_pages_ids(acme_client, url, graph_id=beta_graph.id)

        assert unfiltered_ids == [acme_version.id]
        assert beta_version.id not in unfiltered_ids
        assert filtered_by_beta_graph_ids == []
