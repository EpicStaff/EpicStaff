"""POST /api/run-python-code/ with `target`: test mode runs a node's code slot
with the payload a real run would send — storage scope, org_id and secrets —
while the legacy `python_code_id` path keeps running the bare code.

Real view, service, converter and secret resolver; only the Redis client is
mocked (`redis_client_mock`), so the published sandbox message is what is
asserted."""

import json

import pytest
from django.utils import timezone

from rbac.models import OrganizationUser
from tables.models import Graph, PythonCode, PythonCodeResult, PythonNode
from tables.models.graph_models import GraphStorageFile, StorageFile, WebhookTriggerNode
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

URL = "/api/run-python-code/"
PLAINTEXT = "sk-target-run-abc123"


def _published_tasks(redis_client_mock):
    return [json.loads(call.args[1]) for call in redis_client_mock.publish.call_args_list]


@pytest.fixture
def acme_client(client_as, member_only, acme):
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="acme-target-run", org=acme)


@pytest.fixture
def beta_graph(beta):
    return Graph.objects.create(name="beta-target-run", org=beta)


@pytest.fixture
def attached_file(acme, acme_graph):
    storage_file = StorageFile.objects.create(org=acme, name="input.csv", path="docs/input.csv")
    GraphStorageFile.objects.create(graph=acme_graph, storage_file=storage_file)
    return storage_file


def _python_node(graph, *, use_storage, code="def main(): return 1"):
    python_code = PythonCode.objects.create(code=code, entrypoint="main")
    return PythonNode.objects.create(graph=graph, python_code=python_code, use_storage=use_storage)


def _run_target(client, target_type, target_id, variables=None):
    return client.post(
        URL,
        {"target": {"type": target_type, "id": target_id}, "variables": variables or {}},
        format="json",
    )


@pytest.mark.django_db
class TestPythonNodeTarget:
    def test_storage_node_gets_attached_files_and_its_test_run_folder(
        self, acme_client, acme, acme_graph, attached_file, member_only, redis_client_mock
    ):
        node = _python_node(acme_graph, use_storage=True)

        response = _run_target(acme_client, "python_node", node.id, {"x": 1})

        assert response.status_code == 200, response.data
        [task] = _published_tasks(redis_client_mock)
        assert task["use_storage"] is True
        assert task["storage_allowed_paths"] == [
            "docs/input.csv",
            f"test-runs/python_node-{node.id}/",
        ]
        assert task["storage_org_prefix"] == f"org_{acme.id}"
        assert task["org_id"] == acme.id
        assert task["global_kwargs"]["org_id"] == acme.id
        assert task["session_id"] is None
        assert task["func_kwargs"] == {"x": 1}
        assert task["execution_id"] == response.data["execution_id"]
        result = PythonCodeResult.objects.get(execution_id=response.data["execution_id"])
        assert result.python_code_id == node.python_code_id
        assert result.org_id == acme.id
        assert result.created_by == member_only
        assert result.status == PythonCodeResult.Status.PENDING

    def test_storage_node_without_attached_files_still_gets_its_folder(
        self, acme_client, acme_graph, redis_client_mock
    ):
        node = _python_node(acme_graph, use_storage=True)

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _published_tasks(redis_client_mock)
        assert task["storage_allowed_paths"] == [f"test-runs/python_node-{node.id}/"]

    def test_node_without_storage_sends_no_storage_fields(
        self, acme_client, acme, acme_graph, attached_file, redis_client_mock
    ):
        node = _python_node(acme_graph, use_storage=False)

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _published_tasks(redis_client_mock)
        assert task["use_storage"] is False
        assert task["storage_allowed_paths"] is None
        assert task["storage_org_prefix"] is None
        assert task["org_id"] == acme.id
        assert task["global_kwargs"]["org_id"] == acme.id

    def test_declared_secret_reaches_the_sandbox_message(
        self, acme_client, acme, acme_graph, redis_client_mock
    ):
        secret = secret_service.create(text=PLAINTEXT, org=acme, name="TARGET_KEY")
        node = _python_node(
            acme_graph, use_storage=False, code='def main(): return get_secret("TARGET_KEY")'
        )
        node.python_code.secrets.set([secret])

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _published_tasks(redis_client_mock)
        assert task["secrets"] == {"TARGET_KEY": PLAINTEXT}

    def test_undeclared_secret_is_rejected_before_anything_is_written(
        self, acme_client, acme, acme_graph, redis_client_mock
    ):
        secret_service.create(text=PLAINTEXT, org=acme, name="TARGET_KEY")
        node = _python_node(
            acme_graph, use_storage=True, code='def main(): return get_secret("TARGET_KEY")'
        )

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 400
        assert "TARGET_KEY" in str(response.data)
        assert not redis_client_mock.publish.call_args_list
        assert not PythonCodeResult.objects.exists()


