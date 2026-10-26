"""The plugin side of EpicStaff's gateway: verifying the context of every request."""

from epicstaff_plugin.gateway.asgi_middleware import EpicStaffContextMiddleware
from epicstaff_plugin.gateway.context_verifier import ContextRejected, ContextVerifier
from epicstaff_plugin.gateway.scope import ContextUnavailableError, context_from_scope

__all__ = [
    "ContextRejected",
    "ContextUnavailableError",
    "ContextVerifier",
    "EpicStaffContextMiddleware",
    "context_from_scope",
]
