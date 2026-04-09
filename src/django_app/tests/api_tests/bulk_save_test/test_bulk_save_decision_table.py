import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import (
    ConditionGroup,
    DecisionTableNode,
    Edge,
    PythonNode,
)
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


_PYTHON_CODE_DATA = {
    "code": "def main(): return 42",
    "entrypoint": "main",
    "libraries": [],
}


def _make_python_node_payload(graph_id, temp_id, name="PN"):
    return {
        "graph": graph_id,
        "temp_id": temp_id,
        "node_name": name,
        "python_code": _PYTHON_CODE_DATA,
    }


def _make_group(group_name, order, group_type="simple", **kwargs):
    """Build a condition group dict. Accepts expression, manipulation, next_node_id, next_node_temp_id."""
    group = {
        "group_name": group_name,
        "group_type": group_type,
        "order": order,
    }
    group.update(kwargs)
    return group


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def python_node_a(graph, python_code) -> PythonNode:
    return PythonNode.objects.create(
        graph=graph, python_code=python_code, node_name="pn_a"
    )


@pytest.fixture
def python_node_b(graph, python_code) -> PythonNode:
    from tables.models.python_models import PythonCode

    code_b = PythonCode.objects.create(code="def main(): return 99", entrypoint="main")
    return PythonNode.objects.create(graph=graph, python_code=code_b, node_name="pn_b")


@pytest.fixture
def decision_table_node(graph) -> DecisionTableNode:
    return DecisionTableNode.objects.create(graph=graph, node_name="dt_node")


