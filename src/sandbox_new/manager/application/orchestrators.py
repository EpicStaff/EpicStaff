import asyncio
import builtins
import hashlib
import io
import os
import shutil
import tarfile
import tempfile
import time
import zipfile
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import settings
from common.public_errors import log_sandbox_failure, sandbox_failure
from litestar.datastructures import UploadFile
from loguru import logger
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from src.shared.bench_log import BENCH_LEVEL
from src.shared.models.code_failure import CodeFailure, CodeFailureCode

from manager.application.errors import VenvNotFoundError
from manager.application.holding import JobHoldingRegistry
from manager.application.intake import IntakeGate
from manager.application.ports import (
    AbstractFileStorage,
    AbstractJobDispatcher,
    AbstractJobFailureSink,
    AbstractUnitOfWork,
    AbstractUVProvider,
)
from manager.application.ports.errors import (
    DependencyConflictError,
    EnvironmentBuildError,
    PackageNotFoundError,
    PackageVersionNotFoundError,
)
from manager.application.registry import ExecutionRegistry
from manager.domain.enums import (
    ExecutionStatus,
    VenvBuildErrorKind,
    VenvOrder,
    VenvStatus,
    WheelOffer,
    WheelStatus,
)
from manager.domain.errors import (
    BaseError,
    CustomLibraryInUseError,
    CustomLibraryNameNotFoundError,
    CustomLibraryNameTakenError,
    CustomLibraryNotFoundError,
    CustomLibraryNotPublishedError,
    CustomLibraryStillBuildingError,
    UnsupportedUploadError,
    WheelInUseError,
    WheelNameMismatchError,
    WheelNotBuiltError,
    WheelNotFoundError,
    WheelSourceAlreadyUploadedError,
    WheelVersionTakenError,
)
from manager.domain.models import (
    SOURCE_ARCHIVE_SUFFIXES,
    WHEEL_SUFFIX,
    CustomLibrary,
    Job,
    Library,
    StorageCredentials,
    Venv,
    Wheel,
)
from manager.domain.services import offer_wheels, order_by_version

_VENV_BUILD_FAILED_MESSAGE = "Couldn't install the libraries: {error}"
_HOLD_TIMED_OUT_MESSAGE = "The libraries are still being installed. Try again in a minute."
# Read in pieces so that an upload is never held in memory whole.
_UPLOAD_CHUNK_SIZE = 1024 * 1024

__all__ = [
    "CustomLibraryCRUDOrchestrator",
    "CustomLibraryReapOrchestrator",
    "JobOrchestrator",
    "VenvBuildOrchestrator",
    "VenvCRUDOrchestrator",
    "WheelBuildOrchestrator",
    "WheelCRUDOrchestrator",
]

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
        name_contains: str | None = None,
        order: VenvOrder = VenvOrder.DEFAULT,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[Venv], int]:
        async with self.uow:
            return await self.uow.venv_repo.list(
                ids=ids,
                name_contains=name_contains,
                order=order,
                limit=limit,
                offset=offset,
            )

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


# Build errors whose text names only what the user declared, so it is stored as is. The
# custom library refusals come before the build starts; a library that isn't stored is a
# package that doesn't exist, and one with nothing built has no version to install.
_DECLARED_PACKAGE_ERROR_KINDS: dict[type[BaseError], VenvBuildErrorKind] = {
    PackageNotFoundError: VenvBuildErrorKind.PACKAGE_NOT_FOUND,
    PackageVersionNotFoundError: VenvBuildErrorKind.PACKAGE_VERSION_NOT_FOUND,
    DependencyConflictError: VenvBuildErrorKind.PACKAGE_DEPENDENCY_CONFLICT,
    CustomLibraryNameNotFoundError: VenvBuildErrorKind.PACKAGE_NOT_FOUND,
    CustomLibraryNotPublishedError: VenvBuildErrorKind.PACKAGE_VERSION_NOT_FOUND,
}


def _build_failure(error: Exception) -> tuple[VenvBuildErrorKind, str]:
    """The kind and the text to store for a build that raised `error`.

    Any exception but a declared-package error can carry paths or tool output in its
    text, so it is stored as the generic hint; its detail is left to the build's log line.
    """
    kind = _DECLARED_PACKAGE_ERROR_KINDS.get(type(error))
    if kind is None:
        return VenvBuildErrorKind.PACKAGE_INSTALL_FAILED, EnvironmentBuildError.default_message
    return kind, str(error)


