"""Capture layer 3: one generic record for a change no earlier layer recorded.

A successful change request (import, version restore, ...) that neither a
`LastEditTracker` nor an explicit `record_user_action` call described is recorded once,
with its action (a custom DRF action keeps its name; DRF's generic ones read like the
recorder's own verbs), its route and the object its URL names, or for DRF's generic
`create` the object its response names by id. The record never reads the request body,
nor any of the response but that id.
"""

import io

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.handlers.asgi import ASGIRequest
from django.db.models import F, Model
from rbac.views.auth import (
    ApiKeyValidateView,
    CookieTokenRefreshView,
    FirstSetupView,
    LoginView,
    LogoutView,
    PasswordResetRequestView,
    ResetUserView,
    SseTicketView,
    SwaggerTokenView,
    TokenIntrospectView,
    WsTicketView,
)
from rbac.views.profile import PasswordChangeRequestView, ProfileTourCompleteView
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response
from src.shared.models import UserAction
from tables.views.audit_token_views import AuditTokenView
from utils.logger import logger
from utils.request_target import (
    id_from_response,
    id_from_url,
    model_of,
    org_path_of,
    org_row,
    url_path_pattern,
)

from user_audit.actor import actor_from_request
from user_audit.context import UserActionContext, current_context, user_action_context
from user_audit.read_only import handler_reads_only
from user_audit.recorder import record_user_action
from user_audit.targets import TargetDescription, fields_to_describe, target_type

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
        PasswordResetRequestView,
        PasswordChangeRequestView,
        # Record their own signed_in, sign_in_failed and signed_out.
        LoginView,
        LogoutView,
        # Instance setup and user wipe: superadmin or anonymous instance operations that
        # belong to no organization's trail.
        FirstSetupView,
        ResetUserView,
        # The caller's own UI state, like FALLBACK_EXCLUDED_ACTIONS.
        ProfileTourCompleteView,
    }
)
# DRF actions that change only the caller's own preferences, never anything the org shares.
FALLBACK_EXCLUDED_ACTIONS = frozenset({"favorite"})
# The action recorded for a view with no DRF action name for the method.
METHOD_ACTIONS = {"POST": "create", "PUT": "update", "PATCH": "update", "DELETE": "destroy"}
# DRF's generic action names, recorded as the verbs the recorder's own records use, so one
# change reads the same whichever layer recorded it. A destroy that bins its row never gets
# here, DeleteService records it as moved_to_recycle_bin: a destroy recorded here deleted
# its row at once.
GENERIC_ACTIONS = {
    "create": UserAction.CREATED,
    "update": UserAction.UPDATED,
    "partial_update": UserAction.UPDATED,
    "destroy": UserAction.DELETED,
}
# Custom DRF actions the fallback never records, because their URL names another object
# than the one they change: a copy's names its source, so the copy records itself
# (`record_copy`).
HOOK_ONLY_ACTIONS = frozenset({"copy"})
# Where every authentication class reads its credentials (JWT, API key, plugin keys). A
# request with neither is anonymous, and an anonymous request is never recorded.
CREDENTIAL_HEADERS = ("HTTP_AUTHORIZATION", "HTTP_X_API_KEY")
# The org that owned a row loaded before its DELETE, read in the same query.
ORG_BEFORE_DELETE_ATTRIBUTE = "_user_audit_org_id"


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
                response_data=response.data if isinstance(response, Response) else None,
            )
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Load the row a DELETE names before the view deletes it, for the fallback to name.

        One query per DELETE that carries credentials while the switch is on, none
        otherwise. It runs before authentication, so it reads in no org: the org is checked
        inside the view, and the fallback uses the row only when the org it then checked
        owned it.
        """
        context = current_context()
        if (
            context is not None
            and request.method == "DELETE"
            and any(request.META.get(header) for header in CREDENTIAL_HEADERS)
        ):
            context.row_before_delete = _row_before_delete(view_func, request.resolver_match)


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
    context: UserActionContext,
    *,
    status: int,
    view_class,
    action: str | None,
    route,
    match,
    response_data=None,
) -> None:
    """Record the request once when it changed something and nothing recorded it yet.

    Skips a handler marked `reads_only`, besides the excluded views and actions and the
    actions only a hook records (`HOOK_ONLY_ACTIONS`).

    Best-effort: never raises. The record goes to the org `OrgContextService` checked for
    the request; a request with no checked org is not recorded, nor is one whose target
    neither its URL nor its create response names.

    Args:
        action: The view's DRF action name for the method, if it has one.
        route: The resolved URL route, None when the request resolved to no view.
        match: The resolved URL, whose `pk` or `id` names the target.
        response_data: A DRF response's data. For DRF's generic `create`, whose URL names
            no object, only its id (`pk`, `id` or the model's primary key) is read, to name
            the created object.
    """
    request = context.request
    try:
        if (
            not settings.USER_AUDIT_TRAIL_ENABLED
            or request.method in SAFE_METHODS
            or status >= FIRST_FAILURE_STATUS
            or context.recorded
            or view_class in FALLBACK_EXCLUDED_VIEWS
            or action in FALLBACK_EXCLUDED_ACTIONS
            or action in HOOK_ONLY_ACTIONS
            or handler_reads_only(view_class, action or request.method.lower())
        ):
            return
        # None for an anonymous caller and a plugin's service account.
        actor = actor_from_request(request)
        if actor is None:
            return
        created_data = response_data if action == "create" else None
        action = action or METHOD_ACTIONS.get(request.method, request.method.lower())
        action = GENERIC_ACTIONS.get(action, action)
        route_text = f"{request.method} {url_path_pattern(route)}" if route is not None else None
        org_id = getattr(request, "_rbac_active_org_id", None)
        if org_id is not None:
            target, target_description = _fallback_target(
                view_class, match, org_id, created_data, context.row_before_delete
            )
            record_user_action(
                action=action,
                org_id=org_id,
                target=target,
                target_description=target_description,
                route=route_text,
                actor=actor,
            )
    except Exception:
        logger.exception("Failed to record {} {} as a user action", request.method, request.path)


def _fallback_target(
    view_class, match, org_id: int, created_data, row_before_delete: Model | None = None
) -> tuple[Model | None, TargetDescription | None]:
    """The changed row, loaded only when `org_id` owns it (see `org_row`), so it is named
    and given its parent like a hook's target; a row the request deleted is the copy
    `row_before_delete` loaded before. Failing that, the bare type and id the URL names; a
    create's response id that does not resolve names nothing."""
    model = model_of(view_class)
    if model is None:
        return None, None
    url_id = id_from_url(match)
    value = url_id if url_id is not None else id_from_response(model, created_data)
    if value is None:
        return None, None
    row = org_row(
        view_class, value, org_id, fields=fields_to_describe(model)
    ) or _deleted_row_of_org(row_before_delete, model, url_id, org_id)
    if row is not None:
        return row, None
    if url_id is None:
        return None, None
    return None, TargetDescription(type=target_type(model), id=str(url_id), name=None)


def _row_before_delete(view_func, match) -> Model | None:
    """The row the URL of a DELETE names, whatever org owns it, with that org's id; None
    while the switch is off, for a custom action (a purge records itself), for a URL that
    names no row or an id its model cannot hold, and for a view whose rows reach no org.

    Loads only what naming it takes (`fields_to_describe`). Runs before the view, outside
    any transaction (`ATOMIC_REQUESTS` is off), so a failed read leaves nothing to roll back.
    """
    try:
        if not settings.USER_AUDIT_TRAIL_ENABLED:
            return None
        if getattr(view_func, "actions", {}).get("delete") not in (None, "destroy"):
            return None
        view_class = getattr(view_func, "cls", None)
        model = model_of(view_class)
        url_id = id_from_url(match)
        if model is None or url_id is None:
            return None
        org_path = org_path_of(view_class, model)
        if org_path is None:
            return None
        return (
            model._base_manager.filter(pk=url_id)
            .only(*fields_to_describe(model))
            .annotate(**{ORG_BEFORE_DELETE_ATTRIBUTE: F(org_path)})
            .first()
        )
    except (TypeError, ValueError, ValidationError):
        # An id the model cannot hold ("abc" for an integer key): the view answers 404, and
        # anyone can send one, so it is not worth a log line.
        return None
    except Exception:
        logger.exception("Failed to load the row a DELETE names for its user-action record")
        return None


def _deleted_row_of_org(row: Model | None, model: type[Model], url_id, org_id: int) -> Model | None:
    """`row`, loaded before the request deleted it, when it is the row the URL names and
    `org_id` owned it; else None."""
    if row is None or url_id is None or not isinstance(row, model) or str(row.pk) != str(url_id):
        return None
    return row if getattr(row, ORG_BEFORE_DELETE_ATTRIBUTE, None) == org_id else None
