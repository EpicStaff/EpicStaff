from pathlib import PurePosixPath

from foundation.schemas import ErrorResponseSchema
from litestar import Controller, Response, delete, get, patch, post, status_codes
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import MultipartBody, Parameter
from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

from manager.application.orchestrators import (
    CustomLibraryCRUDOrchestrator,
    JobOrchestrator,
    VenvCRUDOrchestrator,
    WheelCRUDOrchestrator,
)
from manager.application.ports import AbstractFileStorage, AbstractUnitOfWork
from manager.application.registry import ExecutionRegistry
from manager.domain.enums import VenvOrder
from manager.presentation.rest import schemas
from manager.presentation.rest.guards import reject_when_full

ERROR_RESPONSES = {
    400: ResponseSpec(
        ErrorResponseSchema,
        description="The request was rejected; `errors` says what was wrong with it.",
        generate_examples=False,
    ),
    500: ResponseSpec(
        ErrorResponseSchema,
        description="The service failed to answer.",
        generate_examples=False,
    ),
}
ERROR_RESPONSES_WITH_NOT_FOUND = ERROR_RESPONSES | {
    404: ResponseSpec(
        ErrorResponseSchema,
        description="No venv with this id.",
        generate_examples=False,
    ),
}
SUBMIT_RESPONSES = ERROR_RESPONSES_WITH_NOT_FOUND | {
    503: ResponseSpec(
        ErrorResponseSchema,
        description=(
            "The sandbox is full, the job would wait in its queue longer than the "
            "queue timeout, or its venv is still building and the sandbox already holds "
            "as many jobs as it may. Nothing was accepted; re-post the same body after the "
            "`Retry-After` seconds."
        ),
        generate_examples=False,
    ),
}
STATUS_RESPONSES = ERROR_RESPONSES | {
    404: ResponseSpec(
        ErrorResponseSchema,
        description=(
            "The sandbox does not know this execution: it was never accepted, the "
            "sandbox restarted, or its result went out more than a minute ago."
        ),
        generate_examples=False,
    ),
}


def error_responses(*, not_found: str | None = None, conflict: str | None = None) -> dict:
    """The error answers to document on one handler, on top of the two every handler has.

    Each description is the handler's own: what is missing and what clashes differ per
    route, and a shared wording would document the wrong resource.
    """
    responses = dict(ERROR_RESPONSES)
    for status_code, description in ((404, not_found), (409, conflict)):
        if description is not None:
            responses[status_code] = ResponseSpec(
                ErrorResponseSchema, description=description, generate_examples=False
            )
    return responses


