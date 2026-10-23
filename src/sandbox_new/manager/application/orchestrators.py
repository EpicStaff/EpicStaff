import asyncio
import hashlib
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import settings
from loguru import logger

from manager.application.holding import JobHoldingRegistry
from manager.application.intake import IntakeGate
from manager.application.ports import (
    AbstractJobDispatcher,
    AbstractJobFailureSink,
    AbstractUnitOfWork,
    AbstractUVProvider,
)
from manager.application.registry import ExecutionRegistry
from manager.domain.enums import ExecutionStatus, VenvStatus
from manager.domain.errors import SandboxOverloadedError, VenvNotFoundError
from manager.domain.models import Job, Library, StorageCredentials, Venv

_VENV_BUILD_FAILED_MESSAGE = "Execution environment failed to build; the job was not run."
_DISPATCH_FAILED_MESSAGE = "The job could not be handed to the worker and was not run."
_HOLD_TIMED_OUT_MESSAGE = (
    "The execution environment did not finish building in time; the job was not run."
)
# A re-POST that arrives while the first request for its id is still being admitted is
# told to come back this soon: by then the first request has its outcome.
_SUBMISSION_IN_PROGRESS_RETRY_AFTER_SECONDS = 1

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
        logger.info("Declared venv {} ({}) with {} libraries", venv.id, venv.name, len(venv.libs))
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

        logger.info("Updated venv {}, status {}", venv.id, venv.status.value)
        return venv

    async def remove(self, id: int):
        async with self.uow:
            venv = await self.uow.venv_repo.retrieve(id=id)
            if venv is None:
                raise VenvNotFoundError(venv_id=id)
            await self.uow.venv_repo.remove(venv)
            await self.uow.commit()
        logger.info("Removed venv {}", id)


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
        logger.info("Building venv {} with {} libraries", venv.id, len(venv.libs))

        try:
            await self._build(venv)
        except Exception as e:
            venv.mark_as_failed(e)
            logger.exception("Venv {} failed to build", venv.id)
        else:
            venv.mark_as_completed()
            logger.info("Venv {} built, hash {}", venv.id, venv.hash)

        await self._update(venv)

    async def _build(self, venv: Venv) -> Venv:
        staging_path = settings.VENV_STAGING_DIR / f"venv-{venv.id}"
        if staging_path.exists():
            await self._rmtree(staging_path)
        await self.uv_provider.init_venv(staging_path)

        libs = [library.requirement for library in venv.libs]
        await self.uv_provider.apply(staging_path, *libs)
        # Held, not applied yet: stamping the libraries is what the user sees as the
        # outcome of the build, so it must not survive a step below that fails.
        resolved_versions = self.uv_provider.read_resolved_versions(staging_path)

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

        venv.apply_resolved_versions(resolved_versions)
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

    Every submission is recorded in the execution registry, and a job that would run
    (held or queued) passes the intake gate first. A held job gets a hold deadline; it
    is failed without running if its venv is not built by then. A job handed to the
    worker queue gets a queue deadline; the worker fails it instead of running it once
    that has passed.
    """

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        dispatcher: AbstractJobDispatcher,
        holding: JobHoldingRegistry,
        failure_sink: AbstractJobFailureSink,
        registry: ExecutionRegistry,
        intake_gate: IntakeGate,
        *,
        queue_timeout: float,
        hold_timeout: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.uow = uow
        self.dispatcher = dispatcher
        self.holding = holding
        self.failure_sink = failure_sink
        self.registry = registry
        self.intake_gate = intake_gate
        self.queue_timeout = queue_timeout
        self.hold_timeout = hold_timeout
        self.clock = clock

    async def submit(
        self,
        *,
        execution_id: str,
        session_id: int | None,
        code: str,
        entrypoint: str,
        global_kwargs: dict[str, Any],
        func_kwargs: dict[str, Any],
        secrets: dict[str, Any],
        venv_id: int | None,
        use_storage: bool,
        storage_allowed_paths: List[str],
        storage_org_prefix: str | None,
        storage_credentials: StorageCredentials | None,
        timeout: float | None,
        reply_to_crew_channel: bool,
    ) -> ExecutionStatus:
        """Accept a submission, or answer for the one already accepted under its id.

        A re-POST of a known `execution_id` (a producer retrying after a lost 202) is
        not enqueued again: it gets the first submission's current status. While the
        first submission is still resolving its venv or being admitted, its outcome is
        not known yet -- it may still be refused -- so the re-POST is told to retry
        rather than answered QUEUED for a job that might never be queued.

        Returns:
            Where the execution is now.

        Raises:
            VenvNotFoundError: `venv_id` names no venv, or there is no default venv.
            SandboxOverloadedError: The sandbox cannot take the job now, or the first
                submission of this id is still being admitted.
        """
        if self.registry.is_reserved(execution_id):
            logger.info("Execution {} is still being admitted; re-POST told to retry", execution_id)
            raise SandboxOverloadedError(retry_after=_SUBMISSION_IN_PROGRESS_RETRY_AFTER_SECONDS)

        known_status = self.registry.status(execution_id)
        if known_status is not None:
            logger.info("Execution {} is already known; not enqueued again", execution_id)
            return known_status

        # Reserved before the first await, so a concurrent re-POST sees the id as known.
        self.registry.reserve(execution_id)
        try:
            venv = await self._resolve_venv(venv_id)
            if venv.status is not VenvStatus.FAILED:
                self.intake_gate.admit(will_be_held=venv.status is not VenvStatus.COMPLETED)
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
                storage_credentials=storage_credentials,
                timeout=timeout,
                reply_to_crew_channel=reply_to_crew_channel,
                error=None,
            )
        except BaseException:
            # Refused or interrupted before anything was enqueued: no result will ever
            # finish this id, so it must not stay reserved and count against the cap.
            self.registry.forget(execution_id)
            raise

        if venv.status is VenvStatus.FAILED:
            logger.warning("Execution {} rejected: venv {} failed to build", execution_id, venv.id)
            await self._fail(job, _VENV_BUILD_FAILED_MESSAGE)
        elif venv.status is VenvStatus.COMPLETED:
            await self._dispatch(job)
        else:
            logger.info("Execution {} held until venv {} finishes building", execution_id, venv.id)
            self.registry.mark_held(execution_id)
            self.holding.hold(venv.id, job, deadline=self.clock() + self.hold_timeout)

        return self.registry.get_status(execution_id)

    async def flush_pending(self) -> None:
        """Release held jobs: dispatch when the venv is COMPLETED, fail them if it failed.

        A job held past its hold deadline is failed first, whatever its venv's status:
        a venv stuck building (or rebuilt on purpose) must not keep jobs waiting longer
        than their producers wait for a result.

        A released job is dispatched even when the in-flight cap is full: it was
        admitted already and has waited for its venv, and the worker's run gate still
        bounds what runs at once. The cap is thus exceeded by at most the held cap.
        """
        for job in self.holding.release_overdue(self.clock()):
            logger.warning("Execution {} held past its hold deadline; not run", job.execution_id)
            await self._fail(job, _HOLD_TIMED_OUT_MESSAGE)

        for venv_id in self.holding.pending_venv_ids():
            async with self.uow:
                venv = await self.uow.venv_repo.retrieve(venv_id)

            if venv is None or venv.status is VenvStatus.FAILED:
                for job in self.holding.release(venv_id):
                    await self._fail(job, _VENV_BUILD_FAILED_MESSAGE)
                continue

            if venv.status is VenvStatus.COMPLETED:
                for job in self.holding.release(venv_id):
                    # The venv had no hash when the job was held; stamp the built one.
                    job.venv_hash = venv.hash
                    await self._dispatch(job)

    async def _dispatch(self, job: Job) -> None:
        """Hand a job to the worker, reporting a failed dispatch as a failed run.

        The queue deadline starts here, not at submission: time spent held while the
        venv builds is not queue time.

        The caller was already answered 202, so the only way it learns about a job
        that never reached the worker is a result. Staying silent would leave it
        waiting for one for good, and the credentials it issued unrevoked.
        """
        job.queue_deadline = self.clock() + self.queue_timeout
        self.registry.mark_queued(job.execution_id)
        try:
            await self.dispatcher.dispatch(job)
        except Exception as error:
            # Type only: a validation error's text would quote the job's secrets.
            logger.error("Failed to dispatch job {}: {}", job.execution_id, type(error).__name__)
            await self._fail(job, _DISPATCH_FAILED_MESSAGE)

    async def _fail(self, job: Job, message: str) -> None:
        await self.failure_sink.fail(
            job.execution_id,
            message,
            reply_to_crew_channel=job.reply_to_crew_channel,
        )

    async def _resolve_venv(self, venv_id: int | None) -> Venv:
        async with self.uow:
            if venv_id is not None:
                venv = await self.uow.venv_repo.retrieve(venv_id)
            else:
                venv = await self.uow.venv_repo.retrieve_default()
        if venv is None:
            raise VenvNotFoundError(venv_id=venv_id)
        return venv
