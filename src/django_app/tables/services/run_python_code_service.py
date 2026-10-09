import uuid
from datetime import UTC, datetime
from typing import Any

from django.conf import settings
from django.utils import timezone
from src.shared.models import CodeResultData, CodeTaskData
from tables.exceptions import CodeRunTargetNotFoundError
from tables.models import PythonCode, PythonCodeResult
from tables.services.code_run_targets import CODE_RUN_TARGETS, storage_path_for_test_run
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
        self._assert_secrets_declared(
            python_code_id=python_code_id, code=python_code.code, declared=declared
        )
        secrets = secret_resolver.resolve_named(
            names=sorted(declared),
            org_id=organization_id,
            context=f"PythonCode(id={python_code_id}).secrets",
        )

        execution_id = self.gen_execution_id()
        code_task_data = CodeTaskData(
            venv_name=f"venv_{python_code_id}",
            libraries=python_code.get_libraries_list(),
            code=python_code.code,
            entrypoint=python_code.entrypoint,
            func_kwargs=varaibles,
            execution_id=execution_id,
            global_kwargs={**python_code.global_kwargs, **additional_global_kwargs},
            secrets=secrets,
        )
        self._record_and_publish(
            code_task_data=code_task_data,
            python_code=python_code,
            organization_id=organization_id,
            user=user,
        )
        return execution_id

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
        does. Writes a PENDING `PythonCodeResult` and publishes the task on the
        code-exec channel.

        Args:
            target_type: A key of `CODE_RUN_TARGETS`.

        Returns:
            The execution id the result is stored under.

        Raises:
            CodeRunTargetNotFoundError: No live target with this id in
                `organization_id`, or its code slot is empty.
            UndeclaredSecretError: The code reads a secret it did not declare.
                Nothing is written or published.
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
        )
        resolved = secret_resolver.resolve_payload(payload=python_code_data, org_id=organization_id)

        global_kwargs = dict(resolved.global_kwargs or {})
        if resolved.org_id is not None:
            global_kwargs["org_id"] = resolved.org_id

        execution_id = self.gen_execution_id()
        code_task_data = CodeTaskData(
            venv_name=resolved.venv_name,
            libraries=resolved.libraries,
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
        )
        self._record_and_publish(
            code_task_data=code_task_data,
            python_code=python_code,
            organization_id=organization_id,
            user=user,
        )
        return execution_id

    @staticmethod
    def _assert_secrets_declared(*, python_code_id: int, code: str, declared: set[str]) -> None:
        """Raise if `code` reads a secret outside `declared`."""
        undeclared = parse_secret_names(code=code) - declared
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

    def _record_and_publish(
        self,
        *,
        code_task_data: CodeTaskData,
        python_code: PythonCode,
        organization_id: int,
        user,
    ) -> None:
        PythonCodeResult.objects.create(
            execution_id=code_task_data.execution_id,
            org_id=organization_id,
            created_by=user,
            python_code=python_code,
        )
        self._evict_oldest_results(organization_id)
        self.redis_service.redis_client.publish(
            self.code_exec_task_channel, code_task_data.model_dump_json()
        )

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

    def gen_execution_id(self):
        now = datetime.now(UTC)
        short_uuid = str(uuid.uuid4())[:4]
        formatted_time = now.strftime(f"%d-%m-%Y_%H-%M-%S-{now.microsecond // 1000:03d}")
        return f"{formatted_time}@{short_uuid}"
