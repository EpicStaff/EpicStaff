import abc
from contextlib import AbstractAsyncContextManager

from domain.ports.repositories import (
    AbstractBindingRepository,
    AbstractConversationRepository,
    AbstractEventRepository,
    AbstractMessageRepository,
    AbstractOperatorAliasRepository,
    AbstractOperatorProfileRepository,
    AbstractReceiptRepository,
    AbstractUsageRepository,
    AbstractVisitorNumberRepository,
    AbstractVisitorTokenRepository,
)


class AbstractUnitOfWork(AbstractAsyncContextManager, abc.ABC):
    """One transaction; repositories share its session."""

    bindings: AbstractBindingRepository
    conversations: AbstractConversationRepository
    visitor_tokens: AbstractVisitorTokenRepository
    messages: AbstractMessageRepository
    events: AbstractEventRepository
    usage: AbstractUsageRepository
    receipts: AbstractReceiptRepository
    visitor_numbers: AbstractVisitorNumberRepository
    operator_profiles: AbstractOperatorProfileRepository
    operator_aliases: AbstractOperatorAliasRepository

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.rollback()

    @abc.abstractmethod
    async def rollback(self): ...

    @abc.abstractmethod
    async def commit(self): ...
