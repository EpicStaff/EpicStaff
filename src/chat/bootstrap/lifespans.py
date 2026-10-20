import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Literal

import redis.asyncio as redis_asyncio
from application.orchestrators.identity import OperatorIdentity
from application.orchestrators.lifecycle import LifecycleTimers
from application.orchestrators.reconcile import Reconciler
from common.utils import utcnow
from infrastructure.database.config import make_engine, make_session_factory
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from infrastructure.django.client import DjangoClient
from infrastructure.redis.counters import RedisRateLimiter
from infrastructure.redis.fanout import RedisFanout
from infrastructure.redis.tickets import RedisTickets
from litestar import Litestar
from loguru import logger

from bootstrap.di import conversations as build_conversations

__all__ = ["get_lifespans", "on_shutdown", "on_startup"]

_lifespans: dict[Literal["on_startup", "on_shutdown"], list[Callable]] = defaultdict(list)


def get_lifespans(type: Literal["on_startup", "on_shutdown"], /) -> list[Callable]:
    return _lifespans[type]


def on_startup(fn: Callable):
    _lifespans["on_startup"].append(fn)
    return fn


def on_shutdown(fn: Callable):
    _lifespans["on_shutdown"].append(fn)
    return fn


@on_startup
async def init_database(app: Litestar) -> None:
    app.state.engine = make_engine(app.state.settings.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)


@on_startup
async def init_clients(app: Litestar) -> None:
    settings = app.state.settings
    if app.state.get("redis") is None:
        app.state.redis = redis_asyncio.from_url(settings.redis_url)
    app.state.django = DjangoClient(settings, transport=app.state.get("django_transport"))
    app.state.fanout = RedisFanout(app.state.redis)
    app.state.limiter = RedisRateLimiter(app.state.redis)
    app.state.tickets = RedisTickets(app.state.redis, settings.CHAT_TICKET_TTL)
    app.state.identity = OperatorIdentity(app.state.django, settings.CHAT_IDENTITY_CACHE_TTL)


async def _reconcile_forever(app: Litestar) -> None:
    settings = app.state.settings

    def uow_factory():
        return SQLAlchemyUnitOfWork(app.state.session_factory)

    reconciler = Reconciler(
        uow_factory,
        conversations=build_conversations(app.state),
        flows=app.state.django,
        timers=LifecycleTimers(uow_factory, fanout=app.state.fanout),
        stale_after_seconds=settings.CHAT_STALE_RUN_AFTER,
        unconfirmed_start_release_seconds=settings.CHAT_UNCONFIRMED_START_RELEASE,
        run_timeout_seconds=settings.CHAT_RUN_TIMEOUT,
        retention_seconds=settings.CHAT_EVENT_RETENTION,
        visitor_token_idle_seconds=settings.CHAT_VISITOR_TOKEN_IDLE_TTL,
    )
    while True:
        await asyncio.sleep(settings.CHAT_RECONCILE_INTERVAL)
        try:
            await reconciler.run_once(utcnow())
        except Exception as error:  # the loop outlives any single failure
            logger.error("Reconcile pass failed: {}", error)


# Registered after init_database and init_clients: Litestar runs on_startup in list order.
@on_startup
async def start_reconcile(app: Litestar) -> None:
    app.state.reconcile_task = None
    if app.state.settings.CHAT_RECONCILE_INTERVAL > 0:
        app.state.reconcile_task = asyncio.create_task(_reconcile_forever(app))


@on_shutdown
async def stop_reconcile(app: Litestar) -> None:
    task = app.state.get("reconcile_task")
    if task:
        task.cancel()


@on_shutdown
async def dispose_database(app: Litestar) -> None:
    await app.state.engine.dispose()


@on_shutdown
async def close_clients(app: Litestar) -> None:
    await app.state.django.aclose()
    await app.state.redis.aclose()