class VenvController(Controller):
    path: str = "/venvs"

    @get(
        summary="List virtual environments",
        description=(
            "Returns one page of venvs together with the total number matching the "
            "filters. `count` is that total, counted after `ids` and `search` have "
            "narrowed the result but before `limit` and `offset` are applied, so it "
            "does not shrink as you page through the result."
        ),
        response_description="A page of venvs and the total before paging.",
        responses=ERROR_RESPONSES,
    )
    async def list(
        self,
        uow: AbstractUnitOfWork,
        ids: list[int] | None = Parameter(
            default=None,
            description="Restrict the result to these venv ids. Omit to list every venv.",
        ),
        search: str | None = Parameter(
            default=None,
            description=(
                "Keep the venvs whose name contains this text, ignoring case. The text is "
                "matched literally, so `%` and `_` are those characters, not wildcards."
            ),
        ),
        order: VenvOrder = Parameter(
            default=VenvOrder.DEFAULT,
            description="How to sort the venvs before they are paged.",
        ),
        limit: int | None = Parameter(default=None, description="Maximum venvs to return."),
        offset: int | None = Parameter(default=None, description="Venvs to skip before the page."),
    ) -> schemas.VenvListSchema:
        """Return a page of venvs."""
        orchestrator = VenvCRUDOrchestrator(uow)
        objs, count = await orchestrator.list(
            ids=ids,
            name_contains=search.strip() if search else None,
            order=order,
            limit=limit,
            offset=offset,
        )
        return schemas.VenvListSchema(
            count=count,
            limit=limit or 0,
            offset=offset or 0,
            result=[schemas.VenvRetrieveSchema.from_domain(o) for o in objs],
        )

    @get(
        path="/{id:int}",
        summary="Retrieve a virtual environment",
        description=(
            "Returns one venv with its declared libraries and the state of its build. "
            "While a build is running the libraries carry no resolved `version` yet, and "
            "`error` holds the reason once a build has failed."
        ),
        response_description="The venv.",
        responses=ERROR_RESPONSES_WITH_NOT_FOUND,
    )
    async def retrieve(self, id: int, uow: AbstractUnitOfWork) -> schemas.VenvRetrieveSchema:
        """Return one venv.

        Raises:
            VenvNotFoundError: No venv with this id, rendered as 404.
        """
        orchestrator = VenvCRUDOrchestrator(uow)
        obj = await orchestrator.retrieve(id)
        return schemas.VenvRetrieveSchema.from_domain(obj)

    @post(
        status_code=status_codes.HTTP_201_CREATED,
        summary="Declare a virtual environment",
        description=(
            "Records a venv and the libraries it needs, then returns right away in "
            "`declared` status -- a background builder installs the libraries after the "
            "response. `status`, `error` and each library's resolved `version` only "
            "settle once that build finishes, so poll the venv to follow it.\n\n"
            "A library may declare a `specification` range, an exact `version`, or both; "
            "a version outside its own specification is rejected. Giving a `version` pins "
            "it, otherwise the resolver picks a release inside the range and writes back "
            "what it installed."
        ),
        response_description="The stored venv, declared but not yet built.",
        responses=ERROR_RESPONSES,
    )
    async def create(
        self, data: schemas.VenvCreateSchema, uow: AbstractUnitOfWork
    ) -> schemas.VenvRetrieveSchema:
        """Store a new venv in `declared` status.

        Raises:
            pydantic.ValidationError: A library breaks an invariant of the domain model,
                such as a version outside its specification. Rendered as 400.
        """
        orchestrator = VenvCRUDOrchestrator(uow)
        obj = await orchestrator.create(data.name, [lib.to_domain() for lib in data.libs])
        return schemas.VenvRetrieveSchema.from_domain(obj)

    @patch(
        path="/{id:int}",
        summary="Change a virtual environment",
        description=(
            "Applies the fields present in the body and leaves the rest untouched. "
            "Sending `libs` replaces the whole library list -- it is not merged -- and "
            "returns the venv to `declared` status, which has the background builder "
            "rebuild it. Omitting `libs` keeps both the libraries and the build state, "
            "so renaming a built venv does not rebuild it."
        ),
        response_description="The venv as stored after the change.",
        responses=ERROR_RESPONSES_WITH_NOT_FOUND,
    )
    async def update(
        self, id: int, data: schemas.VenvUpdateSchema, uow: AbstractUnitOfWork
    ) -> schemas.VenvRetrieveSchema:
        """Apply a partial change to a venv.

        Raises:
            VenvNotFoundError: No venv with this id, rendered as 404.
        """
        orchestrator = VenvCRUDOrchestrator(uow)
        libs = None if data.libs is None else [lib.to_domain() for lib in data.libs]
        obj = await orchestrator.update(id, data.name, libs)
        return schemas.VenvRetrieveSchema.from_domain(obj)

    @delete(
        path="/{id:int}",
        summary="Delete a virtual environment",
        description=(
            "Removes the venv. The built environment on disk outlives the call: a "
            "housekeeping task deletes directories no venv refers to any more, so the "
            "space comes back a little later."
        ),
        response_description="The venv was deleted.",
        responses=ERROR_RESPONSES_WITH_NOT_FOUND,
    )
    async def remove(self, id: int, uow: AbstractUnitOfWork) -> None:
        """Delete a venv, leaving its directory for the housekeeping task.

        Raises:
            VenvNotFoundError: No venv with this id, rendered as 404.
        """
        orchestrator = VenvCRUDOrchestrator(uow)
        await orchestrator.remove(id)


