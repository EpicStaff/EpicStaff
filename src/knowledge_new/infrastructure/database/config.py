from settings import settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

__all__ = ["BaseModel", "SessionLocal", "engine"]


engine = create_async_engine(url=settings.DATABASE_DNS, echo=False, pool_pre_ping=True)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


class BaseModel(DeclarativeBase):
    pass
