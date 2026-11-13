"""Route guards for the execution endpoints.

Litestar runs guards in `HTTPRoute.handle` before it resolves the handler's arguments,
so a guard sees the request before its body is read or validated. A full sandbox thus
answers 503 without spending time on the body -- and a malformed body cannot turn a
"come back later" into a 400.
"""

import hmac

from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.handlers.base import BaseRouteHandler

from manager import settings

__all__ = ["reject_when_full", "verify_internal_token"]


def reject_when_full(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Refuse the request when the in-flight execution cap is already reached.

    Raises:
        SandboxOverloadedError: Rendered as 503 with `Retry-After`.
    """
    connection.app.state.intake_gate.check_capacity()


def verify_internal_token(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Refuse the request unless it carries the manager/worker shared secret.

    The internal endpoints hand out job payloads with plaintext secrets, so they must
    never answer a caller that merely reached the port. Compared in constant time.

    Raises:
        NotAuthorizedException: Rendered as 401.
    """
    expected = f"Bearer {settings.INTERNAL_TOKEN}"
    provided = connection.headers.get("Authorization", "")
    if not hmac.compare_digest(provided.encode(), expected.encode()):
        raise NotAuthorizedException("Missing or wrong internal token.")
