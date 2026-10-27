"""Writes plugin activity events: a service account's writes, and what is done to a plugin.

A service account's request is recorded once its response is ready, when it changed
something (a method other than GET, HEAD and OPTIONS) and succeeded (status below 400),
except the `/api/plugin-runtime/` calls, which only read. One made with a development key has
`detail.development` true. Recording it never changes the
response: a failure is logged and the response goes out as it is. Lifecycle events are
written by the services that change the plugin, in their transaction.

`detail` holds only scalars and lists of strings, so every reader can show it as it is.

Adding an action: an `ActivityAction` choice and its migration, a method here called where
the thing happens, then the frontend's label for it and its row in the service-account API
reference.
"""

import re
from typing import TYPE_CHECKING

from django.db.models import Model
from rest_framework import serializers
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
# The columns a row is labelled with, the first one its model has.
TARGET_LABEL_FIELDS = ("name", "custom_name")
_NAMED_GROUP_START = re.compile(r"\(\?P<(\w+)>")
_PATH_CONVERTER = re.compile(r"<\w+:(\w+)>")
PLATFORM_ACTOR_LABEL = "Platform"
# The actions a finished hook job of each kind is recorded as: (succeeded, failed).
HOOK_FINISHED_ACTIONS = {
    HookJobKind.INSTALL: (
        ActivityAction.INSTALL_HOOK_SUCCEEDED,
        ActivityAction.INSTALL_HOOK_FAILED,
    ),
    HookJobKind.ORG_REMOVED: (
        ActivityAction.ORG_REMOVED_HOOK_SUCCEEDED,
        ActivityAction.ORG_REMOVED_HOOK_FAILED,
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
            target = _target_from_created(scope) or _target_from_url(
                view_class, match, scope.principal.pinned_org_id
            )
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

    def grant_suspended(self, actor, grant: PluginGrant, previous_state: str, cause: str) -> None:
        """Record a suspension; `cause` is `grant`, or `uninstall` when the plugin was uninstalled."""
        _superadmin_event(
            actor,
            grant.plugin.identifier,
            grant.org_id,
            ActivityAction.GRANT_SUSPENDED,
            {
                "previous_state": previous_state,
                "purge_after": _datetime_text(grant.purge_after),
                "cause": cause,
            },
        )

    def grant_resumed(self, actor, grant: PluginGrant, cause: str | None) -> None:
        """Record a resume; `cause` is the one the suspension had."""
        _superadmin_event(
            actor,
            grant.plugin.identifier,
            grant.org_id,
            ActivityAction.GRANT_RESUMED,
            {"state": grant.state, "cause": cause},
        )

    def grant_purge_started(
        self,
        actor,
        grant: PluginGrant,
        *,
        reason: str,
        previous_state: str,
        owned_resources: int,
    ) -> None:
        """Record that deleting a grant's data began; `actor` None is the platform."""
        _actor_event(
            actor,
            grant.plugin.identifier,
            grant.org_id,
            ActivityAction.GRANT_PURGE_STARTED,
            {
                "reason": reason,
                "previous_state": previous_state,
                "owned_resources": owned_resources,
            },
        )

    def grant_purged(self, identifier: str, organization_id: int) -> None:
        _actor_event(None, identifier, organization_id, ActivityAction.GRANT_PURGED, {})

    def plugin_uninstalled(self, actor, identifier: str, purge_after, organizations: int) -> None:
        """Record an uninstall; `organizations` is how many grants it suspended."""
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.PLUGIN_UNINSTALLED,
            {"purge_after": _datetime_text(purge_after), "organizations": organizations},
        )

    def plugin_reinstalled(self, actor, identifier: str, organizations_resumed: int) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.PLUGIN_REINSTALLED,
            {"organizations_resumed": organizations_resumed},
        )

    def plugin_purge_started(self, actor, identifier: str, reason: str) -> None:
        """Record that deleting a plugin began; `actor` None is the platform."""
        _actor_event(
            actor, identifier, None, ActivityAction.PLUGIN_PURGE_STARTED, {"reason": reason}
        )

    def plugin_removal_failed(self, identifier: str, error: str | None) -> None:
        _platform_event(identifier, ActivityAction.PLUGIN_REMOVAL_FAILED, {"error": error})

    def plugin_removal_retried(self, actor, identifier: str) -> None:
        _superadmin_event(actor, identifier, None, ActivityAction.PLUGIN_REMOVAL_RETRIED, {})

    def plugin_purged(self, identifier: str, version: str | None, had_database: bool) -> None:
        _platform_event(
            identifier,
            ActivityAction.PLUGIN_PURGED,
            {"version": version, "had_database": had_database},
        )

    def org_removed_hook_retried(self, actor, job: PluginHookJob, identifier: str) -> None:
        _superadmin_event(
            actor,
            identifier,
            job.organization_id,
            ActivityAction.ORG_REMOVED_HOOK_RETRIED,
            {"job_id": job.pk},
        )

    def org_removed_hook_skipped(
        self, actor, job: PluginHookJob, identifier: str, state_before: str
    ) -> None:
        """Record a skipped data removal; `actor` None is the platform."""
        _actor_event(
            actor,
            identifier,
            job.organization_id,
            ActivityAction.ORG_REMOVED_HOOK_SKIPPED,
            {"job_id": job.pk, "state_before": state_before},
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
        _organization_event(
            identifier,
            job.organization_id,
            succeeded_action if succeeded else failed_action,
            detail,
        )

    def upgrade_hook_succeeded(self, job: PluginHookJob, identifier: str) -> None:
        _organization_event(
            identifier,
            job.organization_id,
            ActivityAction.UPGRADE_HOOK_SUCCEEDED,
            {
                "job_id": job.pk,
                "attempt": job.attempt,
                "from_version": job.previous_version,
                "to_version": job.package_version,
            },
        )

    def upgrade_hook_failed(
        self, job: PluginHookJob, identifier: str, *, error: str | None, next_attempt_at
    ) -> None:
        """Record a failed upgrade attempt; `next_attempt_at` None means it waits for Retry."""
        _organization_event(
            identifier,
            job.organization_id,
            ActivityAction.UPGRADE_HOOK_FAILED,
            {
                "job_id": job.pk,
                "attempt": job.attempt,
                "error": error,
                "next_attempt_at": _datetime_text(next_attempt_at),
            },
        )

    def upgrade_hook_retried(self, actor, job: PluginHookJob, identifier: str) -> None:
        _superadmin_event(
            actor,
            identifier,
            job.organization_id,
            ActivityAction.UPGRADE_HOOK_RETRIED,
            {"job_id": job.pk},
        )

    def plugin_upgrade_started(
        self,
        actor,
        identifier: str,
        *,
        from_version: str,
        to_version: str,
        access_growth_acknowledged: bool,
        untrusted_acknowledged: bool,
        replaced_version: str | None,
    ) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.PLUGIN_UPGRADE_STARTED,
            {
                "from_version": from_version,
                "to_version": to_version,
                "access_growth_acknowledged": access_growth_acknowledged,
                "untrusted_acknowledged": untrusted_acknowledged,
                "replaced_version": replaced_version,
            },
        )

    def plugin_maintenance_started(
        self, identifier: str, to_version: str, organizations: int
    ) -> None:
        _platform_event(
            identifier,
            ActivityAction.PLUGIN_MAINTENANCE_STARTED,
            {"to_version": to_version, "organizations": organizations},
        )

    def plugin_upgrade_failed(
        self, identifier: str, *, to_version: str, stage: str, step: str | None, error: str | None
    ) -> None:
        _platform_event(
            identifier,
            ActivityAction.PLUGIN_UPGRADE_FAILED,
            {"to_version": to_version, "stage": stage, "step": step, "error": error},
        )

    def plugin_upgrade_retried(self, actor, identifier: str, to_version: str) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.PLUGIN_UPGRADE_RETRIED,
            {"to_version": to_version},
        )

    def plugin_upgrade_cancelled(self, actor, identifier: str, to_version: str, stage: str) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.PLUGIN_UPGRADE_CANCELLED,
            {"to_version": to_version, "stage": stage},
        )

    def plugin_upgraded(
        self, identifier: str, *, from_version: str, to_version: str, maintenance_seconds: int
    ) -> None:
        _platform_event(
            identifier,
            ActivityAction.PLUGIN_UPGRADED,
            {
                "from_version": from_version,
                "to_version": to_version,
                "maintenance_seconds": maintenance_seconds,
            },
        )

    def database_backed_up(self, identifier: str, backup) -> None:
        _platform_event(
            identifier,
            ActivityAction.DATABASE_BACKED_UP,
            {
                "file_name": backup.file_name,
                "reason": backup.reason,
                "size_bytes": backup.size_bytes,
                "version": backup.version,
            },
        )

    def database_restore_requested(self, actor, identifier: str, file_name: str) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.DATABASE_RESTORE_REQUESTED,
            {"file_name": file_name},
        )

    def database_restored(
        self, identifier: str, file_name: str, pre_restore_file_name: str | None
    ) -> None:
        _platform_event(
            identifier,
            ActivityAction.DATABASE_RESTORED,
            {"file_name": file_name, "pre_restore_file_name": pre_restore_file_name},
        )

    def database_restore_failed(self, identifier: str, step: str | None, error: str | None) -> None:
        _platform_event(
            identifier, ActivityAction.DATABASE_RESTORE_FAILED, {"step": step, "error": error}
        )

    def settings_changed(self, actor, identifier: str, keys: list[str]) -> None:
        """Record which settings changed; their values, secret or not, never are."""
        _superadmin_event(
            actor, identifier, None, ActivityAction.SETTINGS_CHANGED, {"keys": sorted(keys)}
        )

    def limits_changed(self, actor, identifier: str, overrides: dict) -> None:
        """Record the overrides in force after the change, one scalar per limit."""
        _superadmin_event(actor, identifier, None, ActivityAction.LIMITS_CHANGED, dict(overrides))

    def restarted(self, actor, identifier: str, restart_generation: int) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.RESTARTED,
            {"restart_generation": restart_generation},
        )

    def database_ready(self, identifier: str, migrations_applied: int) -> None:
        _platform_event(
            identifier, ActivityAction.DATABASE_READY, {"migrations_applied": migrations_applied}
        )

    def database_failed(self, identifier: str, error: str | None) -> None:
        _platform_event(identifier, ActivityAction.DATABASE_FAILED, {"error": error})

    def development_target_set(
        self, actor, identifier: str, backend_port: int | None, spa_port: int | None
    ) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.DEVELOPMENT_TARGET_SET,
            {"backend_port": backend_port, "spa_port": spa_port},
        )

    def development_target_cleared(self, actor, identifier: str, revoked_keys: int) -> None:
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.DEVELOPMENT_TARGET_CLEARED,
            {"revoked_keys": revoked_keys},
        )

    def development_runtime_file_issued(self, actor, identifier: str, organizations: int) -> None:
        """Record a download of the development runtime file; `organizations` is how many
        organizations it holds a key for. The file itself is never recorded."""
        _superadmin_event(
            actor,
            identifier,
            None,
            ActivityAction.DEVELOPMENT_RUNTIME_FILE_ISSUED,
            {"organizations": organizations},
        )

    def database_limit_restored(self, identifier: str, setting: str) -> None:
        """Record that the node put back a limit of the app role that had been changed."""
        _platform_event(identifier, ActivityAction.DATABASE_LIMIT_RESTORED, {"setting": setting})

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
        detail = {"created_count": len(scope.created)}
        if principal.development_key:
            detail["development"] = True
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
            request_route=url_path_pattern(route) if route is not None else None,
            response_status=status,
            target_resource_type=resource_type,
            target_id=target_id,
            target_label=(target_label or None) and target_label[:MAX_TARGET_LABEL_LENGTH],
            detail=detail,
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


