import abc
import asyncio
from typing import Any

from application.ports.unit_of_work import AbstractUnitOfWork
from domain.errors import RepositoryError
from loguru import logger


class AbstractOrchestrator[TCommand, TResult](abc.ABC):
    def __init__(self, uow: AbstractUnitOfWork):
        self.uow = uow
        self.state: dict[str, Any] = {}

    async def execute(self, command: TCommand) -> TResult:
        try:
            return await self.on_execute(command)
        except asyncio.CancelledError:
            logger.info("{} cancelled for command {}.", type(self).__name__, command)
            await asyncio.shield(self.on_cancel(command))
        except RepositoryError as e:
            logger.exception("{} failed during DB access: {}", type(self).__name__, e)
            raise
        except Exception as e:
            logger.exception("{} failed during execution: {}", type(self).__name__, e)
            await asyncio.shield(self.on_error(command, e))
            raise

    @abc.abstractmethod
    async def on_execute(self, command: TCommand) -> TResult:
        pass

    async def on_cancel(self, command: TCommand):
        pass

    async def on_error(self, command: TCommand, error: Exception):
        pass
