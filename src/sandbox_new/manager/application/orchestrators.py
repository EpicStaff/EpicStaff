import asyncio
import hashlib
import os
import shutil
from pathlib import Path
from typing import Any

import settings
from loguru import logger

from manager.application.holding import JobHoldingRegistry
from manager.application.ports import (
    AbstractJobDispatcher,
    AbstractJobFailureSink,
    AbstractUnitOfWork,
    AbstractUVProvider,
)
from manager.domain.enums import VenvStatus
from manager.domain.errors import VenvNotFoundError
from manager.domain.models import Job, Library, Venv

_VENV_BUILD_FAILED_MESSAGE = "Execution environment failed to build; the job was not run."

__all__ = ["JobOrchestrator", "VenvBuildOrchestrator", "VenvCRUDOrchestrator"]

type List[T] = list[T]


class VenvCRUDOrchestrator:
    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow

    async def retrieve_default(self) -> Venv | None:
        async with self.uow:
            return await self.uow.venv_repo.retrieve_default()

    async def list(
        self,
        *,
        ids: List[int] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[Venv], int]:
        async with self.uow:
            return await self.uow.venv_repo.list(ids=ids, limit=limit, offset=offset)

    async def retrieve(self, id: int) -> Venv:
        async with self.uow:
            venv = await self.uow.venv_repo.retrieve(id=id)
        if venv is None:
            raise VenvNotFoundError(venv_id=id)
        return venv

    async def create(self, name: str, libs: List[Library]) -> Venv:
        venv = Venv(name=name, libs=libs)
        async with self.uow:
            venv = await self.uow.venv_repo.create(venv)
            await self.uow.commit()
        return venv

    async def update(self, id: int, name: str | None, libs: List[Library] | None) -> Venv:
        async with self.uow:
            venv = await self.uow.venv_repo.retrieve(id=id)
            if venv is None:
                raise VenvNotFoundError(venv_id=id)

            if name is not None and venv.name != name:
                venv.rename(name)

            if libs is not None:
                venv.set_libs(libs)

            venv = await self.uow.venv_repo.update(venv)
            await self.uow.commit()

        return venv

    async def remove(self, id: int):
        async with self.uow:
            venv = await self.uow.venv_repo.retrieve(id=id)
            if venv is None:
                raise VenvNotFoundError(venv_id=id)
            await self.uow.venv_repo.remove(venv)
            await self.uow.commit()


class VenvBuildOrchestrator:
    def __init__(self, uow: AbstractUnitOfWork, uv_provider: AbstractUVProvider):
        self.uow = uow
        self.uv_provider = uv_provider

    async def build(self, target: int | Venv):
        if isinstance(target, int):
            venv = await self._retrieve(id=target)
        else:
            venv = target

        venv.mark_as_processing()
        venv = await self._update(venv)

        try:
            await self._build(venv)
        except Exception as e:
            venv.mark_as_failed(e)
        else:
            venv.mark_as_completed()

        await self._update(venv)

    async def _build(self, venv: Venv) -> Venv:
        staging_path = settings.VENV_STAGING_DIR / f"venv-{venv.id}"
        if staging_path.exists():
            await self._rmtree(staging_path)
        await self.uv_provider.init_venv(staging_path)

        libs = [f"{library.name}{library.specification}" for library in venv.libs]
        await self.uv_provider.apply(staging_path, *libs)

        lock_file = self.uv_provider.get_lock_file(staging_path)
        lock_hash = hashlib.sha256(lock_file.read_bytes()).hexdigest()
        venv.hash = f"{venv.id}{lock_hash}"
        await self._update(venv)

        venv_path = settings.VENVS_DIR / f"venv-{venv.hash}"
        if venv_path.exists():
            await self._rmtree(staging_path)
        else:
            os.replace(staging_path, venv_path)

        # Mandatory shared packages (dotdict, epicstaff_secrets, ...) go into every venv
        # -- freshly built or reused -- so existing venvs also pick them up on the next
        # build. They are intentionally kept out of venv.libs.
        await self.uv_provider.install_local(venv_path, *settings.PREDEFINED_VENV_PACKAGES)

        return venv

    async def _retrieve(self, id: int) -> Venv:
        async with self.uow:
            venv = await self.uow.venv_repo.retrieve(id=id)
        if venv is None:
            raise VenvNotFoundError(venv_id=id)
        return venv

    async def _update(self, venv: Venv) -> Venv:
        async with self.uow:
            venv = await self.uow.venv_repo.update(venv)
            await self.uow.commit()
        return venv

    @staticmethod
    async def _rmtree(path: Path, /):
        return await asyncio.to_thread(shutil.rmtree, path)


