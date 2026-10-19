from domain.errors import ForbiddenError
from litestar.connection import ASGIConnection
from litestar.handlers.base import BaseRouteHandler

from presentation.rest.request_context import bearer_token


async def chats_guard(connection: ASGIConnection, route_handler: BaseRouteHandler) -> None:
    """Resolve the operator and require the `chats` action named in the handler's `opt`; a tuple
    names alternatives, any one of which is enough."""
    required = route_handler.opt["chats_action"]
    actions = (required,) if isinstance(required, str) else required
    operator = await connection.app.state.identity.resolve(
        bearer_token(connection), connection.headers.get("x-organization-id")
    )
    if not operator.allows_any(actions):
        raise ForbiddenError(" or ".join(f"chats:{action}" for action in actions) + " is required.")
    connection.state.operator = operator
