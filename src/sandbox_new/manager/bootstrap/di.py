from foundation.utils.litestar import di
from litestar.datastructures import State

from manager.application.ports import AbstractFileStorage, AbstractUnitOfWork
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork


@di.register
async def uow() -> AbstractUnitOfWork:
    return PiccoloUnitOfWork()


@di.register
async def file_storage(state: State) -> AbstractFileStorage:
    return state.custom_library_storage