def url_path_pattern(route: str) -> str:
    """A resolved route as a URL path pattern, the same form for every view.

    A router's regular expressions lose their anchors and escapes, and each named group
    becomes `<name>`: `api/^graphs/(?P<pk>[^/.]+)/$` is recorded as `api/graphs/<pk>/`. A
    `path()` route loses its converters the same way: `api/sessions/<int:session_id>/stop/`
    is recorded as `api/sessions/<session_id>/stop/`.
    """
    parts = []
    position = 0
    while (group := _NAMED_GROUP_START.search(route, position)) is not None:
        parts.append(route[position : group.start()])
        parts.append(f"<{group.group(1)}>")
        position = _end_of_group(route, group.end())
    parts.append(route[position:])
    pattern = re.sub(r"\\(.)", r"\1", "".join(parts).replace("^", "").replace("$", ""))
    return _PATH_CONVERTER.sub(r"<\1>", pattern)


def _end_of_group(route: str, position: int) -> int:
    """The position after the parenthesis that closes the group open before `position`."""
    depth = 1
    while position < len(route) and depth:
        character = route[position]
        if character == "\\":
            position += 1
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        position += 1
    return position


def _target_from_url(view_class, match, org_id: int) -> tuple[str, str | None] | None:
    """The object a detail route names, labelled when the organization still has it."""
    kwargs = match.kwargs if match is not None else {}
    value = next((kwargs[name] for name in TARGET_URL_KWARGS if name in kwargs), None)
    if value is None:
        return None
    return str(value), _label_of_row(view_class, value, org_id)