@pytest.mark.django_db
def test_webhook_trigger_node_target_runs_without_storage(
    acme_client, acme_graph, attached_file, redis_client_mock
):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    node = WebhookTriggerNode.objects.create(
        graph=acme_graph, node_name="webhook_entry", python_code=python_code
    )

    response = _run_target(acme_client, "webhook_trigger_node", node.id)

    assert response.status_code == 200, response.data
    [task] = _published_tasks(redis_client_mock)
    assert task["use_storage"] is False
    assert task["storage_allowed_paths"] is None
    assert task["storage_org_prefix"] is None
    assert PythonCodeResult.objects.get(
        execution_id=response.data["execution_id"]
    ).python_code_id == python_code.id


@pytest.mark.django_db
class TestTargetLookupIsOrgScoped:
    def test_node_of_another_org_is_not_found(self, acme_client, beta_graph, redis_client_mock):
        node = _python_node(beta_graph, use_storage=True)

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 400
        assert response.data["message"] == (
            f'target: Invalid pk "{node.id}" - object does not exist.'
        )
        assert not redis_client_mock.publish.call_args_list
        assert not PythonCodeResult.objects.exists()

    def test_webhook_trigger_node_of_another_org_is_not_found(
        self, acme_client, beta_graph, redis_client_mock
    ):
        python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
        node = WebhookTriggerNode.objects.create(
            graph=beta_graph, node_name="webhook_entry", python_code=python_code
        )

        response = _run_target(acme_client, "webhook_trigger_node", node.id)

        assert response.status_code == 400
        assert "does not exist" in response.data["message"]
        assert not redis_client_mock.publish.call_args_list

    def test_soft_deleted_node_is_not_found(self, acme_client, acme_graph, redis_client_mock):
        node = _python_node(acme_graph, use_storage=True)
        PythonNode.all_objects.filter(pk=node.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 400
        assert "does not exist" in response.data["message"]
        assert not redis_client_mock.publish.call_args_list

    def test_missing_node_is_not_found(self, acme_client, redis_client_mock):
        response = _run_target(acme_client, "python_node", 999_999)

        assert response.status_code == 400
        assert "does not exist" in response.data["message"]

    def test_caller_without_flows_update_is_denied(
        self, client_as, django_user_model, acme, acme_graph, role_viewer, redis_client_mock
    ):
        viewer = django_user_model.objects.create_user(
            email="viewer-target-run@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=viewer, org=acme, role=role_viewer)
        client = client_as(viewer)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        node = _python_node(acme_graph, use_storage=True)

        response = _run_target(client, "python_node", node.id)

        assert response.status_code == 403
        assert not redis_client_mock.publish.call_args_list


@pytest.mark.django_db
class TestRequestShape:
    def test_both_target_and_python_code_id_is_rejected(
        self, acme_client, acme_graph, redis_client_mock
    ):
        node = _python_node(acme_graph, use_storage=False)

        response = acme_client.post(
            URL,
            {
                "target": {"type": "python_node", "id": node.id},
                "python_code_id": node.python_code_id,
            },
            format="json",
        )

        assert response.status_code == 400
        assert "exactly one" in response.data["message"]
        assert not redis_client_mock.publish.call_args_list

    def test_neither_target_nor_python_code_id_is_rejected(self, acme_client, redis_client_mock):
        response = acme_client.post(URL, {"variables": {}}, format="json")

        assert response.status_code == 400
        assert "exactly one" in response.data["message"]

    def test_unknown_target_type_is_rejected(self, acme_client, acme_graph, redis_client_mock):
        node = _python_node(acme_graph, use_storage=False)

        response = _run_target(acme_client, "agent_node", node.id)

        assert response.status_code == 400
        assert "agent_node" in response.data["message"]
        assert not redis_client_mock.publish.call_args_list

    def test_legacy_python_code_id_runs_bare_code_without_storage(
        self, acme_client, acme_graph, attached_file, redis_client_mock
    ):
        node = _python_node(acme_graph, use_storage=True)

        response = acme_client.post(
            URL, {"python_code_id": node.python_code_id, "variables": {"x": 1}}, format="json"
        )

        assert response.status_code == 200, response.data
        [task] = _published_tasks(redis_client_mock)
        assert task["venv_name"] == f"venv_{node.python_code_id}"
        assert task["use_storage"] is False
        assert task["storage_allowed_paths"] is None
        assert task["org_id"] is None
        assert "org_id" not in task["global_kwargs"]
        assert task["func_kwargs"] == {"x": 1}
