"""POST /api/run-python-code/ with `target`: test mode runs a node's code slot
with the payload a real run would send — storage scope, org_id and secrets —
while the legacy `python_code_id` path keeps running the bare code.

Real view, service, converter and secret resolver. The sandbox is replaced by a
recording HTTP intake (`sandbox_intake`), so the submitted body is what is
asserted, and so is minting storage credentials (`minted_credentials`), which
would otherwise need the organization's storage admin account in the object
store."""

import pytest
from django.utils import timezone
from src.shared.models.storage_scope import StorageCredentials
from storage_credentials.services.session_credential_service import session_credential_service

from rbac.models import OrganizationUser
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


def _submitted_tasks(sandbox_intake):
    return sandbox_intake.bodies


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
        sandbox_intake,
        minted_credentials,
    ):
        node = _python_node(acme_graph, use_storage=True)

        response = _run_target(acme_client, "python_node", node.id, {"x": 1})

        assert response.status_code == 200, response.data
        [task] = _submitted_tasks(sandbox_intake)
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
        self, acme_client, acme_graph, sandbox_intake, minted_credentials
    ):
        node = _python_node(acme_graph, use_storage=True)

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _submitted_tasks(sandbox_intake)
        assert task["storage_allowed_paths"] == [f"test-runs/python_node-{node.id}/"]

    def test_node_without_storage_sends_no_storage_fields(
        self, acme_client, acme, acme_graph, attached_file, sandbox_intake
    ):
        node = _python_node(acme_graph, use_storage=False)

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _submitted_tasks(sandbox_intake)
        assert task["use_storage"] is False
        assert task["storage_allowed_paths"] == []
        assert task["storage_org_prefix"] is None
        assert task["global_kwargs"]["org_id"] == acme.id

    def test_declared_secret_reaches_the_sandbox_message(
        self, acme_client, acme, acme_graph, sandbox_intake
    ):
        secret = secret_service.create(text=PLAINTEXT, org=acme, name="TARGET_KEY")
        node = _python_node(
            acme_graph, use_storage=False, code='def main(): return get_secret("TARGET_KEY")'
        )
        node.python_code.secrets.set([secret])

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _submitted_tasks(sandbox_intake)
        assert task["secrets"] == {"TARGET_KEY": PLAINTEXT}

    def test_undeclared_secret_is_rejected_before_anything_is_written(
        self, acme_client, acme, acme_graph, sandbox_intake
    ):
        secret_service.create(text=PLAINTEXT, org=acme, name="TARGET_KEY")
        node = _python_node(
            acme_graph, use_storage=True, code='def main(): return get_secret("TARGET_KEY")'
        )

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 400
        assert "TARGET_KEY" in str(response.data)
        assert sandbox_intake.bodies == []
        assert not PythonCodeResult.objects.exists()


def _webhook_trigger_node(graph, *, use_storage):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return WebhookTriggerNode.objects.create(
        graph=graph, node_name="webhook_entry", python_code=python_code, use_storage=use_storage
    )


