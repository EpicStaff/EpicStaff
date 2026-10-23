"""Route guards for the execution endpoints.

Litestar runs guards in `HTTPRoute.handle` before it resolves the handler's arguments,
so a guard sees the request before its body is read or validated. A full sandbox thus
answers 503 without spending time on the body -- and a malformed body cannot turn a
"come back later" into a 400.
"""

from litestar.connection import ASGIConnection
from litestar.handlers.base import BaseRouteHandler

__all__ = ["reject_when_full"]


def reject_when_full(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    """Refuse the request when the in-flight execution cap is already reached.

    Raises:
        SandboxOverloadedError: Rendered as 503 with `Retry-After`.
    """
    connection.app.state.job_intake.intake_gate.check_capacity()
