from foundation.schemas import ErrorResponseSchema
from litestar import Controller, delete, get, patch, post, status_codes
from litestar.openapi.datastructures import ResponseSpec
from litestar.params import Parameter
from loguru import logger
from src.shared.bench_log import BENCH_LEVEL

from manager.application.orchestrators import JobOrchestrator, VenvCRUDOrchestrator
from manager.application.ports import AbstractUnitOfWork
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
