"""Capture layer 3: one generic record for a change no earlier layer recorded.

A successful change request (copy, import, version restore, ...) that neither a
`LastEditTracker` nor an explicit `record_user_action` call described is recorded once,
with its action (a custom DRF action keeps its name; DRF's generic ones read like the
recorder's own verbs), its route and the object its URL names. The record never reads
the request or response body.
"""

import io

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.handlers.asgi import ASGIRequest
from rbac.views.auth import (
    ApiKeyValidateView,
    CookieTokenRefreshView,
    LoginView,
    LogoutView,
    SseTicketView,
    SwaggerTokenView,
    TokenIntrospectView,
    WsTicketView,
)
from rest_framework.permissions import SAFE_METHODS
from src.shared.models import UserAction
from tables.views.audit_token_views import AuditTokenView
from utils.logger import logger
from utils.request_target import model_of, target_from_url, url_path_pattern

from user_audit.actor import actor_from_request
from user_audit.context import UserActionContext, user_action_context
from user_audit.recorder import record_for_user_orgs, record_user_action
from user_audit.targets import TARGET_NAME_FIELDS, TargetDescription, target_type

# A request answered with a status at or above this changed nothing worth recording.
FIRST_FAILURE_STATUS = 400
# Views whose writes are sessions and credentials, not changes a user made. No view
# the frontend calls on a timer writes: its polls are all GETs, and the token refresh
# is answered by CookieTokenRefreshView.
FALLBACK_EXCLUDED_VIEWS = frozenset(
    {
        # Token and ticket issuing, introspection and validation.
        CookieTokenRefreshView,
        SseTicketView,
        WsTicketView,
        TokenIntrospectView,
        ApiKeyValidateView,
        SwaggerTokenView,
        AuditTokenView,
        # Record their own signed_in, sign_in_failed and signed_out.
        LoginView,
        LogoutView,
    }
)
# Requests that act in no single org, recorded in every org the user is a member of.
ORGLESS_FAN_OUT_PATH_PREFIXES = ("/api/profile/",)
# The action recorded for a view with no DRF action name for the method.
METHOD_ACTIONS = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "destroy"}
# DRF's generic action names, recorded as the verbs the recorder's own records use, so one
# change reads the same whichever layer recorded it.
GENERIC_ACTIONS = {
    "create": UserAction.CREATED,
    "update": UserAction.UPDATED,
    "partial_update": UserAction.UPDATED,
    "destroy": UserAction.DELETED,
}


class UserActionMiddleware:
    """Opens the user-action context around each Django request, then records the request
    itself when it changed something and nothing recorded it.

    Synchronous only, like `PluginRequestScopeMiddleware` before it: Django runs it in
    the view's own thread, so the context is visible to every save the view makes.
    """

    sync_capable = True
    async_capable = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with user_action_context(request) as context:
            response = self.get_response(request)
            match = getattr(request, "resolver_match", None)
            view = getattr(match, "func", None)
            _record_unhandled_change(
                context,
                status=response.status_code,
                view_class=getattr(view, "cls", None),
                action=getattr(view, "actions", {}).get(request.method.lower()),
                route=match.route if match is not None else None,
                match=match,
            )
        return response


class UserActionASGI:
    """Opens the user-action context around an ASGI app outside Django's middleware (the
    upload stream), then records the request as `UserActionMiddleware` does.

    The app must build its request on the context's `request`, so the user and org it
    checks are the ones recorded. `view_class`, `action` and `route` describe the app as a
    resolved URL describes a view.
    """

    def __init__(self, app, *, view_class, action: str, route: str):
        self._app = app
        self._view_class = view_class
        self._action = action
        self._route = route

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        try:
            # Empty body: the app reads the real one straight from `receive`.
            request = ASGIRequest(scope, io.BytesIO())
        except UnicodeDecodeError:
            # A query string that is not UTF-8: the app refuses it before changing anything.
            await self._app(scope, receive, send)
            return
        status_holder: dict[str, int] = {}

        async def send_noting_status(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
            await send(message)

        with user_action_context(request) as context:
            await self._app(scope, receive, send_noting_status)
            if "status" in status_holder:
                await sync_to_async(_record_unhandled_change)(
                    context,
                    status=status_holder["status"],
                    view_class=self._view_class,
                    action=self._action,
                    route=self._route,
                    match=None,
                )


def _record_unhandled_change(
    context: UserActionContext, *, status: int, view_class, action: str | None, route, match
) -> None:
    """Record the request once when it changed something and nothing recorded it yet.

    Best-effort: never raises. The record goes to the org `OrgContextService` checked for
    the request; a request with no checked org is recorded only under
    `ORGLESS_FAN_OUT_PATH_PREFIXES`, in each of the user's orgs, and otherwise not at all.

    Args:
        action: The view's DRF action name for the method, if it has one.
        route: The resolved URL route, None when the request resolved to no view.
        match: The resolved URL, whose `pk` or `id` names the target.
    """
    request = context.request
    try:
        if (
            not settings.USER_AUDIT_TRAIL_ENABLED
            or request.method in SAFE_METHODS
            or status >= FIRST_FAILURE_STATUS
            or context.recorded
            or view_class in FALLBACK_EXCLUDED_VIEWS
        ):
            return
        # None for an anonymous caller and a plugin's service account.
        actor = actor_from_request(request)
        if actor is None:
            return
        action = action or METHOD_ACTIONS.get(request.method, request.method.lower())
        action = GENERIC_ACTIONS.get(action, action)
        route_text = f"{request.method} {url_path_pattern(route)}" if route is not None else None
        org_id = getattr(request, "_rbac_active_org_id", None)
        if org_id is not None:
            record_user_action(
                action=action,
                org_id=org_id,
                target_description=_url_target(view_class, match, org_id),
                route=route_text,
                actor=actor,
            )
        elif request.path.startswith(ORGLESS_FAN_OUT_PATH_PREFIXES):
            record_for_user_orgs(action=action, actor=actor, route=route_text)
    except Exception:
        logger.exception("Failed to record {} {} as a user action", request.method, request.path)


def _url_target(view_class, match, org_id: int) -> TargetDescription | None:
    target = target_from_url(view_class, match, org_id, label_fields=TARGET_NAME_FIELDS)
    model = model_of(view_class)
    if target is None or model is None:
        return None
    target_id, name = target
    return TargetDescription(type=target_type(model), id=target_id, name=name)
