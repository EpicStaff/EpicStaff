import asyncio

from alembic import context
from infrastructure.database.config import Base
from infrastructure.database.models import *
from sqlalchemy.ext.asyncio import create_async_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    configured = config.get_main_option("sqlalchemy.url")
    if configured:
        return configured
    from settings import load_settings

    return load_settings().database_url


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection) -> None:
    # One transaction per file: a migration with an autocommit block (CREATE INDEX CONCURRENTLY)
    # commits whatever ran before it, so no run should span several files in one transaction.
    context.configure(
        connection=connection, target_metadata=target_metadata, transaction_per_migration=True
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