def _label_of_row(view_class, value, org_id: int) -> str | None:
    """The row's name (or custom name), read in `org_id` only, so a label never comes from
    another organization's row; None for a model without an organization."""
    model = _model_of(view_class)
    if model is None:
        return None
    field_names = {field.name for field in model._meta.concrete_fields}
    label_field = next((name for name in TARGET_LABEL_FIELDS if name in field_names), None)
    if "org" not in field_names or label_field is None:
        return None
    try:
        label = (
            model._base_manager.filter(pk=value, org_id=org_id)
            .values_list(label_field, flat=True)
            .first()
        )
    except (TypeError, ValueError):
        return None
    return label if isinstance(label, str) else None


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


def _actor_event(
    actor, identifier: str, organization_id: int | None, action: str, detail: dict
) -> None:
    """An event a SuperAdmin caused, or the platform itself when `actor` is None."""
    if actor is not None:
        _superadmin_event(actor, identifier, organization_id, action, detail)
        return
    PluginActivityEvent.objects.create(
        plugin_identifier=identifier,
        organization_id=organization_id,
        actor_kind=ActorKind.PLATFORM,
        actor_label=PLATFORM_ACTOR_LABEL,
        action=action,
        detail=detail,
    )


def _datetime_text(value) -> str | None:
    return serializers.DateTimeField().to_representation(value) if value is not None else None


def _organization_event(identifier: str, organization_id: int, action: str, detail: dict) -> None:
    """An event the platform caused in one organization."""
    PluginActivityEvent.objects.create(
        plugin_identifier=identifier,
        organization_id=organization_id,
        actor_kind=ActorKind.PLATFORM,
        actor_label=PLATFORM_ACTOR_LABEL,
        action=action,
        detail=detail,
    )


def _platform_event(identifier: str, action: str, detail: dict) -> None:
    """A deployment-wide event the platform itself caused: no organization, no person."""
    PluginActivityEvent.objects.create(
        plugin_identifier=identifier,
        organization_id=None,
        actor_kind=ActorKind.PLATFORM,
        actor_label=PLATFORM_ACTOR_LABEL,
        action=action,
        detail=detail,
    )


def _as_text(value) -> str | None:
    return None if value is None else str(value)
