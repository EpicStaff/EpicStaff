"""Where the context middleware leaves a verified context for the plugin's code."""

from collections.abc import Mapping
from typing import Any

from epicstaff_plugin.contracts.gateway_context import GatewayContext

CONTEXT_SCOPE_KEY = "epicstaff_plugin.context"


class ContextUnavailableError(LookupError):
    """The ASGI scope holds no verified context: the app runs without the context middleware."""


def context_from_scope(scope: Mapping[str, Any]) -> GatewayContext:
    """Return the verified gateway context of the request whose ASGI `scope` this is.

    With FastAPI or Starlette, pass `request.scope` (or `websocket.scope`).

    Raises:
        ContextUnavailableError: The request did not pass `EpicStaffContextMiddleware`, which
            `python -m epicstaff_plugin.serve` always puts in front of the plugin's app.
    """
    context = scope.get(CONTEXT_SCOPE_KEY)
    if not isinstance(context, GatewayContext):
        raise ContextUnavailableError(
            "this request has no EpicStaff context: serve the app with "
            "`python -m epicstaff_plugin.serve` or wrap it in EpicStaffContextMiddleware"
        )
    return context