# ---------------------------------------------------------------------------
# CREATE — DTN with routing to real nodes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_dtn_with_default_and_error_routing(
    api_client, graph, python_node_a, python_node_b
):
    """Create DTN with default_next_node_id and next_error_node_id pointing to existing nodes."""
    payload = {
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_routed",
                "default_next_node_id": python_node_a.id,
                "next_error_node_id": python_node_b.id,
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    node = DecisionTableNode.objects.get(graph=graph, node_name="dt_routed")
    assert node.default_next_node_id == python_node_a.id
    assert node.next_error_node_id == python_node_b.id


# ---------------------------------------------------------------------------
# CREATE — DTN with routing via temp_ids (deferred resolution)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_dtn_with_routing_temp_ids(api_client, graph):
    """default_next and next_error both reference new PythonNodes via temp_id."""
    temp_a = "aaaa0001-0001-0001-0001-aaaaaaaaaaaa"
    temp_b = "aaaa0002-0002-0002-0002-aaaaaaaaaaaa"

    payload = {
        "python_node_list": [
            _make_python_node_payload(graph.id, temp_a, "pn_default"),
            _make_python_node_payload(graph.id, temp_b, "pn_error"),
        ],
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_temp_routing",
                "default_next_node_temp_id": temp_a,
                "next_error_node_temp_id": temp_b,
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    pn_default = PythonNode.objects.get(graph=graph, node_name="pn_default")
    pn_error = PythonNode.objects.get(graph=graph, node_name="pn_error")
    dt = DecisionTableNode.objects.get(graph=graph, node_name="dt_temp_routing")
    assert dt.default_next_node_id == pn_default.id
    assert dt.next_error_node_id == pn_error.id


# ---------------------------------------------------------------------------
# CREATE — condition groups with next_node_id (real)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_dtn_with_groups_routing_to_real_nodes(
    api_client, graph, python_node_a, python_node_b
):
    payload = {
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_groups_real",
                "condition_groups": [
                    _make_group(
                        "high",
                        0,
                        expression="score * 2",
                        next_node_id=python_node_a.id,
                    ),
                    _make_group(
                        "low",
                        1,
                        manipulation="round_down",
                        next_node_id=python_node_b.id,
                    ),
                ],
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    dt = DecisionTableNode.objects.get(graph=graph, node_name="dt_groups_real")
    groups = ConditionGroup.objects.filter(decision_table_node=dt).order_by("order")
    assert groups.count() == 2
    assert groups[0].next_node_id == python_node_a.id
    assert groups[0].expression == "score * 2"
    assert groups[1].next_node_id == python_node_b.id
    assert groups[1].manipulation == "round_down"


# ---------------------------------------------------------------------------
# CREATE — condition groups with next_node_temp_id (deferred)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_dtn_with_groups_routing_via_temp_ids(api_client, graph):
    temp_a = "bbbb0001-0001-0001-0001-bbbbbbbbbbbb"
    temp_b = "bbbb0002-0002-0002-0002-bbbbbbbbbbbb"

    payload = {
        "python_node_list": [
            _make_python_node_payload(graph.id, temp_a, "pn_high"),
            _make_python_node_payload(graph.id, temp_b, "pn_low"),
        ],
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_groups_temp",
                "condition_groups": [
                    _make_group("high", 0, next_node_temp_id=temp_a),
                    _make_group("low", 1, next_node_temp_id=temp_b),
                ],
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    pn_high = PythonNode.objects.get(graph=graph, node_name="pn_high")
    pn_low = PythonNode.objects.get(graph=graph, node_name="pn_low")
    dt = DecisionTableNode.objects.get(graph=graph, node_name="dt_groups_temp")
    groups = ConditionGroup.objects.filter(decision_table_node=dt).order_by("order")
    assert groups[0].next_node_id == pn_high.id
    assert groups[1].next_node_id == pn_low.id


# ---------------------------------------------------------------------------
# CREATE — mixed routing: some groups real, some temp, node-level temp
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_dtn_mixed_real_and_temp_routing(api_client, graph, python_node_a):
    temp_new = "cccc0001-0001-0001-0001-cccccccccccc"

    payload = {
        "python_node_list": [
            _make_python_node_payload(graph.id, temp_new, "pn_new"),
        ],
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_mixed",
                "default_next_node_temp_id": temp_new,
                "next_error_node_id": python_node_a.id,
                "condition_groups": [
                    _make_group("real_route", 0, next_node_id=python_node_a.id),
                    _make_group(
                        "temp_route",
                        1,
                        expression="val + 1",
                        next_node_temp_id=temp_new,
                    ),
                ],
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    pn_new = PythonNode.objects.get(graph=graph, node_name="pn_new")
    dt = DecisionTableNode.objects.get(graph=graph, node_name="dt_mixed")

    assert dt.default_next_node_id == pn_new.id
    assert dt.next_error_node_id == python_node_a.id

    groups = ConditionGroup.objects.filter(decision_table_node=dt).order_by("order")
    assert groups[0].next_node_id == python_node_a.id
    assert groups[1].next_node_id == pn_new.id
    assert groups[1].expression == "val + 1"


# ---------------------------------------------------------------------------
# UPDATE — clear all condition groups
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_dtn_clear_all_groups(api_client, graph, decision_table_node):
    ConditionGroup.objects.create(
        decision_table_node=decision_table_node,
        group_name="old",
        group_type="simple",
        order=0,
    )
    assert (
        ConditionGroup.objects.filter(decision_table_node=decision_table_node).count()
        == 1
    )

    payload = {
        "decision_table_node_list": [
            {
                "id": decision_table_node.id,
                "graph": graph.id,
                "node_name": "dt_node",
                "condition_groups": [],
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    assert (
        ConditionGroup.objects.filter(decision_table_node=decision_table_node).count()
        == 0
    )


# ---------------------------------------------------------------------------
# UPDATE — replace groups with new routing to new temp_id nodes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_dtn_replace_groups_with_temp_routing(
    api_client, graph, decision_table_node
):
    old_group = ConditionGroup.objects.create(
        decision_table_node=decision_table_node,
        group_name="old_group",
        group_type="simple",
        order=0,
    )

    temp_pn = "dddd0001-0001-0001-0001-dddddddddddd"
    payload = {
        "python_node_list": [
            _make_python_node_payload(graph.id, temp_pn, "pn_replacement"),
        ],
        "decision_table_node_list": [
            {
                "id": decision_table_node.id,
                "graph": graph.id,
                "node_name": "dt_node",
                "default_next_node_temp_id": temp_pn,
                "condition_groups": [
                    _make_group(
                        "new_group",
                        0,
                        group_type="complex",
                        expression="x + y",
                        manipulation="uppercase",
                        next_node_temp_id=temp_pn,
                    ),
                ],
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content

    # Old group gone
    assert not ConditionGroup.objects.filter(id=old_group.id).exists()

    pn = PythonNode.objects.get(graph=graph, node_name="pn_replacement")
    decision_table_node.refresh_from_db()
    assert decision_table_node.default_next_node_id == pn.id

    new_group = ConditionGroup.objects.get(decision_table_node=decision_table_node)
    assert new_group.group_name == "new_group"
    assert new_group.group_type == "complex"
    assert new_group.expression == "x + y"
    assert new_group.manipulation == "uppercase"
    assert new_group.next_node_id == pn.id


# ---------------------------------------------------------------------------
# CREATE — condition group fields: expression, manipulation, group_type
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_create_dtn_group_with_all_fields(api_client, graph, python_node_a):
    payload = {
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_full_fields",
                "condition_groups": [
                    _make_group(
                        "full_group",
                        0,
                        group_type="complex",
                        expression="a + b * c",
                        manipulation="trim_lower",
                        next_node_id=python_node_a.id,
                    ),
                ],
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content
    dt = DecisionTableNode.objects.get(graph=graph, node_name="dt_full_fields")
    group = ConditionGroup.objects.get(decision_table_node=dt)
    assert group.group_type == "complex"
    assert group.expression == "a + b * c"
    assert group.manipulation == "trim_lower"
    assert group.next_node_id == python_node_a.id


# ---------------------------------------------------------------------------
# DTN + edge chain: DTN default routes to new PN, edge connects them
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dtn_with_edge_chain_to_new_python_nodes(api_client, graph):
    temp_dt = "eeee0001-0001-0001-0001-eeeeeeeeeeee"
    temp_pn1 = "eeee0002-0002-0002-0002-eeeeeeeeeeee"
    temp_pn2 = "eeee0003-0003-0003-0003-eeeeeeeeeeee"

    payload = {
        "python_node_list": [
            _make_python_node_payload(graph.id, temp_pn1, "chain_1"),
            _make_python_node_payload(graph.id, temp_pn2, "chain_2"),
        ],
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_chain",
                "temp_id": temp_dt,
                "default_next_node_temp_id": temp_pn1,
                "condition_groups": [
                    _make_group("route_to_2", 0, next_node_temp_id=temp_pn2),
                ],
            }
        ],
        "edge_list": [
            {
                "graph": graph.id,
                "start_temp_id": temp_dt,
                "end_temp_id": temp_pn1,
                "metadata": {},
            },
            {
                "graph": graph.id,
                "start_temp_id": temp_pn1,
                "end_temp_id": temp_pn2,
                "metadata": {},
            },
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_200_OK, resp.content

    dt = DecisionTableNode.objects.get(graph=graph, node_name="dt_chain")
    pn1 = PythonNode.objects.get(graph=graph, node_name="chain_1")
    pn2 = PythonNode.objects.get(graph=graph, node_name="chain_2")

    assert dt.default_next_node_id == pn1.id
    group = ConditionGroup.objects.get(decision_table_node=dt)
    assert group.next_node_id == pn2.id

    assert Edge.objects.filter(
        graph=graph, start_node_id=dt.id, end_node_id=pn1.id
    ).exists()
    assert Edge.objects.filter(
        graph=graph, start_node_id=pn1.id, end_node_id=pn2.id
    ).exists()


# ---------------------------------------------------------------------------
# Validation — both *_node_id and *_node_temp_id provided
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dtn_both_default_next_id_and_temp_id_rejected(
    api_client, graph, python_node_a
):
    temp = "ffff0001-0001-0001-0001-ffffffffffff"
    payload = {
        "python_node_list": [
            _make_python_node_payload(graph.id, temp, "pn_unused"),
        ],
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_conflict",
                "default_next_node_id": python_node_a.id,
                "default_next_node_temp_id": temp,
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "decision_table_node_list" in resp.data["errors"]


@pytest.mark.django_db
def test_dtn_group_both_next_node_id_and_temp_id_rejected(
    api_client, graph, python_node_a
):
    temp = "ffff0002-0002-0002-0002-ffffffffffff"
    payload = {
        "python_node_list": [
            _make_python_node_payload(graph.id, temp, "pn_unused"),
        ],
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_group_conflict",
                "condition_groups": [
                    _make_group(
                        "bad_group",
                        0,
                        next_node_id=python_node_a.id,
                        next_node_temp_id=temp,
                    ),
                ],
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "decision_table_node_list" in resp.data["errors"]


# ---------------------------------------------------------------------------
# Validation — unknown temp_id in routing
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dtn_unknown_default_next_temp_id_rejected(api_client, graph):
    payload = {
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_bad_ref",
                "default_next_node_temp_id": "00000000-0000-0000-0000-000000000000",
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "decision_table_node_list" in resp.data["errors"]


@pytest.mark.django_db
def test_dtn_group_unknown_next_node_temp_id_rejected(api_client, graph):
    payload = {
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_bad_group_ref",
                "condition_groups": [
                    _make_group(
                        "bad_ref_group",
                        0,
                        next_node_temp_id="00000000-0000-0000-0000-999999999999",
                    ),
                ],
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert "decision_table_node_list" in resp.data["errors"]


# ---------------------------------------------------------------------------
# Validation — nonexistent real node id in routing
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_dtn_nonexistent_default_next_node_id_rejected(api_client, graph):
    payload = {
        "decision_table_node_list": [
            {
                "graph": graph.id,
                "node_name": "dt_bad_real_ref",
                "default_next_node_id": 999999,
            }
        ],
    }
    resp = api_client.post(_save_url(graph.id), payload, format="json")

    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
