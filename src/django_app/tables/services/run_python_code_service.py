import uuid
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.utils import timezone
from loguru import logger
from pydantic import ValidationError
from src.shared.models import CodeResultData, CodeTaskData
from storage_credentials.resource_names import org_storage_prefix
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import PythonCode, PythonCodeResult, PythonCodeTool
from tables.services.redis_service import RedisService
from tables.services.secrets import (
    UndeclaredSecretError,
    parse_secret_names,
    secret_resolver,
)
from utils.singleton_meta import SingletonMeta

MAX_STORED_RESULTS = 200


class RunPythonCodeService(metaclass=SingletonMeta):
    def __init__(self, redis_service: RedisService):
        self.redis_service = redis_service
        self.code_exec_task_channel: str = settings.CODE_EXEC_CHANNEL

    def run_code(
        self,
        python_code_id: int,
        varaibles: dict,
        organization_id: int,
        user,
        additional_global_kwargs: dict[str, Any] | None = None,
    ) -> str:
        """
        Sends a Redis request to execute Python code.

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
        parsed = parse_secret_names(code=python_code.code)
        undeclared = parsed - declared
        if undeclared:
            raise UndeclaredSecretError(
                f"PythonCode(id={python_code_id}) calls "
                + ", ".join(f'get_secret("{name}")' for name in sorted(undeclared))
                + ", which "
                + ("are" if len(undeclared) > 1 else "is")
                + " not declared for it. Declared: "
                + (", ".join(sorted(declared)) or "none")
                + "."
            )

        secrets = secret_resolver.resolve_named(
            names=sorted(declared),
            org_id=organization_id,
            context=f"PythonCode(id={python_code_id}).secrets",
        )

        execution_id = self.gen_execution_id()
        python_code_result = PythonCodeResult.objects.create(
            execution_id=execution_id,
            org_id=organization_id,
            created_by=user,
            python_code=python_code,
        )
        self._evict_oldest_results(organization_id)

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

        storage_credentials = None
        if use_storage:
            storage_credentials = session_credential_service.issue_for_test_run(
                python_code_result=python_code_result,
                storage_allowed_paths=storage_allowed_paths,
                org_id=organization_id,
            )

        try:
            code_task_data = CodeTaskData(
                venv_name=f"venv_{python_code_id}",
                libraries=python_code.get_libraries_list(),
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
            # Never log the error itself: pydantic's ValidationError repr embeds
            # the full constructor input, including `secrets` plaintext.
            logger.error(
                "Invalid storage scope for code execution (execution_id={})",
                execution_id,
            )
            PythonCodeResult.objects.filter(execution_id=execution_id).update(
                status=PythonCodeResult.Status.ERROR,
                stderr="Invalid storage scope for code execution.",
                finished_at=timezone.now(),
            )
            # If credentials were minted above, nothing will ever be published
            # for them, so the sandbox result path that normally revokes them
            # never runs. Best-effort by contract: the helper swallows its own
            # errors (and is a no-op when nothing was minted), so the ERROR
            # result is still returned either way.
            session_credential_service.revoke_for_test_run(execution_id=execution_id)
            return execution_id

        channel = self.code_exec_task_channel
        self.redis_service.redis_client.publish(channel, code_task_data.model_dump_json())
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
