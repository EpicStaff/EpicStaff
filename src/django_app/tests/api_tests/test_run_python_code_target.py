"""POST /api/run-python-code/ with `target`: test mode runs a node's code slot
with the payload a real run would send — storage scope, org_id and secrets —
while the legacy `python_code_id` path keeps running the bare code.

Real view, service, converter and secret resolver. The Redis client is mocked
(`redis_client_mock`), so the published sandbox message is what is asserted, and
so is minting storage credentials (`minted_credentials`), which would otherwise
need the organization's storage admin account in the object store."""

import json

import pytest
from django.utils import timezone
from src.shared.models.storage_scope import StorageCredentials
from storage_credentials.services.session_credential_service import session_credential_service

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode, PythonCodeResult, PythonNode
from tables.models.graph_models import GraphStorageFile, StorageFile, WebhookTriggerNode
from tables.services.secrets import secret_service
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

URL = "/api/run-python-code/"
PLAINTEXT = "sk-target-run-abc123"


@pytest.fixture
def minted_credentials(monkeypatch):
    """Stand in for minting a test run's storage credentials; records each scope asked for."""
    requested_scopes = []

    def issue_for_test_run(*, python_code_result, storage_allowed_paths, org_id):
        requested_scopes.append({"storage_allowed_paths": storage_allowed_paths, "org_id": org_id})
        return StorageCredentials(access_key="test-access-key", secret_key="test-secret-key")

    monkeypatch.setattr(session_credential_service, "issue_for_test_run", issue_for_test_run)
    return requested_scopes


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
        self,
        acme_client,
        acme,
        acme_graph,
        attached_file,
        member_only,
        redis_client_mock,
        minted_credentials,
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
        assert task["storage_credentials"]["access_key"] == "test-access-key"
        assert minted_credentials == [
            {"storage_allowed_paths": task["storage_allowed_paths"], "org_id": acme.id}
        ]
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
        self, acme_client, acme_graph, redis_client_mock, minted_credentials
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


def _webhook_trigger_node(graph, *, use_storage):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return WebhookTriggerNode.objects.create(
        graph=graph, node_name="webhook_entry", python_code=python_code, use_storage=use_storage
    )


