import abc
import asyncio
from typing import Any

from database.unit_of_work import AbstractUnitOfWork
from errors import RepositoryError
from loguru import logger


class AbstractOrchestrator[TRequest, TResponse](abc.ABC):
    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow
        self.state: dict[str, Any] = {}

    async def execute(self, request: TRequest) -> TResponse:
        try:
            return await self.on_execute(request)
        except asyncio.CancelledError:
            logger.info("{} cancelled for request {}.", type(self).__name__, request)
            await asyncio.shield(self.on_cancel(request))
        except RepositoryError as e:
            logger.error("{} failed during DB access: {}", type(self).__name__, e)
            raise
        except Exception as e:
            logger.error("{} failed during execution: {}", type(self).__name__, e)
            await asyncio.shield(self.on_error(request, e))
            raise

    @abc.abstractmethod
    async def on_execute(self, request: TRequest) -> TResponse:
        pass

    async def on_cancel(self, request: TRequest):
        pass

    async def on_error(self, request: TRequest, error: Exception):
        pass
