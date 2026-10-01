"""Secret declarations survive a version restore over HTTP, warnings included.

tests/graph_versioning_tests/test_secret_declarations.py covers the mechanism at the
service layer. This file covers the seam above it: that the view passes the snapshot's
declarations through, and that a declaration which could not be re-linked reaches the
caller in the response's existing `warnings` list rather than vanishing.

Fixtures (org, admin client, a flow with a declared secret) live in
graph_version_api_fixtures.py, shared with test_graph_version_preview.py.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import PythonNode
from tables.models.graph_models import Graph
from tables.services.secrets.declaration_validator import SecretDeclarationValidator
from tests.api_tests.graph_version_api_fixtures import *  # noqa: F401,F403
from tests.api_tests.graph_version_api_fixtures import save_version


def _restore(*, client, graph, version_id):
    graph.refresh_from_db()
    return client.post(
        reverse("graph-versions-restore", args=[version_id]),
        {"save_version": graph.save_version},
        format="json",
    )


def _declared_names(*, graph):
    node = PythonNode.objects.filter(graph=graph).select_related("python_code").get()
    return sorted(node.python_code.secrets.values_list("name", flat=True))


@pytest.mark.django_db
def test_restore_reattaches_the_declaration_and_leaves_the_flow_runnable(
    client, graph_with_declared_secret
):
    graph, _ = graph_with_declared_secret
    version_id = save_version(client=client, graph=graph)

    response = _restore(client=client, graph=graph, version_id=version_id)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["warnings"] == []
    assert _declared_names(graph=graph) == ["STRIPE_KEY"]
    assert SecretDeclarationValidator().violations(graph_id=graph.pk) == []


@pytest.mark.django_db
def test_restore_reports_a_dropped_declaration_in_the_response_warnings(
    client, graph_with_declared_secret
):
    """A secret deleted between save and restore must be reported, not silently
    dropped — the caller has no other way to learn the flow is now unrunnable."""
    graph, secret = graph_with_declared_secret
    version_id = save_version(client=client, graph=graph)
    secret.delete()

    response = _restore(client=client, graph=graph, version_id=version_id)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert [w["type"] for w in response.data["warnings"]] == [
        "secret_declaration_dropped"
    ]
    assert "STRIPE_KEY" in response.data["warnings"][0]["reason"]
    assert _declared_names(graph=graph) == []


@pytest.mark.django_db
def test_create_graph_from_a_version_keeps_the_declaration(
    client, graph_with_declared_secret
):
    graph, _ = graph_with_declared_secret
    version_id = save_version(client=client, graph=graph)

    response = client.post(
        reverse("graph-versions-create-graph", args=[version_id]), format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    new_graph = Graph.objects.get(pk=response.data["graph_id"])
    assert new_graph.pk != graph.pk
    assert _declared_names(graph=new_graph) == ["STRIPE_KEY"]


@pytest.mark.django_db
def test_the_snapshot_is_never_exposed_by_the_read_endpoints(
    client, graph_with_declared_secret
):
    """The declarations block lives in a JSONField the serializer does not expose.
    It holds only names, never values, but it is still an authorisation record —
    and the code in the same snapshot is user source. Neither belongs in a list or
    detail payload."""
    graph, _ = graph_with_declared_secret
    version_id = save_version(client=client, graph=graph)

    detail = client.get(reverse("graph-versions-detail", args=[version_id]))
    listed = client.get(reverse("graph-versions-list"))

    # Both statuses asserted: a 403 body contains none of the forbidden strings
    # either, so without this the test would pass for entirely the wrong reason.
    assert detail.status_code == status.HTTP_200_OK, detail.content
    assert listed.status_code == status.HTTP_200_OK, listed.content
    for payload in (detail.data, listed.data):
        body = str(payload)
        assert "secret_declarations" not in body
        assert "snapshot" not in body
        assert "STRIPE_KEY" not in body

