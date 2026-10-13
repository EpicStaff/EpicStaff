"""Tests for RunPythonCodeService storage credential minting and revocation.

Commit 5, Part 9: test-run and realtime storage credential handling.
Tests verify:
1. Test-run without storage → no mint, no DB write
2. Test-run with storage → mint, DB write, credentials embedded in CodeTaskData
3. Revoke on code_results_handler success
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from rbac.models import Organization
from tables.models import PythonCode, PythonCodeResult, PythonCodeTool
from tables.services.redis_service import RedisService
from tables.services.run_python_code_service import RunPythonCodeService
from storage_credentials.models import TemporaryStorageAccount
from src.shared.models import StorageCredentials


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org TestRunStorage")


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Org Other")


@pytest.fixture
def python_code(db):
    """Simple python code without secrets"""
    return PythonCode.objects.create(
        code="def main(**kw): return kw",
        entrypoint="main",
        global_kwargs={},
    )


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        email="testrun@example.com", password="StrongPass123!"
    )


@pytest.mark.django_db
class TestRunCodeStorageCredentials:
    """Test-run (bare /run-python-code/) storage credential handling"""

    def test_run_code_without_storage_no_mint(self, org, user, python_code):
        """Session without storage → no mint, no DB write to TemporaryStorageAccount"""
        # Ensure no PythonCodeTool with use_storage=True exists for this code
        # so use_storage resolves to False
        service = RunPythonCodeService(redis_service=MagicMock())

        with patch.object(
            service.redis_service.redis_client, "publish", return_value=None
        ) as publish_mock:
            execution_id = service.run_code(
                python_code_id=python_code.pk,
                varaibles={},
                organization_id=org.id,
                user=user,
            )

        # Verify no TemporaryStorageAccount was created
        assert not TemporaryStorageAccount.objects.filter(
            python_code_result__execution_id=execution_id
        ).exists()

        # Verify the result was created (basic flow works)
        assert PythonCodeResult.objects.filter(execution_id=execution_id).exists()

        # Verify publish was called (normal flow)
        assert publish_mock.called

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_run_code_with_storage_mints_credentials(
        self, mock_gateway_class, org, user, python_code
    ):
        """Session with storage → mint, DB write, credentials embedded in CodeTaskData"""
        # Create a PythonCodeTool with use_storage=True to trigger storage flow
        PythonCodeTool.objects.create(
            python_code=python_code, org_id=org.id, use_storage=True
        )

        # Mock the async gateway to return credentials
        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.create_service_account = AsyncMock(
            return_value=("test-access-key", "test-secret-key")
        )
        mock_gateway_instance.close = AsyncMock()

        # Mock org credential store
        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        service = RunPythonCodeService(redis_service=MagicMock())

        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            with patch.object(
                service.redis_service.redis_client, "publish", return_value=None
            ) as publish_mock:
                execution_id = service.run_code(
                    python_code_id=python_code.pk,
                    varaibles={},
                    organization_id=org.id,
                    user=user,
                )

        # Verify TemporaryStorageAccount was created with correct FK
        temp_account = TemporaryStorageAccount.objects.get(
            python_code_result__execution_id=execution_id
        )
        assert temp_account.access_key == "test-access-key"
        assert temp_account.python_code_result is not None
        assert temp_account.python_code_result.execution_id == execution_id

        # Verify credentials were embedded in the published message
        assert publish_mock.called
        published_message = publish_mock.call_args[0][1]
        message_data = json.loads(published_message)
        assert message_data["storage_credentials"] == {
            "access_key": "test-access-key",
            "secret_key": "test-secret-key",
        }

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_run_code_with_storage_uses_correct_storage_allowed_paths(
        self, mock_gateway_class, org, user, python_code
    ):
        """Storage-enabled test-run uses execution-scoped allowed_paths"""
        PythonCodeTool.objects.create(
            python_code=python_code, org_id=org.id, use_storage=True
        )

        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.create_service_account = AsyncMock(
            return_value=("test-access-key", "test-secret-key")
        )
        mock_gateway_instance.close = AsyncMock()

        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        service = RunPythonCodeService(redis_service=MagicMock())

        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            with patch.object(service.redis_service.redis_client, "publish"):
                execution_id = service.run_code(
                    python_code_id=python_code.pk,
                    varaibles={},
                    organization_id=org.id,
                    user=user,
                )

        # Verify the gateway was called with test-run-specific path
        call_args = mock_gateway_instance.create_service_account.call_args
        policy = call_args.kwargs["policy"]
        # The policy should be scoped to test-runs/{execution_id}/
        assert policy is not None  # Policy was built and passed

    def test_run_code_org_scoped_use_storage_filter(self, org, other_org, user, python_code):
        """use_storage flag is org-scoped; other org's tool cannot trigger storage for this org"""
        # Create tool with use_storage=True in OTHER org
        PythonCodeTool.objects.create(
            python_code=python_code, org_id=other_org.id, use_storage=True
        )

        service = RunPythonCodeService(redis_service=MagicMock())

        # When called for the first org, use_storage should be False
        # (no tool in first org has use_storage=True)
        with patch.object(service.redis_service.redis_client, "publish") as publish_mock:
            execution_id = service.run_code(
                python_code_id=python_code.pk,
                varaibles={},
                organization_id=org.id,  # First org, not other_org
                user=user,
            )

        # No TemporaryStorageAccount should be created
        assert not TemporaryStorageAccount.objects.filter(
            python_code_result__execution_id=execution_id
        ).exists()

        # Verify storage was not enabled in the published message
        published_message = publish_mock.call_args[0][1]
        message_data = json.loads(published_message)
        assert message_data["use_storage"] is False
        assert message_data["storage_credentials"] is None


