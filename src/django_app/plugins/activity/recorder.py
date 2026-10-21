"""Writes plugin activity events: a service account's writes, and what is done to a plugin.

A service account's request is recorded once its response is ready, when it changed
something (a method other than GET, HEAD and OPTIONS) and succeeded (status below 400),
except the `/api/plugin-runtime/` calls, which only read. Recording it never changes the
response: a failure is logged and the response goes out as it is. Lifecycle events are
written by the services that change the plugin, in their transaction.

Adding an action: an `ActivityAction` choice and its migration, a method here called where
the thing happens, then the frontend's label for it and its row in the service-account API
reference.
"""

from typing import TYPE_CHECKING

from django.db.models import Model
from rest_framework.permissions import SAFE_METHODS
from utils.logger import logger

from plugins.models import (
    ActivityAction,
    ActorKind,
    HookJobKind,
    PluginActivityEvent,
    PluginGrant,
    PluginHookJob,
)
from plugins.models.activity import MAX_TARGET_LABEL_LENGTH

if TYPE_CHECKING:
    from plugins.ownership.request_scope import PluginRequestScope

RUNTIME_API_PATH_PREFIX = "/api/plugin-runtime/"
# A request answered with a status at or above this changed nothing worth recording.
FIRST_FAILURE_STATUS = 400
# URL kwargs a detail route names its object by.
TARGET_URL_KWARGS = ("pk", "id")
PLATFORM_ACTOR_LABEL = "Platform"
# The actions a finished hook job of each kind is recorded as: (succeeded, failed).
HOOK_FINISHED_ACTIONS = {
    HookJobKind.INSTALL: (
        ActivityAction.INSTALL_HOOK_SUCCEEDED,
        ActivityAction.INSTALL_HOOK_FAILED,
    ),
}


class ActivityRecorder:
    def record_django_request(self, scope: "PluginRequestScope", request, response) -> None:
        """Record a Django request a service account made, if it is one that is recorded."""
        try:
            if not _is_recorded(request.method, request.path, response.status_code):
                return
            match = getattr(request, "resolver_match", None)
            view_class = getattr(getattr(match, "func", None), "cls", None)
            target = _target_from_created(scope) or _target_from_url(view_class, match)
            self._write_api_request(
                scope,
                method=request.method,
                path=request.path,
                route=match.route if match is not None else None,
                status=response.status_code,
                resource_type=_as_text(getattr(view_class, "rbac_resource_type", None)),
                target=target,
            )
        except Exception:
            logger.exception("Could not record a plugin service account's request as activity")

    def record_stream_request(
        self,
        scope: "PluginRequestScope",
        *,
        method: str,
        path: str,
        route: str,
        status: int,
        resource_type: str,
    ) -> None:
        """Record a request to an ASGI app outside Django (the upload stream), if recorded."""
        try:
            if not _is_recorded(method, path, status):
                return
            self._write_api_request(
                scope,
                method=method,
                path=path,
                route=route,
                status=status,
                resource_type=resource_type,
                target=_target_from_created(scope),
            )
        except Exception:
            logger.exception("Could not record a plugin service account's upload as activity")

    def package_approved(self, actor, *, identifier: str, version: str, trust: str) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.PACKAGE_APPROVED,
            {"version": version, "trust": trust},
        )

    def grant_created(self, actor, grant: PluginGrant) -> None:
        _superadmin_event(
            actor, grant.plugin.identifier, grant.org_id, ActivityAction.GRANT_CREATED, {}
        )

    def install_hook_retried(self, actor, job: PluginHookJob, identifier: str) -> None:
        _superadmin_event(
            actor,
            identifier,
            job.organization_id,
            ActivityAction.INSTALL_HOOK_RETRIED,
            {"job_id": job.pk},
        )

    def hook_finished(
        self, job: PluginHookJob, identifier: str, *, succeeded: bool, error: str | None
    ) -> None:
        succeeded_action, failed_action = HOOK_FINISHED_ACTIONS[job.kind]
        detail = {"job_id": job.pk, "attempt": job.attempt}
        if not succeeded:
            detail["error"] = error
        PluginActivityEvent.objects.create(
            plugin_identifier=identifier,
            organization_id=job.organization_id,
            actor_kind=ActorKind.PLATFORM,
            actor_label=PLATFORM_ACTOR_LABEL,
            action=succeeded_action if succeeded else failed_action,
            detail=detail,
        )

    def settings_changed(self, actor, identifier: str, keys: list[str]) -> None:
        """Record which settings changed; their values, secret or not, never are."""
        _superadmin_event(
            actor, identifier, None, ActivityAction.SETTINGS_CHANGED, {"keys": sorted(keys)}
        )

    def limits_changed(self, actor, identifier: str, overrides: dict) -> None:
        _superadmin_event(
            actor, identifier, None, ActivityAction.LIMITS_CHANGED, {"overrides": overrides}
        )

    def restarted(self, actor, identifier: str, restart_generation: int) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.RESTARTED,
            {"restart_generation": restart_generation},
        )

    @staticmethod
    def _write_api_request(
        scope: "PluginRequestScope",
        *,
        method: str,
        path: str,
        route: str | None,
        status: int,
        resource_type: str | None,
        target: tuple[str | None, str | None] | None,
    ) -> None:
        principal = scope.principal
        person = principal.person
        target_id, target_label = target or (None, None)
        PluginActivityEvent.objects.create(
            plugin_identifier=principal.plugin_identifier,
            organization_id=principal.pinned_org_id,
            actor_kind=ActorKind.PLUGIN,
            actor_label=principal.display_name,
            on_behalf_of_user=person,
            on_behalf_of_label=person.email if person is not None else None,
            action=ActivityAction.API_REQUEST,
            request_method=method,
            request_path=path,
            request_route=route,
            response_status=status,
            target_resource_type=resource_type,
            target_id=target_id,
            target_label=(target_label or None) and target_label[:MAX_TARGET_LABEL_LENGTH],
            detail={"created_count": len(scope.created)},
        )


