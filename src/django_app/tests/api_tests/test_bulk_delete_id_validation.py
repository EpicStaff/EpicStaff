"""Request validation of the bulk deletes that do not use BulkDeleteActionMixin.

Python-code tools, MCP tools, sessions and source collections keep their own
response shapes; their id lists are validated by the shared BulkIdListField.
"""

from collections.abc import Callable
from dataclasses import dataclass

import pytest
from django.db.models import Model
from rest_framework import status

from tables.models import Graph
from tables.models.knowledge_models import SourceCollection
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.session_models import Session
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _make_python_code_tool(org) -> PythonCodeTool:
    code = PythonCode.objects.create(code="x", entrypoint="main")
    return PythonCodeTool.objects.create(name="tool", description="", python_code=code, org=org)


def _make_mcp_tool(org) -> McpTool:
    return McpTool.objects.create(
        name="mcp", transport="https://example.com/mcp", tool_name="do_thing", org=org
    )


def _make_session(org) -> Session:
    graph = Graph.objects.create(name="flow", org=org)
    return Session.objects.create(graph=graph, status=Session.SessionStatus.PENDING, variables={})


def _make_collection(org) -> SourceCollection:
    return SourceCollection.objects.create(org=org, collection_name="collection")


@dataclass(frozen=True)
class BulkDeleteEndpoint:
    url: str
    ids_key: str
    error_key: str
    make_row: Callable[[object], Model]

    def __str__(self) -> str:
        return self.url


ENDPOINTS = [
    BulkDeleteEndpoint(
        "/api/python-code-tool/bulk-delete/", "ids", "detail", _make_python_code_tool
    ),
    BulkDeleteEndpoint("/api/mcp-tools/bulk-delete/", "ids", "detail", _make_mcp_tool),
    BulkDeleteEndpoint("/api/sessions/bulk_delete/", "ids", "detail", _make_session),
    BulkDeleteEndpoint(
        "/api/source-collections/bulk-delete/", "collection_ids", "error", _make_collection
    ),
]

endpoints = pytest.mark.parametrize("endpoint", ENDPOINTS, ids=str)


def _still_there(row: Model) -> bool:
    return type(row).objects.filter(pk=row.pk).exists()


@pytest.mark.django_db
@endpoints
@pytest.mark.parametrize("bad_id", [True, False], ids=["true", "false"])
def test_a_boolean_id_is_rejected_and_nothing_is_deleted(endpoint, bad_id, acme_admin_client, acme):
    row = endpoint.make_row(acme)

    # bool is an int subclass; `true` must not reach the ORM as id 1.
    response = acme_admin_client.post(endpoint.url, {endpoint.ids_key: [bad_id]}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.json() == {
        endpoint.error_key: f"{endpoint.ids_key} must be a list of positive integers."
    }
    assert _still_there(row)


@pytest.mark.django_db
@endpoints
@pytest.mark.parametrize("bad_id", ["x", "1", 1.5, 0], ids=["word", "numeric-string", "float", "zero"])
def test_an_id_that_is_not_a_positive_integer_is_rejected(endpoint, bad_id, acme_admin_client, acme):
    row = endpoint.make_row(acme)

    response = acme_admin_client.post(
        endpoint.url, {endpoint.ids_key: [row.pk, bad_id]}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.json() == {
        endpoint.error_key: f"{endpoint.ids_key} must be a list of positive integers."
    }
    assert _still_there(row)


@pytest.mark.django_db
@endpoints
def test_more_than_500_ids_are_rejected_and_nothing_is_deleted(endpoint, acme_admin_client, acme):
    row = endpoint.make_row(acme)
    ids = [row.pk, *range(10_000_000, 10_000_500)]

    response = acme_admin_client.post(endpoint.url, {endpoint.ids_key: ids}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.json() == {
        endpoint.error_key: f"{endpoint.ids_key} must have at most 500 items."
    }
    assert _still_there(row)


@pytest.mark.django_db
@endpoints
@pytest.mark.parametrize(
    ("body_for", "expected_message"),
    [
        (lambda key: {key: []}, "{key} must not be empty."),
        (lambda key: {}, "{key} is required."),
        (lambda key: {key: "1,2"}, "{key} must be a list of positive integers."),
    ],
    ids=["empty", "missing", "not-a-list"],
)
def test_an_empty_missing_or_non_list_value_is_rejected(
    endpoint, body_for, expected_message, acme_admin_client
):
    response = acme_admin_client.post(endpoint.url, body_for(endpoint.ids_key), format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.json() == {endpoint.error_key: expected_message.format(key=endpoint.ids_key)}


@pytest.mark.django_db
@endpoints
def test_a_body_that_is_not_an_object_is_rejected(endpoint, acme_admin_client):
    response = acme_admin_client.post(endpoint.url, [1, 2], format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.json() == {
        endpoint.error_key: "Invalid data. Expected a dictionary, but got list."
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    "endpoint", [endpoint for endpoint in ENDPOINTS if endpoint.ids_key == "ids"], ids=str
)
def test_500_ids_delete_the_own_org_rows_and_echo_the_request(
    endpoint, acme_admin_client, acme, beta
):
    ours = endpoint.make_row(acme)
    theirs = endpoint.make_row(beta)
    ids = [ours.pk, theirs.pk, *range(10_000_000, 10_000_498)]

    response = acme_admin_client.post(endpoint.url, {"ids": ids}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {"deleted": 1, "ids": ids}
    assert not _still_there(ours)
    assert _still_there(theirs)


@pytest.mark.django_db
def test_500_collection_ids_delete_the_own_org_collections(acme_admin_client, acme, beta):
    ours = _make_collection(acme)
    theirs = _make_collection(beta)
    ids = [ours.pk, theirs.pk, *range(10_000_000, 10_000_498)]

    response = acme_admin_client.post(
        "/api/source-collections/bulk-delete/", {"collection_ids": ids}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["message"] == "Successfully deleted 1 collection(s)"
    assert response.json()["deleted_count"] == 1
    assert not _still_there(ours)
    assert _still_there(theirs)
