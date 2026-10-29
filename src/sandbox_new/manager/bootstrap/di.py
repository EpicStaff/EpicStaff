from foundation.utils.litestar import di

from manager.application.ports import AbstractUnitOfWork
from manager.infrastructure.database.unit_of_work import PiccoloUnitOfWork


@di.register
async def uow() -> AbstractUnitOfWork:
    return PiccoloUnitOfWork()
