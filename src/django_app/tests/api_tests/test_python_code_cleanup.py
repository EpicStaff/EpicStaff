"""Cascade-cleanup of orphaned `PythonCode` rows (bug: deleting an owner never
deleted its `PythonCode`, since the FK runs owner -> PythonCode with
on_delete=CASCADE, which only cascades in the PythonCode-deleted direction).

Covers:
- Each of the 5 owner models / 6 FK columns cleaning up on delete.
- The reported bug's actual failure path: the flow-editor bulk-save endpoint's
  queryset `.filter(id__in=...).delete()`, not just per-node DELETE.
- CDT detach-to-None (PATCH clearing pre/post python_code without deleting the
  node) also cleans up, since no post_delete signal fires for a plain
  reassignment.
- Execution history (`PythonCodeResult`, SET_NULL) survives with
  python_code=None.
- The reference-count guard: a PythonCode shared by two owners (only
  producible via direct ORM in this test, mirroring
  tests/graph_versioning_tests/test_manager.py's "shared" fixture) is not
  deleted until the last owner is gone.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ConditionalEdge,
    PythonNode,
    WebhookTriggerNode,
)
from tables.models.python_models import PythonCode, PythonCodeResult, PythonCodeTool
from tables.models.webhook_models import NgrokWebhookConfig, WebhookTrigger
from tests.fixtures import *  # noqa: F401,F403


def _save_url(graph_id: int) -> str:
    return reverse("graphs-save-flow", args=[graph_id])


_PYTHON_CODE_DATA = {
    "code": "def main(): return 42",
    "entrypoint": "main",
    "libraries": [],
}


@pytest.fixture
def ngrok_config(db) -> NgrokWebhookConfig:
    return NgrokWebhookConfig.objects.create(
        name="test_ngrok", auth_token="test_token_123", region="eu"
    )


@pytest.fixture
def webhook_trigger(ngrok_config) -> WebhookTrigger:
    return WebhookTrigger.objects.create(
        path="test-path", ngrok_webhook_config=ngrok_config
    )


# ---------------------------------------------------------------------------
# PythonCodeTool
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_python_code_tool_deletes_python_code(auth_client):
    create_payload = {
        "name": "cleanup-test-tool",
        "description": "",
        "variables": [],
        "python_code": _PYTHON_CODE_DATA,
    }
    create_response = auth_client.post(
        "/api/python-code-tool/", create_payload, format="json"
    )
    assert create_response.status_code == status.HTTP_201_CREATED, create_response.data
    tool_id = create_response.data["id"]
    python_code_id = create_response.data["python_code"]["id"]
    assert PythonCode.objects.filter(id=python_code_id).exists()

    delete_response = auth_client.delete(f"/api/python-code-tool/{tool_id}/")

    assert delete_response.status_code == status.HTTP_204_NO_CONTENT
    assert not PythonCode.objects.filter(id=python_code_id).exists()


# ---------------------------------------------------------------------------
# PythonNode
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_python_node_deletes_python_code(auth_client, graph, python_code):
    node = PythonNode.objects.create(graph=graph, python_code=python_code)
    python_code_id = python_code.id

    response = auth_client.delete(reverse("pythonnode-detail", args=[node.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not PythonCode.objects.filter(id=python_code_id).exists()


# ---------------------------------------------------------------------------
# ConditionalEdge
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_conditional_edge_deletes_python_code(auth_client, graph, python_code):
    edge = ConditionalEdge.objects.create(
        graph=graph, python_code=python_code, source_node_id=None, input_map={}
    )
    python_code_id = python_code.id

    response = auth_client.delete(reverse("conditionaledge-detail", args=[edge.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not PythonCode.objects.filter(id=python_code_id).exists()


# ---------------------------------------------------------------------------
# WebhookTriggerNode
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_webhook_trigger_node_deletes_python_code(
    auth_client, graph, python_code, webhook_trigger, ngrok_config
):
    node = WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="webhook_node",
        python_code=python_code,
        webhook_trigger=webhook_trigger,
    )
    python_code_id = python_code.id

    response = auth_client.delete(reverse("webhooktriggernode-detail", args=[node.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not PythonCode.objects.filter(id=python_code_id).exists()
    # Unrelated models: not touched by this fix.
    assert WebhookTrigger.objects.filter(id=webhook_trigger.id).exists()
    assert NgrokWebhookConfig.objects.filter(id=ngrok_config.id).exists()


# ---------------------------------------------------------------------------
# ClassificationDecisionTableNode — delete with both fields set
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_delete_classification_decision_table_node_deletes_both_python_codes(
    auth_client, graph
):
    pre_code = PythonCode.objects.create(code="def main(): return 1")
    post_code = PythonCode.objects.create(code="def main(): return 2")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="cdt_node",
        pre_python_code=pre_code,
        post_python_code=post_code,
    )

    response = auth_client.delete(
        reverse("classificationdecisiontablenode-detail", args=[node.id])
    )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not PythonCode.objects.filter(id=pre_code.id).exists()
    assert not PythonCode.objects.filter(id=post_code.id).exists()


# ---------------------------------------------------------------------------
# The reported bug's exact failure path: flow-editor bulk-save's queryset
# `.filter(id__in=...).delete()`, not the per-node DELETE endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_bulk_save_delete_python_node_deletes_python_code(
    auth_client, graph, python_code
):
    node = PythonNode.objects.create(graph=graph, python_code=python_code)
    python_code_id = python_code.id

    payload = {
        "save_version": graph.save_version,
        "deleted": {"python_node_ids": [node.id]},
    }
    response = auth_client.post(_save_url(graph.id), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert not PythonNode.objects.filter(id=node.id).exists()
    assert not PythonCode.objects.filter(id=python_code_id).exists()


# ---------------------------------------------------------------------------
# CDT detach-to-None leak: PATCH clearing pre_python_code without deleting the
# node must also clean up (no post_delete signal fires for a reassignment).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_cdt_detach_pre_python_code_to_none_deletes_orphaned_python_code(
    auth_client, graph
):
    pre_code = PythonCode.objects.create(code="def main(): return 1")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt_detach", pre_python_code=pre_code
    )
    pre_code_id = pre_code.id

    response = auth_client.patch(
        reverse("classificationdecisiontablenode-detail", args=[node.id]),
        {"pre_python_code": None},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.data
    node.refresh_from_db()
    assert node.pre_python_code_id is None
    assert not PythonCode.objects.filter(id=pre_code_id).exists()


@pytest.mark.django_db
def test_cdt_detach_post_python_code_to_none_deletes_orphaned_python_code(
    auth_client, graph
):
    post_code = PythonCode.objects.create(code="def main(): return 1")
    node = ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt_detach_post", post_python_code=post_code
    )
    post_code_id = post_code.id

    response = auth_client.patch(
        reverse("classificationdecisiontablenode-detail", args=[node.id]),
        {"post_python_code": None},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.data
    node.refresh_from_db()
    assert node.post_python_code_id is None
    assert not PythonCode.objects.filter(id=post_code_id).exists()


# ---------------------------------------------------------------------------
# Execution history survives (PythonCodeResult.python_code is SET_NULL).
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_deleting_owner_preserves_python_code_result_with_null_python_code(
    auth_client, graph, python_code
):
    node = PythonNode.objects.create(graph=graph, python_code=python_code)
    result = PythonCodeResult.objects.create(
        execution_id="cleanup-test-execution-1",
        python_code=python_code,
    )
    python_code_id = python_code.id

    response = auth_client.delete(reverse("pythonnode-detail", args=[node.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not PythonCode.objects.filter(id=python_code_id).exists()
    result.refresh_from_db()
    assert result.python_code_id is None


# ---------------------------------------------------------------------------
# Guard correctness: a PythonCode shared by two CASCADE owners (only
# producible via direct ORM setup, since normal write paths always create a
# fresh row) must survive deleting one owner and only disappear once the
# last owner is gone.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_shared_python_code_survives_until_last_owner_deleted(
    auth_client, graph, python_code
):
    tool = PythonCodeTool.objects.create(
        name="shared-code-tool",
        description="",
        variables=[],
        python_code=python_code,
    )
    node = PythonNode.objects.create(graph=graph, python_code=python_code)
    python_code_id = python_code.id

    first_response = auth_client.delete(
        reverse("pythoncodetool-detail", args=[tool.id])
    )
    assert first_response.status_code == status.HTTP_204_NO_CONTENT
    assert PythonCode.objects.filter(id=python_code_id).exists()

    second_response = auth_client.delete(reverse("pythonnode-detail", args=[node.id]))
    assert second_response.status_code == status.HTTP_204_NO_CONTENT
    assert not PythonCode.objects.filter(id=python_code_id).exists()