def _is_recorded(method: str, path: str, status: int) -> bool:
    return (
        method not in SAFE_METHODS
        and status < FIRST_FAILURE_STATUS
        and not path.startswith(RUNTIME_API_PATH_PREFIX)
    )


def _target_from_created(scope: "PluginRequestScope") -> tuple[str, str | None] | None:
    if not scope.created:
        return None
    first = scope.created[0]
    return str(first.pk), first.label


def _target_from_url(view_class, match) -> tuple[str, str | None] | None:
    """The object a detail route names, labelled with its name when it has one and still exists."""
    kwargs = match.kwargs if match is not None else {}
    value = next((kwargs[name] for name in TARGET_URL_KWARGS if name in kwargs), None)
    if value is None:
        return None
    return str(value), _name_of_row(view_class, value)


def _name_of_row(view_class, value) -> str | None:
    model = _model_of(view_class)
    if model is None or "name" not in {field.name for field in model._meta.concrete_fields}:
        return None
    try:
        name = model._base_manager.filter(pk=value).values_list("name", flat=True).first()
    except (TypeError, ValueError):
        return None
    return name if isinstance(name, str) else None


def _model_of(view_class) -> type[Model] | None:
    """The model a view serves: its queryset's, else its serializer's."""
    queryset = getattr(view_class, "queryset", None)
    if queryset is not None:
        return queryset.model
    serializer_meta = getattr(getattr(view_class, "serializer_class", None), "Meta", None)
    return getattr(serializer_meta, "model", None)


def _superadmin_event(
    actor, identifier: str, organization_id: int | None, action: str, detail: dict
) -> None:
    PluginActivityEvent.objects.create(
        plugin_identifier=identifier,
        organization_id=organization_id,
        actor_kind=ActorKind.SUPERADMIN,
        actor_user=actor,
        actor_label=actor.email,
        action=action,
        detail=detail,
    )


def _as_text(value) -> str | None:
    return None if value is None else str(value)