class ExecutionController(Controller):
    path: str = "/executions"

    @post(
        status_code=status_codes.HTTP_202_ACCEPTED,
        guards=[reject_when_full],
        summary="Submit code for execution",
        description=(
            "Accepts a submission and answers immediately with its `execution_id` and "
            "`status`. The result is not in this response: it is published out of band, "
            "and the caller correlates it by that id.\n\n"
            "What happens next depends on the venv, chosen by `venv_id` or the default "
            "one when it is omitted. A built venv has the job queued at once; a venv "
            "still building holds the job until its build finishes (a job still held "
            "when the hold timeout passes gets a failed result instead of a run); a venv "
            "whose build failed produces a failed result rather than a run. All three "
            "answer 202 -- "
            "acceptance says the submission was understood, not that the code will run.\n\n"
            "Every `secrets` value must be sealed with the transport key; one the sandbox "
            "cannot decrypt is refused with 400 naming the secret, and nothing is run.\n\n"
            "Re-posting an `execution_id` the sandbox already knows does not run it again: "
            "it answers 202 with that execution's current status.\n\n"
            "A full sandbox answers 503 with `Retry-After` instead of accepting work it "
            "could not start within its queue timeout. So does a submission that would be "
            "held while the most jobs the sandbox holds are already waiting on venv builds."
        ),
        response_description="The submission was accepted; the result arrives out of band.",
        responses=SUBMIT_RESPONSES,
    )
    async def submit(
        self, data: schemas.ExecutionSubmitSchema, job_orchestrator: JobOrchestrator
    ) -> schemas.ExecutionAcceptedSchema:
        """Accept a code submission and hand it to the job orchestrator.

        Raises:
            VenvNotFoundError: `venv_id` names no venv, or none is given and there is no
                default venv. Rendered as 404.
            SandboxOverloadedError: The sandbox cannot take the job now. Rendered as 503.
            SecretNotDecryptableError: A secret is not a transport ciphertext this
                sandbox can open. Rendered as 400.
        """
        logger.log(
            BENCH_LEVEL,
            "bench {checkpoint}",
            checkpoint="exec_received",
            session_id=data.session_id,
            execution_id=data.execution_id,
        )
        status = await job_orchestrator.submit(
            execution_id=data.execution_id,
            session_id=data.session_id,
            code=data.code,
            entrypoint=data.entrypoint,
            global_kwargs=data.global_kwargs,
            func_kwargs=data.func_kwargs,
            secrets=data.secrets,
            venv_id=data.venv_id,
            use_storage=data.use_storage,
            storage_allowed_paths=data.storage_allowed_paths,
            storage_org_prefix=data.storage_org_prefix,
            storage_credentials=(
                None if data.storage_credentials is None else data.storage_credentials.to_domain()
            ),
            timeout=data.timeout,
            reply_to_crew_channel=data.reply_to_crew_channel,
        )
        return schemas.ExecutionAcceptedSchema(execution_id=data.execution_id, status=status)

    @get(
        path="/{execution_id:str}",
        summary="Retrieve the status of an execution",
        description=(
            "Says whether the sandbox still has the execution: `held` while its venv "
            "builds, `queued` until its result is out, then `done` for one minute. After "
            "that, or after a sandbox restart, the execution is unknown and this answers "
            "404 -- a caller still waiting for its result should stop waiting."
        ),
        response_description="Where the execution is.",
        responses=STATUS_RESPONSES,
    )
    async def retrieve(
        self, execution_id: str, execution_registry: ExecutionRegistry
    ) -> schemas.ExecutionStatusSchema:
        """Return where an accepted execution is.

        Raises:
            ExecutionNotFoundError: The sandbox does not know the execution, rendered as 404.
        """
        status = execution_registry.get_status(execution_id)
        return schemas.ExecutionStatusSchema(execution_id=execution_id, status=status)


