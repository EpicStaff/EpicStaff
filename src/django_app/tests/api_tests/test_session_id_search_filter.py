"""`id_search` partial match on session id — GET /api/sessions/ and POST /api/sessions/export_all/."""

import json

import pytest
from django.urls import reverse
from rest_framework import status

from tables.import_export.enums import EntityType
from tables.models import Graph
from tables.models.session_models import Session
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

LIST_URL = reverse("session-list")
EXPORT_ALL_URL = "/api/sessions/export_all/"

# Ids are set explicitly so the substring relations are known. They sit far above
# anything the sequence hands out during a test, so no auto id can match by accident.
SEARCH = "987654"
EXACT_ID = 987654
PREFIXED_ID = 1987654
SUFFIXED_ID = 9876540
SHORTER_ID = 98765
UNRELATED_ID = 123456
OTHER_GRAPH_ID = 3987654
BETA_ID = 2987654

MATCHING_IN_ACME_GRAPH = {EXACT_ID, PREFIXED_ID, SUFFIXED_ID}
ALL_ACME = MATCHING_IN_ACME_GRAPH | {SHORTER_ID, UNRELATED_ID, OTHER_GRAPH_ID}


def _session(graph, session_id):
    return Session.objects.create(
        id=session_id, graph=graph, status=Session.SessionStatus.END, variables={}
    )


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="id-search-flow", org=acme)


@pytest.fixture
def sessions(acme, beta, acme_graph):
    """Acme sessions around SEARCH, one in another acme graph, and a matching beta session."""
    other_acme_graph = Graph.objects.create(name="id-search-other-flow", org=acme)
    beta_graph = Graph.objects.create(name="id-search-beta-flow", org=beta)
    for session_id in (EXACT_ID, PREFIXED_ID, SUFFIXED_ID, SHORTER_ID, UNRELATED_ID):
        _session(acme_graph, session_id)
    _session(other_acme_graph, OTHER_GRAPH_ID)
    _session(beta_graph, BETA_ID)


def _listed_ids(response):
    assert response.status_code == status.HTTP_200_OK, response.content
    return {row["id"] for row in response.data["results"]}


def _exported_ids(response):
    assert response.status_code == status.HTTP_200_OK, response.content
    exported = json.loads(response.content)[EntityType.SESSION]
    return {entry["session"]["id"] for entry in exported}


@pytest.mark.django_db
class TestSessionListIdSearch:
    @pytest.mark.parametrize("detailed", ["true", "false"])
    def test_partial_match_returns_every_session_whose_id_contains_the_value(
        self, acme_client, sessions, detailed
    ):
        response = acme_client.get(LIST_URL, {"id_search": SEARCH, "detailed": detailed})

        assert _listed_ids(response) == MATCHING_IN_ACME_GRAPH | {OTHER_GRAPH_ID}

    def test_surrounding_whitespace_is_ignored(self, acme_client, sessions):
        response = acme_client.get(LIST_URL, {"id_search": f"  {SEARCH} "})

        assert _listed_ids(response) == MATCHING_IN_ACME_GRAPH | {OTHER_GRAPH_ID}

    @pytest.mark.parametrize("raw_value", ["", "   "])
    def test_empty_value_does_not_filter(self, acme_client, sessions, raw_value):
        response = acme_client.get(LIST_URL, {"id_search": raw_value})

        assert _listed_ids(response) == ALL_ACME

    @pytest.mark.parametrize("raw_value", ["abc", "9876a", "-987654", "98 76", "98.76"])
    def test_non_digit_value_returns_no_sessions(self, acme_client, sessions, raw_value):
        response = acme_client.get(LIST_URL, {"id_search": raw_value})

        assert _listed_ids(response) == set()
        assert response.data["count"] == 0

    def test_combines_with_graph_id(self, acme_client, sessions, acme_graph):
        response = acme_client.get(LIST_URL, {"id_search": SEARCH, "graph_id": acme_graph.pk})

        assert _listed_ids(response) == MATCHING_IN_ACME_GRAPH

    def test_other_orgs_matching_session_never_appears(self, acme_client, sessions):
        response = acme_client.get(LIST_URL, {"id_search": str(BETA_ID)})

        assert _listed_ids(response) == set()


@pytest.mark.django_db
class TestSessionExportAllIdSearch:
    def test_partial_match_exports_every_session_whose_id_contains_the_value(
        self, acme_client, sessions
    ):
        response = acme_client.post(EXPORT_ALL_URL, {"id_search": SEARCH}, format="json")

        assert _exported_ids(response) == MATCHING_IN_ACME_GRAPH | {OTHER_GRAPH_ID}

    @pytest.mark.parametrize("raw_value", ["", "   "])
    def test_empty_value_does_not_filter(self, acme_client, sessions, raw_value):
        response = acme_client.post(EXPORT_ALL_URL, {"id_search": raw_value}, format="json")

        assert _exported_ids(response) == ALL_ACME

    @pytest.mark.parametrize("raw_value", ["abc", "9876a", "-987654"])
    def test_non_digit_value_matches_nothing(self, acme_client, sessions, raw_value):
        response = acme_client.post(EXPORT_ALL_URL, {"id_search": raw_value}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content

    def test_combines_with_graph_id(self, acme_client, sessions, acme_graph):
        response = acme_client.post(
            EXPORT_ALL_URL, {"id_search": SEARCH, "graph_id": acme_graph.pk}, format="json"
        )

        assert _exported_ids(response) == MATCHING_IN_ACME_GRAPH

    def test_other_orgs_matching_session_is_never_exported(self, acme_client, sessions):
        response = acme_client.post(EXPORT_ALL_URL, {"id_search": str(BETA_ID)}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
