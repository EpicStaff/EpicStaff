"""Pins the N+1 fix for CDT nodes' two PythonCode secret sets on GET /api/graphs/."""

# `ClassificationDecisionTableNodeSerializer` nests `PythonCodeSerializer` (which
# exposes the `secrets` M2M) twice, as `pre_python_code` and `post_python_code`.
# `GraphViewSet.get_queryset` prefetches every other node-list's PythonCode/secrets
# pair but, before this fix, had no `Prefetch` entry for
# `classification_decision_table_node_list` at all — so serializing a graph's CDT
# nodes cost 2 extra queries (one per code block's `secrets` M2M) per node.
#
# Follows the few-vs-many `CaptureQueriesContext` scaling comparison in
# tests/services_tests/test_soft_delete_cascade.py rather than an exact
# `django_assert_num_queries` count: GET /api/graphs/ carries a dozen-plus
# unrelated prefetches, so an absolute count would break on any unrelated change
# to that queryset. What actually matters is that the query count does not grow
# with the number of CDT nodes, which this test isolates by putting each
# graph in its own org so a single list call returns exactly one graph.
#
# The total per-request query count is deliberately NOT the assertion. CDT
# nodes also expose `condition_groups` and `prompt_configs` — two more
# reverse-FK lists with no prefetch anywhere in `GraphViewSet.get_queryset`,
# which is a separate, pre-existing N+1 outside this task's scope (the brief
# covers only `pre_python_code`/`post_python_code` and their `secrets`). Left
# in, that unrelated N+1 would make the total count scale with node count
# regardless of this fix, and the test would fail for the wrong reason. So the
# assertion filters `CaptureQueriesContext.captured_queries` down to the ones
# touching `tables_pythoncode`/`tables_secret` — exactly the tables this fix's
# `Prefetch`/`select_related` chain touches — and checks that subset is flat.

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from tables.models import PythonCode
from tables.models.graph_models import ClassificationDecisionTableNode, Graph
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.secrets import secret_service

GRAPHS_URL = "/api/graphs/"

_RELEVANT_TABLES = ("tables_pythoncode", "tables_secret")


def _relevant_query_count(captured):
    """Count captured queries that touch the PythonCode/secrets tables this fix's Prefetch/select_related chain targets."""
    return sum(
        1
        for query in captured.captured_queries
        if any(table in query["sql"] for table in _RELEVANT_TABLES)
    )


def _client_for(*, org, django_user_model, email):
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


def _build_graph_with_cdt_nodes(*, org, node_count: int) -> Graph:
    """Create a graph with `node_count` CDT nodes, each with pre/post PythonCode carrying a secret."""
    graph = Graph.objects.create(name=f"flow-{org.pk}", org=org)
    secret = secret_service.create(text="sk-live-x", org=org, name=f"SECRET_{org.pk}")
    for index in range(node_count):
        pre_code = PythonCode.objects.create(code="def main(): return 1")
        pre_code.secrets.set([secret])
        post_code = PythonCode.objects.create(code="def main(): return 2")
        post_code.secrets.set([secret])
        ClassificationDecisionTableNode.objects.create(
            graph=graph,
            node_name=f"cdt-{index}",
            pre_python_code=pre_code,
            post_python_code=post_code,
        )
    return graph


@pytest.mark.django_db
def test_graph_list_query_count_does_not_scale_with_cdt_node_count(django_user_model):
    small_org = Organization.objects.create(name="Org Small CDT")
    large_org = Organization.objects.create(name="Org Large CDT")
    _build_graph_with_cdt_nodes(org=small_org, node_count=2)
    _build_graph_with_cdt_nodes(org=large_org, node_count=8)
    small_client = _client_for(
        org=small_org, django_user_model=django_user_model, email="small@example.com"
    )
    large_client = _client_for(
        org=large_org, django_user_model=django_user_model, email="large@example.com"
    )

    with CaptureQueriesContext(connection) as few:
        small_response = small_client.get(GRAPHS_URL)

    with CaptureQueriesContext(connection) as many:
        large_response = large_client.get(GRAPHS_URL)

    assert small_response.status_code == 200, small_response.content
    assert large_response.status_code == 200, large_response.content

    small_results = small_response.data["results"]
    large_results = large_response.data["results"]
    assert len(small_results) == 1
    assert len(large_results) == 1

    small_nodes = small_results[0]["classification_decision_table_node_list"]
    large_nodes = large_results[0]["classification_decision_table_node_list"]
    assert len(small_nodes) == 2
    assert len(large_nodes) == 8

    # Both node lists must actually carry the serialized secret declarations —
    # otherwise a flat query count could mean the CDT nodes were never reached.
    for node in small_nodes + large_nodes:
        assert node["pre_python_code"]["secrets"][0]["name"].startswith("SECRET_")
        assert node["post_python_code"]["secrets"][0]["name"].startswith("SECRET_")

    few_relevant = _relevant_query_count(few)
    many_relevant = _relevant_query_count(many)
    assert few_relevant == many_relevant, (
        f"PythonCode/secrets query count grew from {few_relevant} (2 CDT nodes) "
        f"to {many_relevant} (8 CDT nodes):\n"
        + "\n".join(
            query["sql"]
            for query in many.captured_queries
            if any(table in query["sql"] for table in _RELEVANT_TABLES)
        )
    )
