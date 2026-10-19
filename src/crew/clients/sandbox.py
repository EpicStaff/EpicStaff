"""HTTP intake client for sandbox_new.

crew submits a code execution to sandbox_new over HTTP (`POST /executions`) and
receives the result back on the Redis result channel, unchanged. The request body
mirrors sandbox_new's ExecutionSubmitSchema; the venv is addressed by `venv_id`
(None means sandbox_new's default venv). Storage credentials are minted upstream
by django_app and only passed through here; sandbox_new rejects an execution with
`use_storage` set and no credentials.
"""

from typing import Any

from src.shared.models.storage_scope import StorageCredentials

from clients.http_client import AsyncClient


class SandboxClient(AsyncClient):
    async def submit(
        self,
        *,
        execution_id: str,
        venv_id: int | None,
        session_id: int | None,
        code: str,
        entrypoint: str,
        func_kwargs: dict[str, Any],
        global_kwargs: dict[str, Any],
        secrets: dict[str, str],
        use_storage: bool,
        storage_allowed_paths: list[str],
        storage_org_prefix: str | None,
        storage_credentials: StorageCredentials | None,
        timeout: float | None,
    ) -> None:
        """Hand one execution to sandbox_new. Raises ClientError on a failed submit."""
        await self.request(
            method="POST",
            url="/executions",
            json={
                "execution_id": execution_id,
                "venv_id": venv_id,
                "session_id": session_id,
                "code": code,
                "entrypoint": entrypoint,
                "func_kwargs": func_kwargs,
                "global_kwargs": global_kwargs,
                "secrets": secrets,
                "use_storage": use_storage,
                "storage_allowed_paths": storage_allowed_paths,
                "storage_org_prefix": storage_org_prefix,
                "storage_credentials": (
                    storage_credentials.model_dump() if storage_credentials is not None else None
                ),
                "timeout": timeout,
            },
        )
