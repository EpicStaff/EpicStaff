import hmac

from domain.errors import ForbiddenError, InvalidInternalKeyError
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


INTERNAL_API_KEY_HEADER = "X-Internal-Api-Key"


async def internal_api_key_guard(
    connection: ASGIConnection, route_handler: BaseRouteHandler
) -> None:
    """Require CHAT_INTERNAL_API_KEY in `X-Internal-Api-Key`, compared in constant time.

    A guard runs before the body is read, so a caller without the key learns nothing about how
    the endpoint validates its input.
    """
    presented = connection.headers.get(INTERNAL_API_KEY_HEADER, "")
    expected = connection.app.state.settings.CHAT_INTERNAL_API_KEY
    # As bytes: compare_digest raises TypeError on a non-ASCII str instead of returning False.
    if not hmac.compare_digest(presented.encode(), expected.encode()):
        raise InvalidInternalKeyError()
