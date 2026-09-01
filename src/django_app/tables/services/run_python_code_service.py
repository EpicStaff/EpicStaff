import os
from typing import Any
import uuid
from django.utils import timezone
from src.shared.models import CodeResultData, CodeTaskData
from src.shared.storage_credentials import publish_credential_scope
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
        self.code_exec_task_channel: str = os.environ.get(
            "CODE_EXEC_TASK_CHANNEL", "code_exec_tasks"
        )

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

        execution_id = str(uuid.uuid4())
        PythonCodeResult.objects.create(
            execution_id=execution_id,
            org_id=organization_id,
            created_by=user,
            python_code=python_code,
        )
        self._evict_oldest_results(organization_id)

        # A bare "Test run" has no graph/session context to resolve
        # storage_allowed_paths from (unlike converter_service's node/tool
        # conversions). use_storage is derived from whether this PythonCode
        # is used by at least one storage-enabled PythonCodeTool; when so,
        # it gets the whole-org prefix with no narrower path restriction --
        # the same default converter_service uses when a tool/node declares
        # use_storage but no allowed paths.
        use_storage = PythonCodeTool.objects.filter(
            python_code=python_code, use_storage=True
        ).exists()
        storage_org_prefix = f"org_{organization_id}" if use_storage else None

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
            org_id=organization_id if use_storage else None,
            secrets=secrets,
        )

        channel = self.code_exec_task_channel
        # Trusted scope for the storage-credential issuer, written before the
        # task itself is published.
        publish_credential_scope(self.redis_service.redis_client, code_task_data)
        self.redis_service.redis_client.publish(
            channel, code_task_data.model_dump_json()
        )
        return execution_id

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
