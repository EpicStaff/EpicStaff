from collections.abc import Callable

from application.orchestrators.bindings import BindingOrchestrator
from application.orchestrators.budgets import BindingLimits
from application.orchestrators.conversation import (
    ConversationOrchestrator,
    PublicLimits,
    RunConfig,
)
from application.orchestrators.identity import Operator
from application.orchestrators.operators import OperatorOrchestrator
from application.orchestrators.retention import RetentionOrchestrator
from application.orchestrators.streams import StreamOrchestrator
from application.ports import AbstractTickets
from infrastructure.database.unit_of_work import SQLAlchemyUnitOfWork
from litestar import Request
from litestar.datastructures import State
from litestar.di import Provide

__all__ = ["get_dependencies", "register"]

_dependencies: dict[str, Provide] = {}


def get_dependencies() -> dict[str, Provide]:
    return _dependencies


def register(fn: Callable | None = None, /, use_cache=False, sync_to_thread: bool | None = False):
    def decorator(func: Callable):
        _dependencies[func.__name__] = Provide(
            func, use_cache=use_cache, sync_to_thread=sync_to_thread
        )
        return func

    return decorator if fn is None else decorator(fn)


@register
def uow_factory(state: State):
    return lambda: SQLAlchemyUnitOfWork(state.session_factory)


@register
def public_limits(state: State) -> PublicLimits:
    settings = state.settings
    return PublicLimits(
        action_max_bytes=settings.CHAT_ACTION_MAX_BYTES,
        extra_data_max_bytes=settings.CHAT_EXTRA_DATA_MAX_BYTES,
    )


@register
def conversations(state: State) -> ConversationOrchestrator:
    settings = state.settings
    return ConversationOrchestrator(
        lambda: SQLAlchemyUnitOfWork(state.session_factory),
        flows=state.django,
        fanout=state.fanout,
        limiter=state.limiter,
        config=RunConfig(
            callback_url=settings.CHAT_CALLBACK_URL,
            ip_message_rate=settings.CHAT_IP_MESSAGE_RATE,
            ip_conversation_rate=settings.CHAT_IP_CONVERSATION_RATE,
        ),
        visitor_token_idle_seconds=settings.CHAT_VISITOR_TOKEN_IDLE_TTL,
    )


@register
def operator(request: Request) -> Operator:
    return request.state.operator


@register
def bindings(state: State) -> BindingOrchestrator:
    settings = state.settings
    return BindingOrchestrator(
        lambda: SQLAlchemyUnitOfWork(state.session_factory),
        flows=state.django,
        public_base_url=settings.CHAT_PUBLIC_BASE_URL,
        widget_url=settings.CHAT_WIDGET_URL,
        limits=BindingLimits(
            deployment_defaults={
                "token_budget_per_conversation": settings.CHAT_CONVERSATION_TOKEN_BUDGET_DEFAULT,
                "daily_token_budget": settings.CHAT_DAILY_TOKEN_BUDGET_DEFAULT,
                "response_time_seconds": settings.CHAT_RESPONSE_TIME_DEFAULT,
                "close_after_seconds": settings.CHAT_CLOSE_AFTER_DEFAULT,
            },
            caps={
                "token_budget_per_conversation": settings.CHAT_CONVERSATION_TOKEN_BUDGET_MAX,
                "daily_token_budget": settings.CHAT_DAILY_TOKEN_BUDGET_MAX,
                "response_time_seconds": settings.CHAT_RESPONSE_TIME_MAX,
                "close_after_seconds": settings.CHAT_CLOSE_AFTER_MAX,
            },
        ),
    )


@register
def operators(state: State) -> OperatorOrchestrator:
    return OperatorOrchestrator(
        lambda: SQLAlchemyUnitOfWork(state.session_factory), flows=state.django, fanout=state.fanout
    )


@register
def retention(state: State) -> RetentionOrchestrator:
    return RetentionOrchestrator(lambda: SQLAlchemyUnitOfWork(state.session_factory))


@register
def streams(state: State) -> StreamOrchestrator:
    settings = state.settings
    return StreamOrchestrator(
        lambda: SQLAlchemyUnitOfWork(state.session_factory),
        fanout=state.fanout,
        limiter=state.limiter,
        ping_seconds=settings.CHAT_STREAM_PING_INTERVAL,
        max_seconds=settings.CHAT_STREAM_MAX_LIFETIME,
    )


@register
def tickets(state: State) -> AbstractTickets:
    return state.tickets
