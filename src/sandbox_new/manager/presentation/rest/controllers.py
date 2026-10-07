from litestar import Controller, delete, get, patch, post, status_codes
from litestar.datastructures import State

from manager.application.orchestrators import JobOrchestrator, VenvCRUDOrchestrator
from manager.application.ports import AbstractUnitOfWork
from manager.presentation.rest import schemas


class VenvController(Controller):
    path: str = "/venvs"

    @get()
    async def list(self, uow: AbstractUnitOfWork) -> schemas.VenvListSchema:
        orchestrator = VenvCRUDOrchestrator(uow)
        objs = await orchestrator.list()
        return schemas.VenvListSchema(
            objects=[schemas.VenvRetrieveSchema.model_validate(o) for o in objs]
        )

    @get(path="/{id:int}")
    async def retrieve(self, id: int, uow: AbstractUnitOfWork) -> schemas.VenvRetrieveSchema:
        orchestrator = VenvCRUDOrchestrator(uow)
        obj = await orchestrator.retrieve(id)
        return schemas.VenvRetrieveSchema.model_validate(obj)

    @post(status_code=status_codes.HTTP_201_CREATED)
    async def create(
        self, data: schemas.VenvCreateSchema, uow: AbstractUnitOfWork
    ) -> schemas.VenvRetrieveSchema:
        orchestrator = VenvCRUDOrchestrator(uow)
        obj = await orchestrator.create(data.name, data.libs)
        return schemas.VenvRetrieveSchema.model_validate(obj)

    @patch(path="/{id:int}")
    async def update(
        self, id: int, data: schemas.VenvUpdateSchema, uow: AbstractUnitOfWork
    ) -> schemas.VenvRetrieveSchema:
        orchestrator = VenvCRUDOrchestrator(uow)
        obj = await orchestrator.update(id, data.name, data.libs)
        return schemas.VenvRetrieveSchema.model_validate(obj)

    @delete(path="/{id:int}")
    async def remove(self, id: int, uow: AbstractUnitOfWork) -> None:
        orchestrator = VenvCRUDOrchestrator(uow)
        await orchestrator.remove(id)


class ExecutionController(Controller):
    path: str = "/executions"

    @post(status_code=status_codes.HTTP_202_ACCEPTED)
    async def submit(
        self, data: schemas.ExecutionSubmitSchema, state: State, uow: AbstractUnitOfWork
    ) -> schemas.ExecutionAcceptedSchema:
        intake = state.job_intake
        orchestrator = JobOrchestrator(
            uow,
            intake.dispatcher,
            intake.holding,
            intake.failure_sink,
        )
        job = await orchestrator.submit(
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
            timeout=data.timeout,
        )
        return schemas.ExecutionAcceptedSchema(execution_id=job.execution_id, status=job.status)
