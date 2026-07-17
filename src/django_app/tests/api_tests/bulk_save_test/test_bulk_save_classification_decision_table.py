import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import (
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
)
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


def _cdt_list_url() -> str:
    return reverse("classificationdecisiontablenode-list")


def _make_cdt_node_payload(graph_id, group_name, *, temp_id=None):
    node = {
        "graph": graph_id,
        "node_name": "cdt_test_node",
        "condition_groups": [
            {
                "group_name": group_name,
                "order": 0,
            }
        ],
    }

    if temp_id is not None:
        node["temp_id"] = temp_id

    return node


# ---------------------------------------------------------------------------
# Bulk save — null/blank group_name → 400
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_save_cdt_null_group_name_rejected(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [
            _make_cdt_node_payload(graph.id, group_name=None),
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "classification_decision_table_node_list" in resp.data["errors"]
    body = str(resp.content)
    assert "group_name" in body


@pytest.mark.django_db
def test_bulk_save_cdt_empty_string_group_name_rejected(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [
            _make_cdt_node_payload(graph.id, group_name=""),
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "classification_decision_table_node_list" in resp.data["errors"]
    body = str(resp.content)
    assert "group_name" in body


@pytest.mark.django_db
def test_bulk_save_cdt_whitespace_group_name_rejected(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [
            _make_cdt_node_payload(graph.id, group_name="   "),
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "classification_decision_table_node_list" in resp.data["errors"]
    body = str(resp.content)
    assert "group_name" in body


# ---------------------------------------------------------------------------
# Per-node POST — null/blank group_name → 400
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_per_node_post_null_group_name_rejected(auth_client, graph):
    payload = {
        "graph": graph.id,
        "node_name": "cdt_per_node",
        "condition_groups": [{"group_name": None, "order": 0}],
    }
    resp = auth_client.post(_cdt_list_url(), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    body = str(resp.content)
    assert "group_name" in body


@pytest.mark.django_db
def test_per_node_post_empty_string_group_name_rejected(auth_client, graph):
    payload = {
        "graph": graph.id,
        "node_name": "cdt_per_node_empty",
        "condition_groups": [{"group_name": "", "order": 0}],
    }
    resp = auth_client.post(_cdt_list_url(), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    body = str(resp.content)
    assert "group_name" in body


@pytest.mark.django_db
def test_per_node_post_whitespace_group_name_rejected(auth_client, graph):
    payload = {
        "graph": graph.id,
        "node_name": "cdt_per_node_ws",
        "condition_groups": [{"group_name": "   ", "order": 0}],
    }
    resp = auth_client.post(_cdt_list_url(), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    body = str(resp.content)
    assert "group_name" in body


# ---------------------------------------------------------------------------
# Regression — valid group_name succeeds
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_save_cdt_valid_group_name_succeeds(auth_client, graph):
    payload = {
        "save_version": graph.save_version,
        "classification_decision_table_node_list": [
            _make_cdt_node_payload(graph.id, group_name="valid_group"),
        ],
    }
    resp = auth_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    node = ClassificationDecisionTableNode.objects.get(
        graph=graph, node_name="cdt_test_node"
    )
    groups = ClassificationConditionGroup.objects.filter(
        classification_decision_table_node=node
    )
    assert groups.count() == 1
    assert groups.first().group_name == "valid_group"


@pytest.mark.django_db
def test_per_node_post_valid_group_name_succeeds(auth_client, graph):
    payload = {
        "graph": graph.id,
        "node_name": "cdt_per_node_valid",
        "condition_groups": [{"group_name": "good_name", "order": 0}],
    }
    resp = auth_client.post(_cdt_list_url(), payload, format="json")

    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    node = ClassificationDecisionTableNode.objects.get(
        graph=graph, node_name="cdt_per_node_valid"
    )
    groups = ClassificationConditionGroup.objects.filter(
        classification_decision_table_node=node
    )
    assert groups.count() == 1
    assert groups.first().group_name == "good_name"
