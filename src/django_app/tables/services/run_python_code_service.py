import uuid
from datetime import UTC, datetime
from typing import Any

from django.utils import timezone
from foundation.transport.http import ClientError
from loguru import logger
from pydantic import ValidationError
from rbac.authorship import resolve_author
from src.shared.models import CodeResultData, CodeTaskData
from src.shared.models.storage_scope import StorageCredentials
from storage_credentials.exceptions import StorageCredentialError
from storage_credentials.resource_names import org_storage_prefix
from storage_credentials.services.session_credential_service import session_credential_service
from tables.clients import SandboxExecutionClient
from tables.exceptions import CodeRunTargetNotFoundError
from tables.models import PythonCode, PythonCodeResult, PythonCodeTool
from tables.services.code_run_targets import CODE_RUN_TARGETS, storage_path_for_test_run
from tables.services.secrets import (
    UndeclaredSecretError,
    parse_secret_names,
    secret_resolver,
)
from tables.services.secrets.declaration_validator import (
    binned_secret_names,
    describe_unreadable_secrets,
)
from utils.singleton_meta import SingletonMeta

MAX_STORED_RESULTS = 200


class RunPythonCodeService(metaclass=SingletonMeta):
    _INVALID_REQUEST_LOG = "Invalid code execution request (execution_id={})"
    _INVALID_REQUEST_STDERR = "Invalid code execution request."
    _CREDENTIAL_ISSUE_LOG = (
        "Failed to issue storage credentials for code execution (execution_id={})"
    )
    _CREDENTIAL_ISSUE_STDERR = "Could not grant file storage access for this run."
    _SUBMIT_FAILED_LOG = "Failed to submit code execution to the sandbox (execution_id={}, {})"
    _SUBMIT_FAILED_STDERR = "Could not reach the code sandbox for this run."

    def run_code(
        self,
        python_code_id: int,
        varaibles: dict,
        organization_id: int,
        user,
        additional_global_kwargs: dict[str, Any] | None = None,
    ) -> str:
        """
        Submits Python code to the sandbox for execution.

        Args:
            python_code_id (int): The ID of the Python code in the database.
            variables (dict): A dictionary containing key-value pairs to be used as input for the Python code.
            additional_global_kwargs (dict[str, Any], optional): Additional global keyword arguments to be passed to the Python code. Defaults to None.
        Returns:
            str: The execution ID of the Python code.
        """
        additional_global_kwargs = additional_global_kwargs or {}

        python_code: PythonCode = PythonCode.objects.get(id=python_code_id)

        # Resolve before anything is written or published: this path never goes
        # through the session payload, so it resolves for itself, and a failure
        # must leave no PENDING result row and publish nothing. organization_id is
        # what scopes the lookup; the declaration is the M2M, so Test mode and a
        # real run agree about what this code may read.
        declared = set(python_code.secrets.values_list("name", flat=True))
        self._assert_secrets_declared(
            python_code_id=python_code_id,
            code=python_code.code,
            declared=declared,
            binned=binned_secret_names(python_code),
        )
        secrets = secret_resolver.resolve_named(
            names=sorted(declared),
            org_id=organization_id,
            context=f"PythonCode(id={python_code_id}).secrets",
        )

        execution_id = self.gen_execution_id()

        # A bare "Test run" has no graph/session context to resolve
        # storage_allowed_paths from (unlike converter_service's node/tool
        # conversions). use_storage is derived from whether this PythonCode
        # is used by at least one storage-enabled PythonCodeTool belonging
        # to *this* organization -- an org-scoped filter, since a different
        # tenant's tool marked use_storage=True must never be able to flip
        # storage on for this org's Test run.
        #
        # CredentialScopeValidator fails closed on an empty/missing
        # storage_allowed_paths (no more "whole org prefix" default), so an
        # explicit, narrow path scoped to this one execution is passed here
        # rather than relying on any default.
        use_storage = PythonCodeTool.objects.filter(
            python_code=python_code, use_storage=True, org_id=organization_id
        ).exists()
        storage_org_prefix = org_storage_prefix(organization_id) if use_storage else None
        storage_allowed_paths = [f"test-runs/{execution_id}/"] if use_storage else None

        python_code_result = self._create_pending_result(
            execution_id=execution_id,
            organization_id=organization_id,
            user=user,
            python_code=python_code,
        )

        storage_credentials, ok = self._mint_storage_credentials(
            execution_id=execution_id,
            use_storage=use_storage,
            python_code_result=python_code_result,
            storage_allowed_paths=storage_allowed_paths,
            org_id=organization_id,
        )
        if not ok:
            return execution_id

        try:
            code_task_data = CodeTaskData(
                # The code's own venv: a test run must execute where the real run
                # would, not on the sandbox's default venv.
                venv_id=python_code.venv_id,
                code=python_code.code,
                entrypoint=python_code.entrypoint,
                func_kwargs=varaibles,
                execution_id=execution_id,
                global_kwargs={**python_code.global_kwargs, **additional_global_kwargs},
                use_storage=use_storage,
                storage_org_prefix=storage_org_prefix,
                storage_allowed_paths=storage_allowed_paths,
                org_id=organization_id if use_storage else None,
                secrets=secrets,
                storage_credentials=storage_credentials,
            )
        except ValidationError:
            return self._fail_execution(
                execution_id=execution_id,
                use_storage=use_storage,
                log_message=self._INVALID_REQUEST_LOG,
                stderr=self._INVALID_REQUEST_STDERR,
            )

        return self._submit(
            code_task_data=code_task_data, execution_id=execution_id, use_storage=use_storage
        )

    def run_target(
        self,
        *,
        target_type: str,
        target_id: int,
        variables: dict,
        organization_id: int,
        user,
    ) -> str:
        """Test-run one code slot with the payload a real run of that slot would send.

        The payload comes from the slot's real-run converter method, with the
        test run's own folder (`test-runs/<type>-<id>/`) in place of the session
        folder. Secrets are resolved on a copy, the way `RedisService` resolves a
        session payload, and `org_id` is put into the code's globals the way crew
        does. Writes a PENDING `PythonCodeResult` and submits the task to the
        sandbox.

        Args:
            target_type: A key of `CODE_RUN_TARGETS`.

        Returns:
            The execution id the result is stored under.

        Raises:
            CodeRunTargetNotFoundError: No live target with this id in
                `organization_id`, or its code slot is empty.
            UndeclaredSecretError: The code reads a secret it did not declare.
                Nothing is written or submitted.
        """
        code_run_target = CODE_RUN_TARGETS[target_type]
        owner = code_run_target.find_in_org(target_id=target_id, org_id=organization_id)
        if owner is None:
            raise CodeRunTargetNotFoundError(target_id)
        python_code = code_run_target.python_code_of(owner)
        python_code_data = code_run_target.build_payload(
            owner, storage_path_for_test_run(target_type, target_id)
        )

        self._assert_secrets_declared(
            python_code_id=python_code.pk,
            code=python_code_data.code,
            declared=set(python_code_data.secret_names),
            binned=binned_secret_names(python_code),
        )
        resolved = secret_resolver.resolve_payload(payload=python_code_data, org_id=organization_id)

        global_kwargs = dict(resolved.global_kwargs or {})
        if resolved.org_id is not None:
            global_kwargs["org_id"] = resolved.org_id

        execution_id = self.gen_execution_id()

        python_code_result = self._create_pending_result(
            execution_id=execution_id,
            organization_id=organization_id,
            user=user,
            python_code=python_code,
        )

        storage_credentials, ok = self._mint_storage_credentials(
            execution_id=execution_id,
            use_storage=resolved.use_storage,
            python_code_result=python_code_result,
            storage_allowed_paths=resolved.storage_allowed_paths,
            org_id=resolved.org_id,
        )
        if not ok:
            return execution_id

        try:
            code_task_data = CodeTaskData(
                # The slot's real-run venv: a test run of a slot must execute where
                # the real run would, not on the sandbox's default venv.
                venv_id=resolved.venv_id,
                code=resolved.code,
                entrypoint=resolved.entrypoint,
                func_kwargs=variables,
                execution_id=execution_id,
                global_kwargs=global_kwargs,
                use_storage=resolved.use_storage,
                storage_allowed_paths=resolved.storage_allowed_paths,
                storage_org_prefix=resolved.storage_org_prefix,
                session_id=resolved.session_id,
                org_id=resolved.org_id,
                secrets=resolved.secrets,
                storage_credentials=storage_credentials,
            )
        except ValidationError:
            return self._fail_execution(
                execution_id=execution_id,
                use_storage=resolved.use_storage,
                log_message=self._INVALID_REQUEST_LOG,
                stderr=self._INVALID_REQUEST_STDERR,
            )

        return self._submit(
            code_task_data=code_task_data,
            execution_id=execution_id,
            use_storage=resolved.use_storage,
        )

    def _mint_storage_credentials(
        self,
        *,
        execution_id: str,
        use_storage: bool,
        python_code_result: PythonCodeResult,
        storage_allowed_paths: list[str] | None,
        org_id: int,
    ) -> tuple[StorageCredentials | None, bool]:
        """Mint storage credentials if needed. Returns (credentials, ok);
        ok=False means the execution already failed (ERROR, best-effort revoke)
        and the caller should return `execution_id` without building anything.
        """
        try:
            return (
                self._issue_storage_credentials_if_needed(
                    use_storage=use_storage,
                    python_code_result=python_code_result,
                    storage_allowed_paths=storage_allowed_paths,
                    org_id=org_id,
                ),
                True,
            )
        except StorageCredentialError:
            self._fail_execution(
                execution_id=execution_id,
                use_storage=use_storage,
                log_message=self._CREDENTIAL_ISSUE_LOG,
                stderr=self._CREDENTIAL_ISSUE_STDERR,
            )
            return None, False

    def _fail_execution(
        self,
        *,
        execution_id: str,
        use_storage: bool,
        log_message: str,
        stderr: str,
        log_args: tuple = (),
    ) -> str:
        logger.error(log_message, execution_id, *log_args)
        PythonCodeResult.objects.filter(execution_id=execution_id).update(
            status=PythonCodeResult.Status.ERROR,
            stderr=stderr,
            finished_at=timezone.now(),
        )
        self._revoke_storage_credentials_safely(use_storage=use_storage, execution_id=execution_id)
        return execution_id

    @staticmethod
    def _assert_secrets_declared(
        *, python_code_id: int, code: str, declared: set[str], binned: set[str]
    ) -> None:
        """Raise if `code` reads a secret outside `declared` (binned ones are named as such)."""
        undeclared = parse_secret_names(code=code) - declared
        if undeclared:
            raise UndeclaredSecretError(
                describe_unreadable_secrets(
                    subject=f"PythonCode(id={python_code_id})",
                    owner="it",
                    undeclared=undeclared,
                    binned=binned,
                    declared=declared,
                )
            )

    def _create_pending_result(
        self, *, execution_id: str, organization_id: int, user, python_code: PythonCode
    ) -> PythonCodeResult:
        python_code_result = PythonCodeResult.objects.create(
            execution_id=execution_id,
            org_id=organization_id,
            created_by=resolve_author(user),
            python_code=python_code,
        )
        self._evict_oldest_results(organization_id)
        return python_code_result

    def _issue_storage_credentials_if_needed(
        self,
        *,
        use_storage: bool,
        python_code_result: PythonCodeResult,
        storage_allowed_paths: list[str] | None,
        org_id: int,
    ):
        if not use_storage:
            return None
        return session_credential_service.issue_for_test_run(
            python_code_result=python_code_result,
            storage_allowed_paths=storage_allowed_paths,
            org_id=org_id,
        )

    def _revoke_storage_credentials_safely(self, *, use_storage: bool, execution_id: str) -> None:
        # Best-effort by contract: the underlying call swallows its own errors
        # and is a no-op when nothing was minted.
        if use_storage:
            session_credential_service.revoke_for_test_run(execution_id=execution_id)

    def _submit(self, *, code_task_data: CodeTaskData, execution_id: str, use_storage: bool) -> str:
        """Hand the task to the sandbox, failing the execution if it does not take it.

        A rejected or undelivered submission produces no result on the result
        channel, so the PENDING row would stay PENDING for good -- it is marked
        ERROR here instead, and any minted credentials are revoked.

        Returns:
            The execution id, whether the submit succeeded or failed.
        """
        try:
            with SandboxExecutionClient() as client:
                client.submit(code_task_data)
        except ClientError as error:
            # The class name, never the error: it holds the sandbox response and,
            # through it, the submitted body with resolved secret plaintext.
            return self._fail_execution(
                execution_id=execution_id,
                use_storage=use_storage,
                log_message=self._SUBMIT_FAILED_LOG,
                stderr=self._SUBMIT_FAILED_STDERR,
                log_args=(type(error).__name__,),
            )
        return execution_id

    def gen_execution_id(self):
        now = datetime.now(UTC)
        short_uuid = str(uuid.uuid4())[:4]
        formatted_time = now.strftime(f"%d-%m-%Y_%H-%M-%S-{now.microsecond // 1000:03d}")
        return f"{formatted_time}@{short_uuid}"

    def save_execution_result(self, result: CodeResultData) -> bool:
        updated = PythonCodeResult.objects.filter(
            execution_id=result.execution_id,
            status=PythonCodeResult.Status.PENDING,
        ).update(
            status=(
                PythonCodeResult.Status.COMPLETED
                if result.returncode == 0
                else PythonCodeResult.Status.ERROR
            ),
            result_data=result.result_data,
            stderr=result.stderr,
            stdout=result.stdout,
            returncode=result.returncode,
            finished_at=timezone.now(),
        )
        return bool(updated)

    def _evict_oldest_results(self, organization_id: int) -> None:
        stale_ids = (
            PythonCodeResult.objects.filter(org_id=organization_id)
            .order_by("-created_at", "-pk")
            .values_list("pk", flat=True)[MAX_STORED_RESULTS:]
        )
        if stale_ids:
            PythonCodeResult.objects.filter(pk__in=list(stale_ids)).delete()