@pytest.mark.django_db
class TestWebhookTriggerNodeTarget:
    def test_storage_node_gets_attached_files_and_its_test_run_folder(
        self, acme_client, acme, acme_graph, attached_file, redis_client_mock, minted_credentials
    ):
        node = _webhook_trigger_node(acme_graph, use_storage=True)

        response = _run_target(acme_client, "webhook_trigger_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _published_tasks(redis_client_mock)
        assert task["use_storage"] is True
        assert task["storage_allowed_paths"] == [
            "docs/input.csv",
            f"test-runs/webhook_trigger_node-{node.id}/",
        ]
        assert task["storage_org_prefix"] == f"org_{acme.id}"
        assert task["storage_credentials"]["access_key"] == "test-access-key"
        assert minted_credentials == [
            {"storage_allowed_paths": task["storage_allowed_paths"], "org_id": acme.id}
        ]
        assert task["org_id"] == acme.id
        assert task["session_id"] is None
        assert PythonCodeResult.objects.get(
            execution_id=response.data["execution_id"]
        ).python_code_id == node.python_code_id

    def test_node_without_storage_sends_no_storage_fields(
        self, acme_client, acme, acme_graph, attached_file, redis_client_mock
    ):
        node = _webhook_trigger_node(acme_graph, use_storage=False)

        response = _run_target(acme_client, "webhook_trigger_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _published_tasks(redis_client_mock)
        assert task["use_storage"] is False
        assert task["storage_allowed_paths"] is None
        assert task["storage_org_prefix"] is None
        assert task["org_id"] == acme.id


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


def _flows_client(client_as, django_user_model, org, permissions, name):
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.FLOWS, permissions=int(permissions)
    )
    user = django_user_model.objects.create_user(
        email=f"{name}@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


def _plain_webhook_trigger_node(graph):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return WebhookTriggerNode.objects.create(
        graph=graph, node_name="webhook_entry", python_code=python_code
    )


@pytest.mark.django_db
class TestTriggerNodeTargetNeedsRun:
    """A trigger node's code runs need flows:run on top of flows:update."""

    def test_webhook_trigger_target_without_run_is_denied(
        self, client_as, django_user_model, acme, acme_graph, redis_client_mock
    ):
        client = _flows_client(
            client_as, django_user_model, acme, Permission.READ | Permission.UPDATE, "code-no-run"
        )
        node = _plain_webhook_trigger_node(acme_graph)

        response = _run_target(client, "webhook_trigger_node", node.id)

        assert response.status_code == 403, response.data
        assert response.data["code"] == "permission_denied"
        assert not redis_client_mock.publish.call_args_list
        assert not PythonCodeResult.objects.exists()

    def test_webhook_trigger_target_without_run_is_denied_before_the_lookup(
        self, client_as, django_user_model, acme, redis_client_mock
    ):
        client = _flows_client(
            client_as, django_user_model, acme, Permission.READ | Permission.UPDATE, "code-no-run-2"
        )

        response = _run_target(client, "webhook_trigger_node", 999_999)

        assert response.status_code == 403, response.data

    def test_webhook_trigger_target_with_run_runs(
        self, client_as, django_user_model, acme, acme_graph, redis_client_mock
    ):
        client = _flows_client(
            client_as,
            django_user_model,
            acme,
            Permission.READ | Permission.UPDATE | Permission.RUN,
            "code-with-run",
        )
        node = _plain_webhook_trigger_node(acme_graph)

        response = _run_target(client, "webhook_trigger_node", node.id)

        assert response.status_code == 200, response.data
        assert len(redis_client_mock.publish.call_args_list) == 1

    def test_webhook_trigger_target_with_run_but_without_update_is_denied(
        self, client_as, django_user_model, acme, acme_graph, redis_client_mock
    ):
        client = _flows_client(
            client_as, django_user_model, acme, Permission.READ | Permission.RUN, "code-run-only"
        )
        node = _plain_webhook_trigger_node(acme_graph)

        response = _run_target(client, "webhook_trigger_node", node.id)

        assert response.status_code == 403, response.data
        assert not redis_client_mock.publish.call_args_list

    def test_webhook_trigger_code_by_python_code_id_without_run_is_denied(
        self, client_as, django_user_model, acme, acme_graph, redis_client_mock
    ):
        client = _flows_client(
            client_as, django_user_model, acme, Permission.READ | Permission.UPDATE, "code-id-no-run"
        )
        node = _plain_webhook_trigger_node(acme_graph)

        response = client.post(
            URL, {"python_code_id": node.python_code_id, "variables": {}}, format="json"
        )

        assert response.status_code == 403, response.data
        assert response.data["code"] == "permission_denied"
        assert not redis_client_mock.publish.call_args_list
        assert not PythonCodeResult.objects.exists()

    def test_webhook_trigger_code_by_python_code_id_with_run_runs(
        self, client_as, django_user_model, acme, acme_graph, redis_client_mock
    ):
        client = _flows_client(
            client_as,
            django_user_model,
            acme,
            Permission.READ | Permission.UPDATE | Permission.RUN,
            "code-id-with-run",
        )
        node = _plain_webhook_trigger_node(acme_graph)

        response = client.post(
            URL, {"python_code_id": node.python_code_id, "variables": {}}, format="json"
        )

        assert response.status_code == 200, response.data
        assert len(redis_client_mock.publish.call_args_list) == 1

    def test_python_node_code_by_python_code_id_needs_no_run(
        self, client_as, django_user_model, acme, acme_graph, redis_client_mock
    ):
        client = _flows_client(
            client_as, django_user_model, acme, Permission.READ | Permission.UPDATE, "code-id-py"
        )
        node = _python_node(acme_graph, use_storage=False)

        response = client.post(
            URL, {"python_code_id": node.python_code_id, "variables": {}}, format="json"
        )

        assert response.status_code == 200, response.data

    def test_foreign_webhook_trigger_code_by_python_code_id_stays_not_found(
        self, client_as, django_user_model, acme, beta_graph, redis_client_mock
    ):
        client = _flows_client(
            client_as, django_user_model, acme, Permission.READ | Permission.UPDATE, "code-id-xorg"
        )
        node = _plain_webhook_trigger_node(beta_graph)

        response = client.post(
            URL, {"python_code_id": node.python_code_id, "variables": {}}, format="json"
        )

        assert response.status_code == 400, response.data
        assert "does not exist" in response.data["message"]

    def test_python_node_target_needs_no_run(
        self, client_as, django_user_model, acme, acme_graph, redis_client_mock
    ):
        client = _flows_client(
            client_as, django_user_model, acme, Permission.READ | Permission.UPDATE, "code-python"
        )
        node = _python_node(acme_graph, use_storage=False)

        response = _run_target(client, "python_node", node.id)

        assert response.status_code == 200, response.data