class VenvBuildOrchestrator:
    def __init__(
        self,
        uow: AbstractUnitOfWork,
        uv_provider: AbstractUVProvider,
        file_storage: AbstractFileStorage,
    ):
        self.uow = uow
        self.uv_provider = uv_provider
        self.file_storage = file_storage

    async def build(self, target: int | Venv):
        if isinstance(target, int):
            venv = await self._retrieve(id=target)
        else:
            venv = target

        # Before anything is started: a venv refused here has had nothing done to it,
        # and one that is only waiting must not look like one that is being built.
        try:
            custom_wheels = await self._offered_wheels(venv)
        except CustomLibraryStillBuildingError as waiting:
            venv.mark_as_waiting()
            await self._update(venv)
            logger.info("Venv {} waits: {}", venv.id, waiting)
            return
        except BaseError as error:
            venv.mark_as_failed(*_build_failure(error))
            await self._update(venv)
            logger.warning("Venv {} cannot be built: {}", venv.id, error)
            return

        venv.mark_as_processing()
        venv = await self._update(venv)
        logger.info("Building venv {} with {} libraries", venv.id, len(venv.libs))

        try:
            await self._build(venv, custom_wheels)
        except Exception as e:
            venv.mark_as_failed(*_build_failure(e))
            logger.exception("Venv {} failed to build", venv.id)
        else:
            venv.mark_as_completed()
            logger.info("Venv {} built, hash {}", venv.id, venv.hash)

        await self._update(venv)

    async def _offered_wheels(self, venv: Venv) -> list[Wheel]:
        """The wheels this venv's custom libraries offer, in two queries for them all.

        One query per entry would be a query per library on a tick that runs every
        five seconds, so the libraries and their wheels are read in bulk and matched
        up here.

        Raises:
            CustomLibraryNameNotFoundError: An entry names no stored library.
            CustomLibraryNotPublishedError: A library has no built version and none
                on its way.
            CustomLibraryStillBuildingError: A version the venv needs is being built.
        """
        entries = [library for library in venv.libs if library.is_custom]
        if not entries:
            return []

        async with self.uow:
            libraries = await self.uow.custom_library_repo.list_by_names(
                [entry.name for entry in entries]
            )
            wheels = await self.uow.wheel_repo.list_by_library_ids(
                [library.id for library in libraries]
            )

        stored = {library.name: library for library in libraries}
        by_library: dict[int, list[Wheel]] = defaultdict(list)
        for wheel in wheels:
            by_library[wheel.library_id].append(wheel)

        offered: list[Wheel] = []
        for entry in entries:
            library = stored.get(entry.name)
            if library is None:
                raise CustomLibraryNameNotFoundError(name=entry.name)

            offer = offer_wheels(by_library[library.id], specification=entry.specification)
            if offer.outcome is WheelOffer.WAIT:
                raise CustomLibraryStillBuildingError(name=entry.name)
            if offer.outcome is WheelOffer.NOTHING_BUILT:
                raise CustomLibraryNotPublishedError(name=entry.name)
            offered.extend(offer.wheels)
        return offered

    async def _fill_wheelhouse(self, wheels: list[Wheel], directory: Path) -> Path | None:
        """Download the offered wheels into `directory`, or answer None for none.

        None rather than an empty directory: a venv of ordinary packages should not
        have the resolver pointed at a source that holds nothing.
        """
        if not wheels:
            return None
        for wheel in wheels:
            content = await self.file_storage.get(wheel.wheel_key)
            (directory / wheel.wheel_filename).write_bytes(content)
        return directory

    async def _build(self, venv: Venv, custom_wheels: list[Wheel]) -> Venv:
        staging_path = settings.VENV_STAGING_DIR / f"venv-{venv.id}"
        if staging_path.exists():
            await self._rmtree(staging_path)
        await self.uv_provider.init_venv(staging_path)

        libs = [library.requirement for library in venv.libs]
        # The wheelhouse lives only for this build, and is deliberately not cached: a
        # cache would be another place a deleted wheel could still be installed from.
        with tempfile.TemporaryDirectory() as workspace:
            wheelhouse = await self._fill_wheelhouse(custom_wheels, Path(workspace))
            await self.uv_provider.apply(staging_path, *libs, wheelhouse=wheelhouse)
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
    worker queue is stamped with the moment it was queued; the worker fails it instead
    of running it once it has waited longer than the queue timeout.

    Args:
        clock: Monotonic clock for hold deadlines, which never leave this process.
        wall_clock: Clock for `Job.queued_at`, which crosses to the worker and so must
            mean the same thing in another process.
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
        hold_timeout: float,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        self.uow = uow
        self.dispatcher = dispatcher
        self.holding = holding
        self.failure_sink = failure_sink
        self.registry = registry
        self.intake_gate = intake_gate
        self.hold_timeout = hold_timeout
        self.clock = clock
        self.wall_clock = wall_clock

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
        self.intake_gate.check_not_in_progress(execution_id)

        known_status = self.registry.status(execution_id)
        if known_status is not None:
            logger.info("Execution {} is already known; not enqueued again", execution_id)
            return known_status

        # Reserved before the first await, so a concurrent re-POST sees the id as known.
        self.registry.reserve(execution_id)
        try:
            venv = await self._resolve_venv(venv_id)
            if venv.status is not VenvStatus.FAILED:
                self.intake_gate.admit(
                    execution_id, will_be_held=venv.status is not VenvStatus.COMPLETED
                )
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
            await self._fail(job, _venv_build_failure(venv))
        elif venv.status is VenvStatus.COMPLETED:
            await self._dispatch(job)
        else:
            logger.info("Execution {} held until venv {} finishes building", execution_id, venv.id)
            self.registry.mark_held(execution_id)
            self.holding.hold(venv.id, job, deadline=self.clock() + self.hold_timeout)
            logger.log(
                BENCH_LEVEL,
                "bench {checkpoint}",
                checkpoint="exec_held",
                session_id=session_id,
                execution_id=execution_id,
                venv_id=venv.id,
            )

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
            await self._fail(
                job, CodeFailure(code=CodeFailureCode.HOLD_TIMEOUT, detail=_HOLD_TIMED_OUT_MESSAGE)
            )

        for venv_id in self.holding.pending_venv_ids():
            async with self.uow:
                venv = await self.uow.venv_repo.retrieve(venv_id)

            if venv is None or venv.status is VenvStatus.FAILED:
                failure = _venv_build_failure(venv)
                for job in self.holding.release(venv_id):
                    await self._fail(job, failure)
                continue

            if venv.status is VenvStatus.COMPLETED:
                for job in self.holding.release(venv_id):
                    # The venv had no hash when the job was held; stamp the built one.
                    job.venv_hash = venv.hash
                    await self._dispatch(job)

    async def _dispatch(self, job: Job) -> None:
        """Hand a job to the worker, reporting a failed dispatch as a failed run.

        Queue time starts here, not at submission: time spent held while the venv
        builds is not queue time.

        The caller was already answered 202, so the only way it learns about a job
        that never reached the worker is a result. Staying silent would leave it
        waiting for one for good, and the credentials it issued unrevoked.
        """
        job.queued_at = self.wall_clock()
        self.registry.mark_queued(job.execution_id)
        try:
            await self.dispatcher.dispatch(job)
        except Exception as error:
            # Type only: a validation error's text would quote the job's secrets.
            reference = log_sandbox_failure(
                f"Failed to dispatch the job: {type(error).__name__}",
                execution_id=job.execution_id,
            )
            failure = sandbox_failure(CodeFailureCode.DISPATCH_FAILED, reference)
            await self._fail(job, failure, reference=reference)

    async def _fail(self, job: Job, failure: CodeFailure, reference: str | None = None) -> None:
        await self.failure_sink.fail(
            job.execution_id,
            failure,
            reference=reference,
            session_id=job.session_id,
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


def _venv_build_failure(venv: Venv | None) -> CodeFailure:
    """The failure a job gets when its venv failed to build, or vanished while it was held.

    The code is the build error's kind. Only an error whose kind says it names what the
    user declared is quoted; any other failure, and one stored before kinds were, gets the
    generic hint, and a failure with no kind, or a vanished venv, the generic code.
    """
    kind = venv.error_kind if venv is not None else None
    code = (
        CodeFailureCode(kind.value) if kind is not None else CodeFailureCode.PACKAGE_INSTALL_FAILED
    )
    error = venv.build_error_detail if venv is not None else None
    if error is not None:
        detail = _VENV_BUILD_FAILED_MESSAGE.format(error=error)
    else:
        detail = EnvironmentBuildError.default_message
    return CodeFailure(code=code, detail=detail)


class CustomLibraryCRUDOrchestrator:
    # No file storage: a library holds no files of its own, and deleting the files its
    # wheels hold is the reaper's job, not this one's.
    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow

    async def list(
        self,
        ids: list[int] | None,
        limit: int | None,
        offset: int | None,
    ) -> tuple[list[tuple[CustomLibrary, list[Wheel]]], int]:
        """One page of libraries, each with its versions, and the total before paging.

        The versions of the whole page are read in one query rather than one per
        library: a reader is shown what state a library's builds are in, and that
        must not cost a round trip per row.
        """
        async with self.uow:
            objs, total = await self.uow.custom_library_repo.list(
                ids=ids, limit=limit, offset=offset
            )
            wheels = await self.uow.wheel_repo.list_by_library_ids([obj.id for obj in objs])

        by_library: dict[int, list[Wheel]] = defaultdict(list)
        for wheel in wheels:
            by_library[wheel.library_id].append(wheel)
        return [(obj, by_library[obj.id]) for obj in objs], total

    # `builtins.list`: the method named `list` above shadows the builtin for every
    # annotation in this class body from here on.
    async def retrieve(self, id: int) -> tuple[CustomLibrary, builtins.list[Wheel]]:
        """One library and its versions.

        Raises:
            CustomLibraryNotFoundError: No library with this id.
        """
        async with self.uow:
            obj = await self._retrieve(id)
            return obj, await self.uow.wheel_repo.list(id)

    async def create(self, name: str | None) -> CustomLibrary:
        """Create a library, named or not.

        Raises:
            CustomLibraryNameTakenError: Some library already has this name.
        """
        obj = CustomLibrary(name=name)
        async with self.uow:
            # Against `obj.name`, not `name`: the domain canonicalizes on construction,
            # and it is the canonical spelling that has to be unique. An unnamed library
            # never clashes with anything -- the partial unique index does not even
            # look at a null name -- so there is nothing to check for one.
            if obj.name is not None:
                await self._reject_taken_name(obj.name)
            obj = await self.uow.custom_library_repo.create(obj)
            await self.uow.commit()
        logger.info("Created custom library {} ({})", obj.id, obj.name or "unnamed")
        return obj

    async def create_for(self, filename: str) -> CustomLibrary:
        """Create a library for an upload: a wheel names it at once, no name ever
        typed; a source archive's distribution is not known until it builds, so it
        starts unnamed and a later build names it.

        Raises:
            UnsupportedUploadError: The filename ends in a wheel's suffix but does not
                parse as one.
            CustomLibraryNameTakenError: A wheel's name is already another library's.
        """
        if not filename.lower().endswith(WHEEL_SUFFIX):
            return await self.create(None)
        try:
            name, _, _, _ = parse_wheel_filename(filename)
        except InvalidWheelFilename as error:
            raise UnsupportedUploadError(str(error)) from error
        return await self.create(str(name))

    async def remove(self, id: int):
        """Mark the library and every wheel of it deleted.

        Nothing is removed here: the artifacts are in the object store, which this
        transaction cannot roll back, so a background task deletes them and the rows
        afterwards. Until it does, the library answers no read.
        """
        async with self.uow:
            obj = await self._retrieve(id)

            # Refused rather than cascaded: a venv naming a library that is gone would
            # fail on its next build, and its author never asked for that.
            users = await self.uow.venv_repo.list_using_custom_library(obj.name)
            if users:
                raise CustomLibraryInUseError(custom_library_id=id, venv_count=len(users))

            obj.mark_as_deleted()
            await self.uow.custom_library_repo.update(obj)

            # Marked now rather than left to the reaper to work out: reads are scoped
            # to live rows, so the wheels have to stop answering the moment the library
            # does, and the reaper deletes what is marked, nothing else.
            wheels = await self.uow.wheel_repo.list(id)
            for wheel in wheels:
                wheel.mark_as_deleted()
                await self.uow.wheel_repo.update(wheel)

            await self.uow.commit()
        logger.info("Marked custom library {} and its {} wheels as deleted", id, len(wheels))

    async def _retrieve(self, id: int) -> CustomLibrary:
        obj = await self.uow.custom_library_repo.retrieve(id)
        if obj is None:
            raise CustomLibraryNotFoundError(custom_library_id=id)
        return obj

    async def _reject_taken_name(self, name: str):
        """Refuse a canonical name another library already answers to.

        The partial unique index is what actually enforces this; the lookup is here so
        that the ordinary case is a 409 naming the library rather than a failed write.

        Raises:
            CustomLibraryNameTakenError: Some other library already has this name.
        """
        if await self.uow.custom_library_repo.retrieve_by_name(name) is not None:
            raise CustomLibraryNameTakenError(name=name)


class WheelCRUDOrchestrator:
    def __init__(self, uow: AbstractUnitOfWork, file_storage: AbstractFileStorage):
        self.uow = uow
        self.file_storage = file_storage

    async def list(self, library_id: int) -> list[Wheel]:
        """This library's versions, newest first."""
        async with self.uow:
            return order_by_version(await self.uow.wheel_repo.list(library_id))

    async def retrieve(self, library_id: int, id: int) -> Wheel:
        async with self.uow:
            return await self._retrieve(library_id, id)

    async def download_wheel(self, library_id: int, id: int) -> tuple[bytes, str]:
        """Return the wheel's bytes and the name it was stored under.

        Only a `completed` wheel has a file to hand out. Every other status either has
        no wheel yet or never will, and an upload still in flight has a name on the row
        before it has bytes in the object store, so the status is what is checked here.

        Note:
            Reads the whole wheel into memory. An upload cannot exceed the request body
            limit, so neither can what comes back.

        Raises:
            WheelNotFoundError: No wheel with this id in this library. Rendered as 404.
            WheelNotBuiltError: There is no wheel file to return. Rendered as 409.
        """
        async with self.uow:
            obj = await self._retrieve(library_id, id)

        if obj.status is not WheelStatus.COMPLETED or obj.wheel_key is None:
            raise WheelNotBuiltError(wheel_id=id, status=obj.status.value)
        return await self.file_storage.get(obj.wheel_key), obj.wheel_filename

    async def upload(self, library_id: int, file: UploadFile) -> Wheel:
        """Store an uploaded wheel or source archive as a new version of this library.

        A wheel is complete on arrival and ends up `completed`; a source archive ends up
        `declared`, which is what has the background builder pick it up.

        The row is written before the file, in `processing`, because the key it is stored
        under is derived from its id. Only once the file is in the object store does the
        row take its real status, so nothing ever claims to be usable before its bytes
        are there.

        Raises:
            CustomLibraryNotFoundError: No library with this id. Rendered as 404.
            UnsupportedUploadError: Not a wheel or a source archive, or a wheel whose
                name does not parse. Rendered as 400.
            WheelNameMismatchError: An uploaded wheel built for another distribution
                than the library's name, or than an earlier wheel's. Rendered as 400.
            CustomLibraryNameTakenError: This is the library's first wheel, and its
                name is already another library's. Rendered as 409.
            WheelSourceAlreadyUploadedError: This library already holds this exact file.
                Rendered as 409.
            WheelVersionTakenError: This library already holds that version.
                Rendered as 409.
        """
        filename = PurePosixPath(file.filename or "").name
        checksum = await self._checksum(file)

        async with self.uow:
            library = await self._retrieve_library(library_id)
            duplicate = await self.uow.wheel_repo.retrieve_by_sha256(library_id, checksum)
            if duplicate is not None:
                raise WheelSourceAlreadyUploadedError(
                    custom_library_id=library_id, wheel_id=duplicate.id
                )

            obj, version, name = self._declare(library, filename, checksum)
            if name is not None:
                await self._name_or_match(library, name)
            if version is not None:
                await self._reject_taken_version(library_id, version)
            obj = await self.uow.wheel_repo.create(obj)
            await self.uow.commit()

        # shortcut: a crash between the commit above and the status below strands the row
        # in `processing`, where nothing picks it up again. Upgrade when the build moves
        # to its own worker, which needs a sweep for stale `processing` rows anyway.
        key = obj.wheel_key if version is not None else obj.source_key
        try:
            await self.file_storage.put(key, file.file)
        except Exception as error:
            logger.exception("Failed to store the upload for wheel {}", obj.id)
            obj.mark_as_failed(error)
            await self._update(obj)
            raise

        if version is not None:
            obj.mark_as_completed(version, obj.wheel_filename)
        else:
            obj.mark_as_declared()
        obj = await self._update(obj)
        logger.info(
            "Stored {} as wheel {} of custom library {}, status {}",
            filename,
            obj.id,
            library_id,
            obj.status.value,
        )
        return obj

    def _declare(
        self, library: CustomLibrary, filename: str, checksum: str
    ) -> tuple[Wheel, str | None, str | None]:
        """Build the row for an upload, and what it tells about the distribution.

        The version and the name are handed back rather than checked here: a wheel
        carries both in its own filename, while the source archive below has neither
        until it is built, and whether either agrees with the library is the caller's
        question to put to both kinds the same way.

        Raises:
            UnsupportedUploadError: The name is neither a wheel nor a source archive, or
                is a wheel the packaging rules cannot read.
        """
        lowered = filename.lower()
        if lowered.endswith(WHEEL_SUFFIX):
            try:
                name, version, _, _ = parse_wheel_filename(filename)
            except InvalidWheelFilename as error:
                raise UnsupportedUploadError(str(error)) from error
            obj = Wheel(
                library_id=library.id,
                wheel_filename=filename,
                upload_sha256=checksum,
                status=WheelStatus.PROCESSING,
            )
            return obj, str(version), str(name)

        if lowered.endswith(SOURCE_ARCHIVE_SUFFIXES):
            obj = Wheel(
                library_id=library.id,
                source_filename=filename,
                upload_sha256=checksum,
                status=WheelStatus.PROCESSING,
            )
            return obj, None, None

        raise UnsupportedUploadError(filename=filename)

    async def _name_or_match(self, library: CustomLibrary, name: str):
        """Name the library the first time a wheel reveals its distribution, or check
        that a later one agrees with the name an earlier wheel or build already gave it.

        Both sides are canonical: `parse_wheel_filename` normalizes, and so does the
        library on construction.

        Raises:
            CustomLibraryNameTakenError: Some other library already has this name.
            WheelNameMismatchError: The wheel was built for another distribution.
        """
        if library.name is None:
            library.assign_name(name)
            if await self.uow.custom_library_repo.retrieve_by_name(library.name) is not None:
                raise CustomLibraryNameTakenError(name=library.name)
            await self.uow.custom_library_repo.update(library)
            return
        if name != library.name:
            raise WheelNameMismatchError(
                wheel_name=name,
                custom_library_id=library.id,
                library_name=library.name,
            )

    @staticmethod
    async def _checksum(file: UploadFile) -> str:
        """Return the hex sha256 of the upload, leaving it rewound for the caller."""
        digest = hashlib.sha256()
        await file.seek(0)
        while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
            digest.update(chunk)
        await file.seek(0)
        return digest.hexdigest()

    async def _retrieve_library(self, library_id: int) -> CustomLibrary:
        library = await self.uow.custom_library_repo.retrieve(library_id)
        if library is None:
            raise CustomLibraryNotFoundError(custom_library_id=library_id)
        return library

    async def _reject_taken_version(self, library_id: int, version: str):
        """Refuse a version this library already published.

        Raises:
            WheelVersionTakenError: Some wheel of this library already has it.
        """
        if await self.uow.wheel_repo.retrieve_by_version(library_id, version) is not None:
            raise WheelVersionTakenError(custom_library_id=library_id, version=version)

    async def _update(self, obj: Wheel) -> Wheel:
        async with self.uow:
            obj = await self.uow.wheel_repo.update(obj)
            await self.uow.commit()
        return obj

    async def remove(self, library_id: int, id: int):
        """Mark the wheel deleted.

        Nothing is removed here: the files are in the object store, which this
        transaction cannot roll back, so a background task deletes them and the row
        afterwards. The version and the upload it occupied are free again at once,
        which is what makes replacing a published version a delete and a re-upload.
        """
        async with self.uow:
            obj = await self._retrieve(library_id, id)
            await self._reject_installed_version(library_id, obj)
            obj.mark_as_deleted()
            await self.uow.wheel_repo.update(obj)
            await self.uow.commit()
        logger.info("Marked wheel {} of custom library {} as deleted", id, library_id)

    async def _reject_installed_version(self, library_id: int, obj: Wheel):
        """Refuse a version some venv already has installed.

        An unbuilt version carries no number, so nothing can be holding it. A venv
        that names the library with only a specification is not holding it either: a
        specification is a range the build has not chosen from.

        Raises:
            WheelInUseError: Some venv has resolved to exactly this version.
        """
        if obj.version is None:
            return

        library = await self._retrieve_library(library_id)
        users = [
            venv
            for venv in await self.uow.venv_repo.list_using_custom_library(library.name)
            if venv.pins_custom_library(library.name, obj.version)
        ]
        if users:
            raise WheelInUseError(
                custom_library_id=library_id, version=obj.version, venv_count=len(users)
            )

    async def _retrieve(self, library_id: int, id: int) -> Wheel:
        obj = await self.uow.wheel_repo.retrieve(library_id, id)
        if obj is None:
            raise WheelNotFoundError(wheel_id=id)
        return obj


class WheelBuildOrchestrator:
    """Turns a declared wheel's source archive into a wheel in the object store.

    The build runs `uv` on a client's source, which executes that source's build
    backend. It is not isolated yet; see `UVProvider._build_env` for what it is kept
    away from in the meantime.
    """

    def __init__(
        self,
        uow: AbstractUnitOfWork,
        file_storage: AbstractFileStorage,
        uv_provider: AbstractUVProvider,
    ):
        self.uow = uow
        self.file_storage = file_storage
        self.uv_provider = uv_provider

    async def build(self, wheel: Wheel):
        """Build `wheel` and record the outcome on its row.

        Never raises: a build fails for reasons that belong to the uploaded source, so
        the failure is the result, reported through the row's status and `error`.
        """
        wheel.mark_as_processing()
        wheel = await self._update(wheel)
        logger.info("Building wheel {} of custom library {}", wheel.id, wheel.library_id)

        try:
            version = await self._build(wheel)
        except Exception as error:
            wheel.mark_as_failed(error)
            logger.exception("Wheel {} failed to build", wheel.id)
        else:
            wheel.mark_as_completed(version, wheel.wheel_filename)
            logger.info("Wheel {} built as {} {}", wheel.id, wheel.wheel_filename, version)

        await self._update(wheel)

    async def _build(self, wheel: Wheel) -> str:
        """Build the source archive and store the wheel it produces.

        Sets `wheel_filename` before the upload, because the key the wheel is stored
        under is derived from it. The version is returned rather than recorded, so that
        a build which fails after this point leaves it unclaimed and the next attempt
        can still take it.

        Raises:
            EnvironmentBuildError: There is no source archive, or the build produced nothing.
            WheelNameMismatchError: The source builds a different distribution.
            WheelVersionTakenError: This library already holds that version.
        """
        if wheel.source_key is None or wheel.source_filename is None:
            raise EnvironmentBuildError("This wheel has no source archive to build.")

        archive = await self.file_storage.get(wheel.source_key)
        with tempfile.TemporaryDirectory() as workspace:
            root = Path(workspace)
            source_dir = root / "source"
            output_dir = root / "wheel"
            await asyncio.to_thread(self._unpack, archive, wheel.source_filename, source_dir)

            built = await self.uv_provider.build_wheel(self._project_root(source_dir), output_dir)
            name, version, _, _ = parse_wheel_filename(built.name)
            await self._check(wheel, name, str(version))

            wheel.wheel_filename = built.name
            with built.open("rb") as handle:
                await self.file_storage.put(wheel.wheel_key, handle)

        return str(version)

    async def _check(self, wheel: Wheel, name: str, version: str):
        """Hold what the build produced to what the upload promised.

        The archive's own metadata decides the name and the version, and nothing checked
        either before the build: a source may declare any distribution, and the version
        it carries only becomes known here. The first build a library sees names it, the
        same as a wheel uploaded directly; a later one must agree with the name a build
        or a wheel already gave it.

        Raises:
            CustomLibraryNameTakenError: This is the library's first build, and the
                distribution it builds is already another library's.
            WheelNameMismatchError: The source builds a different distribution than the
                one a wheel or an earlier build already named the library.
            WheelVersionTakenError: This library already holds that version.
        """
        async with self.uow:
            library = await self.uow.custom_library_repo.retrieve(wheel.library_id)
            if library is not None:
                if library.name is None:
                    library.assign_name(name)
                    if (
                        await self.uow.custom_library_repo.retrieve_by_name(library.name)
                        is not None
                    ):
                        raise CustomLibraryNameTakenError(name=library.name)
                    await self.uow.custom_library_repo.update(library)
                elif name != library.name:
                    raise WheelNameMismatchError(
                        wheel_name=name,
                        custom_library_id=wheel.library_id,
                        library_name=library.name,
                    )
            taken = await self.uow.wheel_repo.retrieve_by_version(wheel.library_id, version)
            if taken is not None and taken.id != wheel.id:
                raise WheelVersionTakenError(custom_library_id=wheel.library_id, version=version)
            await self.uow.commit()

    @staticmethod
    def _unpack(archive: bytes, filename: str, destination: Path):
        """Extract the uploaded archive into `destination`.

        Members that would land outside it are refused: the archive is a client's file,
        and both formats can name paths that escape the directory they unpack into.

        shortcut: the extracted size is not bounded, so a crafted archive can still fill
        the disk. Upgrade when the build moves into its own isolated worker.
        """
        destination.mkdir(parents=True, exist_ok=True)
        buffer = io.BytesIO(archive)
        if filename.lower().endswith(".zip"):
            with zipfile.ZipFile(buffer) as bundle:
                bundle.extractall(destination)
            return
        with tarfile.open(fileobj=buffer, mode="r:*") as bundle:
            bundle.extractall(destination, filter="data")

    @staticmethod
    def _project_root(path: Path) -> Path:
        """Return the directory the build should run in.

        A source distribution unpacks into one directory named after itself, so the
        project is a level down unless the archive was packed without that wrapper.
        """
        if (path / "pyproject.toml").exists() or (path / "setup.py").exists():
            return path
        entries = [entry for entry in path.iterdir() if entry.is_dir()]
        return entries[0] if len(entries) == 1 else path

    async def _update(self, wheel: Wheel) -> Wheel:
        async with self.uow:
            wheel = await self.uow.wheel_repo.update(wheel)
            await self.uow.commit()
        return wheel


class CustomLibraryReapOrchestrator:
    """Removes what a delete only marked: the artifacts first, then the rows.

    The object store and the database cannot be committed together, so a delete marks
    and this takes the two steps apart. Both are idempotent, which is what makes a run
    that stopped halfway harmless: deleting an object that is not there is not an
    error, and a row that outlived its files is simply dropped on the next pass.
    """

    def __init__(self, uow: AbstractUnitOfWork, file_storage: AbstractFileStorage):
        self.uow = uow
        self.file_storage = file_storage

    async def reap(self):
        """Delete the files and rows of everything currently marked deleted.

        Wheels go first and libraries second: the foreign key cascades, so dropping a
        library while a wheel it could not reap is still stored would take that row
        with it and strand the wheel's files for good.

        One failure does not stop the pass. What could not be reaped stays marked, so
        the next run picks it up again.
        """
        async with self.uow:
            wheels = await self.uow.wheel_repo.list_deleted()
            libraries = await self.uow.custom_library_repo.list_deleted()

        reaped_wheels = sum([await self._reap_wheel(wheel) for wheel in wheels])
        reaped_libraries = sum([await self._reap_library(library) for library in libraries])

        if reaped_wheels or reaped_libraries:
            logger.info(
                "Reaped {} of {} marked wheels and {} of {} marked custom libraries",
                reaped_wheels,
                len(wheels),
                reaped_libraries,
                len(libraries),
            )

    async def _reap_wheel(self, wheel: Wheel) -> bool:
        """Delete this wheel's files and then its row. Returns whether it is gone.

        The files go first: a row deleted before them is the one order that loses
        track of what is left in the object store.
        """
        try:
            for key in (wheel.source_key, wheel.wheel_key):
                if key is not None:
                    await self.file_storage.delete(key)
            async with self.uow:
                await self.uow.wheel_repo.remove(wheel)
                await self.uow.commit()
        except Exception:
            logger.exception("Could not reap wheel {}; it stays marked for the next pass", wheel.id)
            return False
        return True

    async def _reap_library(self, library: CustomLibrary) -> bool:
        """Delete this library's row once no wheel of it is left. Returns whether it is gone."""
        try:
            async with self.uow:
                remaining = await self.uow.wheel_repo.count_by_library(library.id)
                if remaining:
                    logger.debug(
                        "Custom library {} still has {} wheels to reap first",
                        library.id,
                        remaining,
                    )
                    return False
                await self.uow.custom_library_repo.remove(library)
                await self.uow.commit()
        except Exception:
            logger.exception(
                "Could not reap custom library {}; it stays marked for the next pass", library.id
            )
            return False
        return True