class CustomLibraryController(Controller):
    path = "/custom-libraries"

    @get(
        summary="List custom libraries",
        description=(
            "Returns one page of libraries together with the total number matching the "
            "filters. `count` is that total, counted after `ids` has narrowed the result "
            "but before `limit` and `offset` are applied, so it does not shrink as you "
            "page through the result."
        ),
        response_description="A page of libraries and the total before paging.",
        responses=error_responses(),
    )
    async def list(
        self,
        uow: AbstractUnitOfWork,
        ids: list[int] | None = Parameter(
            default=None,
            description="Restrict the result to these library ids. Omit to list every one.",
        ),
        limit: int | None = Parameter(default=None, description="Maximum libraries to return."),
        offset: int | None = Parameter(
            default=None, description="Libraries to skip before the page."
        ),
    ) -> schemas.CustomLibraryListSchema:
        """Return a page of custom libraries."""
        orchestrator = CustomLibraryCRUDOrchestrator(uow)
        pairs, count = await orchestrator.list(ids, limit, offset)
        return schemas.CustomLibraryListSchema(
            count=count,
            limit=limit or 0,
            offset=offset or 0,
            result=[
                schemas.CustomLibraryRetrieveSchema.from_domain(o, wheels) for o, wheels in pairs
            ],
        )

    @get(
        path="/{id:int}",
        summary="Retrieve a custom library",
        description=(
            "Returns one library. Its versions are not embedded; they are listed under "
            "this library's `wheels` path."
        ),
        response_description="The library.",
        responses=error_responses(not_found="No custom library with this id."),
    )
    async def retrieve(
        self, id: int, uow: AbstractUnitOfWork
    ) -> schemas.CustomLibraryRetrieveSchema:
        """Return one custom library.

        Raises:
            CustomLibraryNotFoundError: No library with this id, rendered as 404.
        """
        orchestrator = CustomLibraryCRUDOrchestrator(uow)
        obj, wheels = await orchestrator.retrieve(id)
        return schemas.CustomLibraryRetrieveSchema.from_domain(obj, wheels)

    @post(
        status_code=status_codes.HTTP_201_CREATED,
        summary="Create a custom library",
        description=(
            "Creates a library from its first version: a wheel, or a source archive to "
            "build into one. No name is ever typed; a wheel names the library at once, "
            "the way a package index would spell it -- `My_Library` and `my.library` "
            "both store as `my-library` -- while a source archive's distribution is not "
            "known until it builds, so the library is created unnamed and takes the name "
            "its first successful build produces. Either way the name, once set, cannot "
            "be changed afterwards."
        ),
        response_description=(
            "The stored library, with its first version uploaded. `name` is null when "
            "it was created from a source archive still waiting to build."
        ),
        responses=error_responses(conflict="A library with this name already exists."),
    )
    async def create(
        self,
        data: MultipartBody[schemas.CustomLibraryCreateSchema],
        uow: AbstractUnitOfWork,
        file_storage: AbstractFileStorage,
    ) -> schemas.CustomLibraryRetrieveSchema:
        """Store a new custom library, from the wheel or the source archive that
        creates it.

        Raises:
            pydantic.ValidationError: The upload is not a wheel or a source archive.
                Rendered as 400.
            UnsupportedUploadError: The filename ends in a wheel's suffix but does not
                parse as one. Rendered as 400.
            CustomLibraryNameTakenError: A wheel's name is already another library's,
                rendered as 409.
        """
        filename = PurePosixPath(data.file.filename or "").name
        library_orchestrator = CustomLibraryCRUDOrchestrator(uow)
        obj = await library_orchestrator.create_for(filename)
        try:
            wheel = await WheelCRUDOrchestrator(uow, file_storage).upload(
                library_id=obj.id, file=data.file
            )
        except Exception:
            # The library was just created and nothing could name it yet, so removing
            # it here is safe and frees the name for the next attempt.
            await library_orchestrator.remove(obj.id)
            raise
        # The library was created for this upload, so its one version is the whole
        # state of it; nothing is read back to work that out.
        return schemas.CustomLibraryRetrieveSchema.from_domain(obj, [wheel])

    @delete(
        path="/{id:int}",
        summary="Delete a custom library",
        description=(
            "Removes the library and every version of it. Both stop answering at once "
            "and the name is free to reuse immediately, while the uploaded and built "
            "files outlive the call: a housekeeping task deletes them and then the rows, "
            "so the space comes back a little later."
        ),
        response_description="The library was deleted.",
        responses=error_responses(not_found="No custom library with this id."),
    )
    async def remove(self, id: int, uow: AbstractUnitOfWork) -> None:
        """Delete a custom library and its versions, leaving the files for housekeeping.

        Raises:
            CustomLibraryNotFoundError: No library with this id, rendered as 404.
        """
        orchestrator = CustomLibraryCRUDOrchestrator(uow)
        await orchestrator.remove(id=id)


