from application.ports.unit_of_work import AbstractUnitOfWork
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.database.repositories import (
    BindingRepository,
    ConversationRepository,
    EventRepository,
    MessageRepository,
    OperatorAliasRepository,
    OperatorProfileRepository,
    ReceiptRepository,
    UsageRepository,
    VisitorNumberRepository,
    VisitorTokenRepository,
)


class SQLAlchemyUnitOfWork(AbstractUnitOfWork):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self):
        self._session = self._session_factory()
        self.bindings = BindingRepository(self._session)
        self.conversations = ConversationRepository(self._session)
        self.visitor_tokens = VisitorTokenRepository(self._session)
        self.messages = MessageRepository(self._session)
        self.events = EventRepository(self._session)
        self.usage = UsageRepository(self._session)
        self.receipts = ReceiptRepository(self._session)
        self.visitor_numbers = VisitorNumberRepository(self._session)
        self.operator_profiles = OperatorProfileRepository(self._session)
        self.operator_aliases = OperatorAliasRepository(self._session)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.rollback()
        await self._session.close()
        self._session = None

    async def rollback(self):
        await self._session.rollback()

    async def commit(self):
        await self._session.commit()