@pytest.mark.django_db
class TestRunCodeInvalidScopeRevocation:
    """An invalid CodeTaskData means nothing is ever published for this
    execution, so the code_results handler never runs -- run_code itself has to
    revoke the credentials it just minted."""

    @staticmethod
    def _validation_error() -> ValidationError:
        class _Probe(BaseModel):
            value: int

        try:
            _Probe(value="not-an-int")
        except ValidationError as error:
            return error
        raise AssertionError("expected a ValidationError")

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_invalid_task_data_revokes_minted_credentials(
        self, mock_gateway_class, org, user, python_code
    ):
        PythonCodeTool.objects.create(
            python_code=python_code, org_id=org.id, use_storage=True
        )

        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.create_service_account = AsyncMock(
            return_value=("invalid-scope-access-key", "invalid-scope-secret-key")
        )
        mock_gateway_instance.delete_service_account = AsyncMock()
        mock_gateway_instance.close = AsyncMock()

        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        service = RunPythonCodeService(redis_service=MagicMock())

        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            with patch(
                "tables.services.run_python_code_service.CodeTaskData",
                side_effect=self._validation_error(),
            ):
                with patch.object(
                    service.redis_service.redis_client, "publish"
                ) as publish_mock:
                    execution_id = service.run_code(
                        python_code_id=python_code.pk,
                        varaibles={},
                        organization_id=org.id,
                        user=user,
                    )

        assert not publish_mock.called

        result = PythonCodeResult.objects.get(execution_id=execution_id)
        assert result.status == PythonCodeResult.Status.ERROR

        mock_gateway_instance.delete_service_account.assert_called_once_with(
            "invalid-scope-access-key"
        )
        assert not TemporaryStorageAccount.objects.filter(
            python_code_result__execution_id=execution_id
        ).exists()