class WheelController(Controller):
    """Versions of one custom library.

    A version is uploaded either as a built wheel, which arrives finished, or as a
    source archive, which a background build turns into one. Its `status` says which
    stage it is at, and only a `completed` version has a file to download.
    """

    path = "/custom-libraries/{library_id:int}/wheels"

    @get(
        summary="List the versions of a custom library",
        description=(
            "Returns every version of this library, oldest first. Not paged: a library "
            "holds few versions, and a client following a build needs all of them."
        ),
        response_description="The library's versions.",
        responses=error_responses(),
    )
    async def list(
        self, library_id: int, uow: AbstractUnitOfWork, file_storage: AbstractFileStorage
    ) -> list[schemas.WheelRetrieveSchema]:
        """Return every version of one custom library."""
        orchestrator = WheelCRUDOrchestrator(uow, file_storage)
        objs = await orchestrator.list(library_id)
        return [schemas.WheelRetrieveSchema.from_domain(obj) for obj in objs]

    @get(
        path="/{id:int}",
        summary="Retrieve one version",
        description=(
            "Returns one version and the state of its build. A source archive carries no "
            "`version` until the build resolves one, and `error` holds the reason once an "
            "upload or a build has failed, so poll this to follow one."
        ),
        response_description="The version.",
        responses=error_responses(not_found="No version with this id in this library."),
    )
    async def retrieve(
        self,
        library_id: int,
        id: int,
        uow: AbstractUnitOfWork,
        file_storage: AbstractFileStorage,
    ) -> schemas.WheelRetrieveSchema:
        """Return one version.

        Raises:
            WheelNotFoundError: No version with this id in this library, rendered as 404.
        """
        orchestrator = WheelCRUDOrchestrator(uow, file_storage)
        obj = await orchestrator.retrieve(library_id, id)
        return schemas.WheelRetrieveSchema.from_domain(obj)

    @get(
        path="/{id:int}/file",
        media_type="application/octet-stream",
        summary="Download the wheel of one version",
        description=(
            "Returns the wheel itself, named the way it is stored. Only a `completed` "
            "version has one: a version still building, or one whose build failed, "
            "answers 409 rather than an empty body."
        ),
        response_description="The wheel.",
        responses=error_responses(
            not_found="No version with this id in this library.",
            conflict="This version has no wheel file; its status says why.",
        ),
    )
    async def download(
        self,
        library_id: int,
        id: int,
        uow: AbstractUnitOfWork,
        file_storage: AbstractFileStorage,
    ) -> Response[bytes]:
        """Return the wheel's bytes as a download.

        Raises:
            WheelNotFoundError: No version with this id in this library, rendered as 404.
            WheelNotBuiltError: This version has no wheel file, rendered as 409.
        """
        orchestrator = WheelCRUDOrchestrator(uow, file_storage)
        content, filename = await orchestrator.download_wheel(library_id, id)
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"content-disposition": f'attachment; filename="{filename}"'},
        )

    @post(
        status_code=status_codes.HTTP_201_CREATED,
        summary="Upload a new version",
        description=(
            "Takes one file: a built wheel (`.whl`), or a source archive (`.tar.gz`, "
            "`.tgz`, `.zip`) to build one from. A wheel is stored as `completed` right "
            "away; an archive is stored as `declared` and a background builder picks it "
            "up, so poll the version to follow it.\n\n"
            "The distribution the file is for must be this library: an uploaded wheel is "
            "checked against the library's name on arrival, and a source archive after "
            "its build, because only then is the name it builds known. Neither a version "
            "this library already has nor a file it already holds is accepted twice -- "
            "sameness is decided by content, not by filename -- so replacing a published "
            "version means deleting it and uploading again."
        ),
        response_description="The stored version.",
        responses=error_responses(
            not_found="No custom library with this id.",
            conflict="This library already holds this version, or this exact file.",
        ),
    )
    async def upload(
        self,
        library_id: int,
        data: MultipartBody[schemas.WheelUploadSchema],
        uow: AbstractUnitOfWork,
        file_storage: AbstractFileStorage,
    ) -> schemas.WheelRetrieveSchema:
        """Store an uploaded wheel or source archive as a new version.

        Raises:
            CustomLibraryNotFoundError: No library with this id, rendered as 404.
            UnsupportedUploadError: Not a wheel or a source archive, rendered as 400.
            WheelNameMismatchError: A wheel for another distribution, rendered as 400.
            WheelSourceAlreadyUploadedError: This exact file is already here, as 409.
            WheelVersionTakenError: This library already has that version, as 409.
        """
        orchestrator = WheelCRUDOrchestrator(uow, file_storage)
        obj = await orchestrator.upload(library_id=library_id, file=data.file)
        return schemas.WheelRetrieveSchema.from_domain(obj)

    @delete(
        path="/{id:int}",
        summary="Delete one version",
        description=(
            "Removes the version. It stops answering at once and frees both its version "
            "number and its file for re-upload, while the stored files outlive the call: "
            "a housekeeping task deletes them and then the row."
        ),
        response_description="The version was deleted.",
        responses=error_responses(not_found="No version with this id in this library."),
    )
    async def remove(
        self,
        library_id: int,
        id: int,
        uow: AbstractUnitOfWork,
        file_storage: AbstractFileStorage,
    ) -> None:
        """Mark one version deleted, leaving its files for housekeeping.

        Raises:
            WheelNotFoundError: No version with this id in this library, rendered as 404.
        """
        orchestrator = WheelCRUDOrchestrator(uow, file_storage)
        await orchestrator.remove(library_id=library_id, id=id)
