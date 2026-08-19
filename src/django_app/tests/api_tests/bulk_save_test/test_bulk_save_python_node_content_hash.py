"""Regression tests for the content_hash CAS reorder fix on the bulk-save
path, for the serializers sharing ``NestedPythonCodeMixin``:
PythonNodeSerializer, ConditionalEdgeSerializer, WebhookTriggerNodeSerializer.

``NestedPythonCodeMixin.update()`` used to write the nested ``PythonCode``
row first, then check the parent's content_hash precondition — but the
parent's hash folds in the nested row's hash, so the check always compared
against a value already mutated by the write it was meant to guard,
producing a deterministic false conflict. Positive tests here send a real,
freshly-fetched content_hash alongside a nested code change; negative tests
confirm the guard still fires on a genuine conflict.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import ConditionalEdge, PythonNode, WebhookTriggerNode
from tables.models.python_models import PythonCode
from tests.fixtures import *  # noqa: F401,F403


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


def _fresh_python_node(node_id: int) -> PythonNode:
    """Re-fetch with python_code selected so content_hash reflects the
    CURRENT DB state (the cached in-memory instance may be stale)."""
    return PythonNode.objects.select_related("python_code").get(pk=node_id)


# ---------------------------------------------------------------------------
# 1. Regression: the reported bug — real pre-edit hash + nested code change.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_python_node_with_correct_hash_and_code_change_succeeds(
    auth_client, graph, python_node
):
    current = _fresh_python_node(python_node.id)
    pre_edit_hash = current.content_hash
    pre_edit_nested_hash = current.python_code.content_hash
    pre_edit_python_code_id = current.python_code_id
    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "id": current.id,
                "graph": graph.id,
                "content_hash": pre_edit_hash,
                "python_code": {
                    "code": "def main(): return 'edited'",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "content_hash": pre_edit_nested_hash,
                },
            },
        ],
    }

    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    final = _fresh_python_node(python_node.id)
    assert final.python_code.code == "def main(): return 'edited'"
    assert final.python_code_id == pre_edit_python_code_id, (
        "Arming both the outer and nested content_hash must still update the "
        "existing PythonCode row in place, not replace it."
    )


# ---------------------------------------------------------------------------
# 2. Genuine conflict still detected — outer (top-level) content_hash stale.
#    This is the most important test in the file: it proves the guard was
#    reordered, not removed.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_python_node_with_stale_outer_hash_returns_409(
    auth_client, graph, python_node
):
    stale_hash = python_node.content_hash

    # Out-of-band write bypassing the model's save()/CAS entirely — simulates
    # a second editor's already-flushed change.
    PythonNode.objects.filter(pk=python_node.id).update(node_name="changed_out_of_band")

    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "id": python_node.id,
                "graph": graph.id,
                "content_hash": stale_hash,
                "python_code": {
                    "code": "def main(): return 'should_not_persist'",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
            },
        ],
    }

    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    assert response.data["code"] == "content_hash_conflict"
    python_node.python_code.refresh_from_db()
    assert python_node.python_code.code != "def main(): return 'should_not_persist'", (
        "A stale outer content_hash must not let the nested python_code write "
        "through before the conflict is raised."
    )


# ---------------------------------------------------------------------------
# 3. Genuine conflict still detected — nested content_hash stale.
#    The nested CAS in _update_python_code was deliberately left untouched.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_python_node_with_stale_nested_hash_returns_409(
    auth_client, graph, python_node
):
    stale_nested_hash = python_node.python_code.content_hash

    # Out-of-band write to the nested PythonCode row only.
    PythonCode.objects.filter(pk=python_node.python_code_id).update(
        code="def main(): return 'server_side_change'"
    )

    payload = {
        "save_version": graph.save_version,
        "python_node_list": [
            {
                "id": python_node.id,
                "graph": graph.id,
                # No top-level content_hash — isolates the nested check.
                "python_code": {
                    "code": "def main(): return 'should_not_persist'",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "content_hash": stale_nested_hash,
                },
            },
        ],
    }

    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_409_CONFLICT, response.content
    assert response.data["code"] == "content_hash_conflict"
    persisted_code = PythonCode.objects.get(pk=python_node.python_code_id).code
    assert persisted_code == "def main(): return 'server_side_change'", (
        "A stale nested content_hash must not let the new code overwrite the "
        "out-of-band write."
    )


# ---------------------------------------------------------------------------
# 4. No duplication across successive correctly-hashed flushes.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_repeated_correct_hash_updates_do_not_duplicate_rows(
    auth_client, graph, python_node
):
    original_python_code_id = python_node.python_code_id
    node_count_before = PythonNode.objects.count()
    python_code_count_before = PythonCode.objects.count()

    for attempt, new_code in enumerate(
        ["def main(): return 'first'", "def main(): return 'second'", "def main(): return 'third'"]
    ):
        current = _fresh_python_node(python_node.id)
        payload = {
            "save_version": graph.save_version,
            "python_node_list": [
                {
                    "id": current.id,
                    "graph": graph.id,
                    "content_hash": current.content_hash,
                    "python_code": {
                        "code": new_code,
                        "entrypoint": "main",
                        "libraries": [],
                        "global_kwargs": {},
                        "content_hash": current.python_code.content_hash,
                    },
                },
            ],
        }
        response = auth_client.post(_save_url(graph.id), payload, format="json")
        assert response.status_code == status.HTTP_200_OK, (
            f"Flush #{attempt + 1} failed: {response.content}"
        )
        graph.refresh_from_db(fields=["save_version"])

    assert PythonNode.objects.count() == node_count_before, (
        "PythonNode row count drifted across repeated correctly-hashed saves."
    )
    assert PythonCode.objects.count() == python_code_count_before, (
        "PythonCode row count drifted across repeated correctly-hashed saves — "
        "a new PythonCode row was created instead of updating the existing one."
    )
    final = _fresh_python_node(python_node.id)
    assert final.python_code_id == original_python_code_id, (
        "python_node.python_code_id changed across repeated saves — the nested "
        "PythonCode row was replaced rather than updated in place."
    )
    assert final.python_code.code == "def main(): return 'third'"


# ---------------------------------------------------------------------------
# 5. Same positive regression coverage for ConditionalEdge and
#    WebhookTriggerNode — both share NestedPythonCodeMixin and were equally
#    broken.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_update_conditional_edge_with_correct_hash_and_code_change_succeeds(
    auth_client, graph, crew_node
):
    python_code = PythonCode.objects.create(
        code="def main(): return True",
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )
    conditional_edge = ConditionalEdge.objects.create(
        graph=graph,
        python_code=python_code,
        source_node_id=crew_node.id,
        input_map={},
    )
    pre_edit_hash = conditional_edge.content_hash
    pre_edit_nested_hash = python_code.content_hash
    pre_edit_python_code_id = python_code.id

    payload = {
        "save_version": graph.save_version,
        "conditional_edge_list": [
            {
                "id": conditional_edge.id,
                "graph": graph.id,
                "source_node_id": crew_node.id,
                "input_map": {},
                "content_hash": pre_edit_hash,
                "python_code": {
                    "code": "def main(): return False",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "content_hash": pre_edit_nested_hash,
                },
            },
        ],
    }

    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    python_code.refresh_from_db()
    assert python_code.code == "def main(): return False"
    assert python_code.id == pre_edit_python_code_id


@pytest.mark.django_db
def test_update_webhook_trigger_node_with_correct_hash_and_code_change_succeeds(
    auth_client, graph
):
    python_code = PythonCode.objects.create(
        code="def main(): return {}",
        entrypoint="main",
        libraries="",
        global_kwargs={},
    )
    webhook_node = WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="webhook_node_1",
        python_code=python_code,
        webhook_trigger=None,
    )
    pre_edit_hash = webhook_node.content_hash
    pre_edit_nested_hash = python_code.content_hash
    pre_edit_python_code_id = python_code.id

    payload = {
        "save_version": graph.save_version,
        "webhook_trigger_node_list": [
            {
                "id": webhook_node.id,
                "graph": graph.id,
                "node_name": webhook_node.node_name,
                "metadata": {},
                "content_hash": pre_edit_hash,
                "webhook_trigger": None,
                "python_code": {
                    "code": "def main(): return {'changed': True}",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "content_hash": pre_edit_nested_hash,
                },
            },
        ],
    }

    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    python_code.refresh_from_db()
    assert python_code.code == "def main(): return {'changed': True}"
    assert python_code.id == pre_edit_python_code_id
