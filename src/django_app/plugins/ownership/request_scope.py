"""The plugin service account behind the current request, and what it created.

Ownership and activity both need to know, deep inside a save, whether a plugin's service
account is the caller. A context variable holds one `PluginRequestScope` per request:

- the outermost wrapper creates it empty and resets it in `finally`:
  `PluginRequestScopeMiddleware` for Django's requests, `PluginRequestScopeASGI` for the
  upload stream (an ASGI app outside Django's middleware);
- `PluginServiceAccountAuthentication` fills `principal`, and creates the scope itself only
  when no wrapper did (a view called directly in a test);
- the ownership recorder appends every root it records to `created`.

Everything mutates the one scope object in place, so nothing depends on context changes
flowing back from inner code (a `sync_to_async` thread) to the wrapper. Once the response is
ready, the wrapper records the request as activity when a service account made it.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from asgiref.sync import sync_to_async
from django.conf import settings

from plugins.activity.recorder import ActivityRecorder
from plugins.identity.principals import PluginServiceAccountPrincipal


@dataclass(frozen=True)
class CreatedRoot:
    """A resource the service account created during the request."""

    model_label: str
    pk: int
    label: str | None


@dataclass
class PluginRequestScope:
    principal: PluginServiceAccountPrincipal | None = None
    created: list[CreatedRoot] = field(default_factory=list)


_current_scope: ContextVar[PluginRequestScope | None] = ContextVar(
    "plugin_request_scope", default=None
)


def current_scope() -> PluginRequestScope | None:
    return _current_scope.get()


def current_principal() -> PluginServiceAccountPrincipal | None:
    """The service account making the current request, or None for anyone else."""
    scope = _current_scope.get()
    return scope.principal if scope is not None else None


@contextmanager
def request_scope() -> Iterator[PluginRequestScope]:
    """Open an empty scope for one request, and close it whatever happens."""
    scope = PluginRequestScope()
    token = _current_scope.set(scope)
    try:
        yield scope
    finally:
        _current_scope.reset(token)


def scope_for_authentication() -> PluginRequestScope:
    """The request's scope, created here when no wrapper opened one (a view called directly)."""
    scope = _current_scope.get()
    if scope is None:
        scope = PluginRequestScope()
        _current_scope.set(scope)
    return scope


class PluginRequestScopeMiddleware:
    """Opens the scope for each Django request and records a service account's writes.

    The last entry of `MIDDLEWARE`, so the scope surrounds exactly the view. Synchronous
    only: Django runs it in the view's own thread, where the scope is visible to
    authentication and to every save. Does nothing while the plugin platform is off.
    """

    sync_capable = True
    async_capable = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not settings.PLUGINS_ENABLED:
            return self.get_response(request)
        with request_scope() as scope:
            response = self.get_response(request)
        if scope.principal is not None:
            ActivityRecorder().record_django_request(scope, request, response)
        return response


class PluginRequestScopeASGI:
    """Opens the scope around an ASGI app that bypasses Django's middleware (the upload stream).

    `resource_type` and `route` describe the app for the activity event, as a view's
    `rbac_resource_type` and URL route do for a Django request.
    """

    def __init__(self, app, *, resource_type: str, route: str):
        self._app = app
        self._resource_type = resource_type
        self._route = route

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not settings.PLUGINS_ENABLED:
            await self._app(scope, receive, send)
            return
        status_holder: dict[str, int] = {}

        async def send_noting_status(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        with request_scope() as request_scope_state:
            await self._app(scope, receive, send_noting_status)
        if request_scope_state.principal is None or "status" not in status_holder:
            return
        await sync_to_async(ActivityRecorder().record_stream_request)(
            request_scope_state,
            method=scope.get("method", ""),
            path=scope.get("path", ""),
            route=self._route,
            status=status_holder["status"],
            resource_type=self._resource_type,
        )