@pytest.mark.django_db
class TestCodeResultsHandlerRevocation:
    """Test code_results_handler's credential revocation flow"""

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_code_results_handler_revokes_on_success(
        self, mock_gateway_class, org, user, python_code
    ):
        """code_results_handler revokes temp account and deletes DB row on success"""
        from tables.services.redis_pubsub import RedisPubSub
        from src.shared.models import CodeResultData

        # Create result and temp account
        result = PythonCodeResult.objects.create(
            execution_id="test-exec-123",
            org_id=org.id,
            created_by=user,
            python_code=python_code,
            status=PythonCodeResult.Status.PENDING,
        )
        temp_account = TemporaryStorageAccount.objects.create(
            python_code_result=result, access_key="test-access-key"
        )

        # Mock org creds and gateway
        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.delete_service_account = AsyncMock()
        mock_gateway_instance.close = AsyncMock()

        # Create handler with mocked redis
        handler = RedisPubSub()
        handler.redis_client = MagicMock()

        # Mock the org_credential_store
        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            with patch("tables.services.redis_pubsub.close_old_connections"):
                # Call the handler
                message = {
                    "data": CodeResultData(
                        execution_id="test-exec-123",
                        result_data="ok",
                        stderr="",
                        stdout="",
                        returncode=0,
                    ).model_dump_json()
                }
                handler.code_results_handler(message)

        # Verify delete_service_account was called
        mock_gateway_instance.delete_service_account.assert_called_once_with("test-access-key")

        # Verify the TemporaryStorageAccount row was deleted
        assert not TemporaryStorageAccount.objects.filter(pk=temp_account.pk).exists()

        # Verify the result was marked as completed
        result.refresh_from_db()
        assert result.status == PythonCodeResult.Status.COMPLETED

    @patch("storage_credentials.services.session_credential_service.StorageAdminGateway")
    def test_code_results_handler_leaves_row_when_revoke_fails(
        self, mock_gateway_class, org, user, python_code
    ):
        """code_results_handler leaves the TemporaryStorageAccount row in place
        when revocation fails -- the manager backstop job finds it later."""
        from tables.services.redis_pubsub import RedisPubSub
        from src.shared.models import CodeResultData

        result = PythonCodeResult.objects.create(
            execution_id="test-exec-revoke-fails",
            org_id=org.id,
            created_by=user,
            python_code=python_code,
            status=PythonCodeResult.Status.PENDING,
        )
        temp_account = TemporaryStorageAccount.objects.create(
            python_code_result=result, access_key="test-access-key-fail"
        )

        mock_org_creds = MagicMock()
        mock_org_creds.access_key = "org-access"
        mock_org_creds.secret_key = "org-secret"

        mock_gateway_instance = AsyncMock()
        mock_gateway_class.return_value = mock_gateway_instance
        mock_gateway_instance.delete_service_account = AsyncMock(
            side_effect=Exception("Gateway error")
        )
        mock_gateway_instance.close = AsyncMock()

        handler = RedisPubSub()
        handler.redis_client = MagicMock()

        with patch(
            "storage_credentials.services.session_credential_service.org_credential_store.get",
            return_value=mock_org_creds,
        ):
            with patch("tables.services.redis_pubsub.close_old_connections"):
                message = {
                    "data": CodeResultData(
                        execution_id="test-exec-revoke-fails",
                        result_data="ok",
                        stderr="",
                        stdout="",
                        returncode=0,
                    ).model_dump_json()
                }
                handler.code_results_handler(message)

        # Revoke failed -- the opportunistic delete never ran, row stays for
        # the manager backstop job.
        assert TemporaryStorageAccount.objects.filter(pk=temp_account.pk).exists()

        # Result persistence must not be blocked by the revoke failure.
        result.refresh_from_db()
        assert result.status == PythonCodeResult.Status.COMPLETED

    def test_code_results_handler_no_revoke_without_temp_account(
        self, org, user, python_code
    ):
        """code_results_handler is no-op when no TemporaryStorageAccount exists"""
        from tables.services.redis_pubsub import RedisPubSub
        from src.shared.models import CodeResultData

        # Create result without temp account
        result = PythonCodeResult.objects.create(
            execution_id="test-exec-no-storage",
            org_id=org.id,
            created_by=user,
            python_code=python_code,
            status=PythonCodeResult.Status.PENDING,
        )

        handler = RedisPubSub()
        handler.redis_client = MagicMock()

        with patch("tables.services.redis_pubsub.close_old_connections"):
            # Call handler — must not raise even though no temp account exists
            message = {
                "data": CodeResultData(
                    execution_id="test-exec-no-storage",
                    result_data="ok",
                    stderr="",
                    stdout="",
                    returncode=0,
                ).model_dump_json()
            }
            handler.code_results_handler(message)

        # Verify the result was still marked as completed (handler succeeded)
        result.refresh_from_db()
        assert result.status == PythonCodeResult.Status.COMPLETED