@pytest.mark.django_db
class TestWebhookTriggerNodeTarget:
    def test_storage_node_gets_attached_files_and_its_test_run_folder(
        self, acme_client, acme, acme_graph, attached_file, sandbox_intake, minted_credentials
    ):
        node = _webhook_trigger_node(acme_graph, use_storage=True)

        response = _run_target(acme_client, "webhook_trigger_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _submitted_tasks(sandbox_intake)
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
        assert task["global_kwargs"]["org_id"] == acme.id
        assert task["session_id"] is None
        assert PythonCodeResult.objects.get(
            execution_id=response.data["execution_id"]
        ).python_code_id == node.python_code_id

    def test_node_without_storage_sends_no_storage_fields(
        self, acme_client, acme, acme_graph, attached_file, sandbox_intake
    ):
        node = _webhook_trigger_node(acme_graph, use_storage=False)

        response = _run_target(acme_client, "webhook_trigger_node", node.id)

        assert response.status_code == 200, response.data
        [task] = _submitted_tasks(sandbox_intake)
        assert task["use_storage"] is False
        assert task["storage_allowed_paths"] == []
        assert task["storage_org_prefix"] is None
        assert task["global_kwargs"]["org_id"] == acme.id


@pytest.mark.django_db
class TestSandboxRefusesTheSubmission:
    """A refused submission produces no result on the result channel, so the
    PENDING row would never be completed by anything."""

    def test_the_result_is_marked_error_instead_of_staying_pending(
        self, acme_client, acme_graph, sandbox_intake
    ):
        sandbox_intake.status_code = 503
        node = _python_node(acme_graph, use_storage=False)

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 200, response.data
        result = PythonCodeResult.objects.get(execution_id=response.data["execution_id"])
        assert result.status == PythonCodeResult.Status.ERROR
        assert result.stderr == "Could not reach the code sandbox for this run."
        assert result.finished_at is not None


@pytest.mark.django_db
class TestTargetLookupIsOrgScoped:
    def test_node_of_another_org_is_not_found(self, acme_client, beta_graph, sandbox_intake):
        node = _python_node(beta_graph, use_storage=True)

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 400
        assert response.data["message"] == (
            f'target: Invalid pk "{node.id}" - object does not exist.'
        )
        assert sandbox_intake.bodies == []
        assert not PythonCodeResult.objects.exists()

    def test_webhook_trigger_node_of_another_org_is_not_found(
        self, acme_client, beta_graph, sandbox_intake
    ):
        python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
        node = WebhookTriggerNode.objects.create(
            graph=beta_graph, node_name="webhook_entry", python_code=python_code
        )

        response = _run_target(acme_client, "webhook_trigger_node", node.id)

        assert response.status_code == 400
        assert "does not exist" in response.data["message"]
        assert sandbox_intake.bodies == []

    def test_soft_deleted_node_is_not_found(self, acme_client, acme_graph, sandbox_intake):
        node = _python_node(acme_graph, use_storage=True)
        PythonNode.all_objects.filter(pk=node.pk).update(
            active=False, soft_deleted_at=timezone.now()
        )

        response = _run_target(acme_client, "python_node", node.id)

        assert response.status_code == 400
        assert "does not exist" in response.data["message"]
        assert sandbox_intake.bodies == []

    def test_missing_node_is_not_found(self, acme_client, sandbox_intake):
        response = _run_target(acme_client, "python_node", 999_999)

        assert response.status_code == 400
        assert "does not exist" in response.data["message"]

    def test_caller_without_flows_update_is_denied(
        self, client_as, django_user_model, acme, acme_graph, role_viewer, sandbox_intake
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
        assert sandbox_intake.bodies == []


@pytest.mark.django_db
class TestRequestShape:
    def test_both_target_and_python_code_id_is_rejected(
        self, acme_client, acme_graph, sandbox_intake
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
        assert sandbox_intake.bodies == []

    def test_neither_target_nor_python_code_id_is_rejected(self, acme_client, sandbox_intake):
        response = acme_client.post(URL, {"variables": {}}, format="json")

        assert response.status_code == 400
        assert "exactly one" in response.data["message"]

    def test_unknown_target_type_is_rejected(self, acme_client, acme_graph, sandbox_intake):
        node = _python_node(acme_graph, use_storage=False)

        response = _run_target(acme_client, "agent_node", node.id)

        assert response.status_code == 400
        assert "agent_node" in response.data["message"]
        assert sandbox_intake.bodies == []

    def test_legacy_python_code_id_runs_bare_code_without_storage(
        self, acme_client, acme_graph, attached_file, sandbox_intake
    ):
        node = _python_node(acme_graph, use_storage=True)

        response = acme_client.post(
            URL, {"python_code_id": node.python_code_id, "variables": {"x": 1}}, format="json"
        )

        assert response.status_code == 200, response.data
        [task] = _submitted_tasks(sandbox_intake)
        # The bare run has no venv of its own: null means the sandbox's default.
        assert task["venv_id"] is None
        assert task["use_storage"] is False
        assert task["storage_allowed_paths"] == []
        assert task["storage_credentials"] is None
        assert "org_id" not in task["global_kwargs"]
        assert task["func_kwargs"] == {"x": 1}