class JobOrchestrator:
    """Accepts code-execution submissions and gets them to the worker.

    Resolves the job's venv (by id, or the default when none is given), then: a
    COMPLETED venv dispatches now; a venv still building holds until it is done; a
    FAILED venv reports a failed result to the consumer (the job cannot run, but the
    caller still gets an outcome). Jobs are never persisted; holding is in RAM.

    The readiness gate lives only here: the dispatcher is a dumb transport adapter,
    so this is the single place that decides dispatch vs hold vs fail by venv status.
    """

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        dispatcher: AbstractJobDispatcher,
        holding: JobHoldingRegistry,
        failure_sink: AbstractJobFailureSink,
    ):
        self.uow = uow
        self.dispatcher = dispatcher
        self.holding = holding
        self.failure_sink = failure_sink

    async def submit(
        self,
        *,
        execution_id: str,
        session_id: int,
        code: str,
        entrypoint: str,
        global_kwargs: dict[str, Any],
        func_kwargs: dict[str, Any],
        secrets: dict[str, Any],
        venv_id: int | None,
        use_storage: bool,
        storage_allowed_paths: List[str],
        storage_org_prefix: str | None,
        timeout: float | None,
    ) -> Job:
        venv = await self._resolve_venv(venv_id)

        job = Job(
            session_id=session_id,
            execution_id=execution_id,
            venv_id=venv.id,
            venv_hash=venv.hash,
            code=code,
            result="",
            entrypoint=entrypoint,
            secrets=secrets,
            global_kwargs=global_kwargs,
            func_kwargs=func_kwargs,
            use_storage=use_storage,
            storage_allowed_paths=storage_allowed_paths,
            storage_org_prefix=storage_org_prefix,
            timeout=timeout,
            error=None,
        )

        if venv.status is VenvStatus.FAILED:
            await self.failure_sink.fail(execution_id, _VENV_BUILD_FAILED_MESSAGE)
        elif venv.status is VenvStatus.COMPLETED:
            await self._dispatch(job)
        else:
            self.holding.hold(venv.id, job)

        return job

    async def flush_pending(self) -> None:
        """Release held jobs: dispatch when the venv is COMPLETED, fail them if it failed."""
        for venv_id in self.holding.pending_venv_ids():
            async with self.uow:
                venv = await self.uow.venv_repo.retrieve(venv_id)

            if venv is None or venv.status is VenvStatus.FAILED:
                for job in self.holding.release(venv_id):
                    await self.failure_sink.fail(job.execution_id, _VENV_BUILD_FAILED_MESSAGE)
                continue

            if venv.status is VenvStatus.COMPLETED:
                for job in self.holding.release(venv_id):
                    # The venv had no hash when the job was held; stamp the built one.
                    job.venv_hash = venv.hash
                    await self._dispatch(job)

    async def _dispatch(self, job: Job) -> None:
        """Hand a job to the worker; a dispatch failure is logged, not raised."""
        try:
            await self.dispatcher.dispatch(job)
        except Exception:
            logger.exception("Failed to dispatch job {}", job.execution_id)

    async def _resolve_venv(self, venv_id: int | None) -> Venv:
        async with self.uow:
            if venv_id is not None:
                venv = await self.uow.venv_repo.retrieve(venv_id)
            else:
                venv = await self.uow.venv_repo.retrieve_default()
        if venv is None:
            raise VenvNotFoundError(venv_id=venv_id)
        return venv
