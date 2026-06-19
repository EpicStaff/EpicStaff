from sqlalchemy.ext.asyncio import (
    create_async_engine,
    async_sessionmaker,
    AsyncSession,
)
from sqlalchemy.orm import DeclarativeBase

from settings import settings

__all__ = [
    "engine",
    "SessionLocal",
    "BaseModel",
]


engine = create_async_engine(
    url=settings.POSTGRES_DNS,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    bind=engine, expire_on_commit=False, class_=AsyncSession
)


class BaseModel(DeclarativeBase):
    pass
