from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

__all__ = ["Base", "make_engine", "make_session_factory"]


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    # Without hide_parameters a failed statement's error quotes its bound values (message text,
    # a desk's identity secret), and that error reaches the log.
    return create_async_engine(url, echo=False, pool_pre_ping=True, hide_parameters=True)


def make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
