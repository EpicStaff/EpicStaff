from typing import Protocol, Self, cast

from piccolo.engine import Engine, engine_finder

from manager.application.ports import AbstractUnitOfWork
from manager.domain.ports import AbstractVenvRepository
from manager.infrastructure.database.venvs.repository import PiccoloVenvRepository


class Transaction(Protocol):
    """Transaction shape the UoW depends on.

    Piccolo's `BaseTransaction` only declares the async context methods, not
    `commit`/`rollback`, so the needed shape is stated here and stays
    engine-agnostic across Piccolo backends.
    """

    async def __aenter__(self) -> object: ...
    async def __aexit__(self, exc_type, exc_value, traceback) -> object: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class PiccoloUnitOfWork(AbstractUnitOfWork):
    """Transaction scope over the Piccolo engine.

    A fresh transaction is opened on each `__aenter__`, so a single instance is
    reusable across many blocks. Piccolo binds the active transaction to the
    current async context, so the repositories' queries join it automatically.
    Per the domain contract, the transaction rolls back on exit unless `commit`
    was called explicitly.
    """

    def __init__(self, engine: Engine | None = None):
        resolved_engine = engine or engine_finder()
        if resolved_engine is None:
            raise RuntimeError("Requires a configured engine.")
        self._engine: Engine = resolved_engine
        self._transaction: Transaction | None = None
        self._venv_repo: AbstractVenvRepository | None = None
        self._committed = False

    async def __aenter__(self) -> Self:
        self._transaction = cast(Transaction, self._engine.transaction())
        await self._transaction.__aenter__()
        self._committed = False
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        # Default is rollback; only an explicit commit persists. Rolling back an
        # already-committed asyncpg transaction raises, so guard on the flag.
        if not self._committed:
            await self.rollback()
        await self.transaction.__aexit__(exc_type, exc_value, traceback)
        self._transaction = None
        self._venv_repo = None
        self._committed = False

    async def commit(self):
        await self.transaction.commit()
        self._committed = True

    async def rollback(self):
        await self.transaction.rollback()

    @property
    def transaction(self) -> Transaction:
        if self._transaction is None:
            raise RuntimeError("UnitOfWork used outside its context manager.")
        return self._transaction

    @property
    def venv_repo(self) -> AbstractVenvRepository:
        if self._venv_repo is None:
            self._venv_repo = PiccoloVenvRepository()
        return self._venv_repo
