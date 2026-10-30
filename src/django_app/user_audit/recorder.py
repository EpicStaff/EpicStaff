from uuid import uuid4

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from loguru import logger
from rbac.governance.organization_retention import effective_retention_days_for_org
from rbac.models import OrganizationUser
from src.shared.models import UserActionEvent
from src.shared.retention import DataType

from user_audit.actor import Actor, actor_from_request
from user_audit.context import UserActionContext, current_context
from user_audit.sender import get_user_audit_sender
from user_audit.targets import TargetDescription, describe


def record_user_action(
    *,
    action: str,
    org_id: int,
    target: models.Model | None = None,
    target_description: TargetDescription | None = None,
    previous_name: str | None = None,
    parent: models.Model | None = None,
    route: str | None = None,
    actor: Actor | None = None,
) -> None:
    """Record one user action, sent to the auditor once the transaction commits.

    Best-effort: never raises into the caller. Records nothing while the switch is off,
    or when there is no actor: none was passed and the current request (if any) was not
    made by a user or the system API key. So management commands and consumers, which
    run outside a request, record nothing unless they name the actor.

    Args:
        org_id: The resource's org, or the active org `OrgContextService` resolved for
            the request; never the raw `X-Organization-Id` header.
        target_description: For a target that no longer exists as a model instance;
            takes precedence over `target`.
        route: Set only by the middleware's fallback record.
    """
    try:
        if not settings.USER_AUDIT_TRAIL_ENABLED:
            return
        context = current_context()
        if actor is None and context is not None:
            actor = actor_from_request(context.request)
        if actor is None:
            return
        if context is not None:
            context.recorded = True

        target_description = target_description or (describe(target) if target else None)
        parent_description = describe(parent) if parent is not None else None
        event = UserActionEvent(
            id=str(uuid4()),
            org_id=org_id,
            event_time=timezone.now(),
            retention_days=_retention_days(org_id, context),
            actor_user_id=actor.user_id,
            actor_email=actor.email,
            actor_api_key_name=actor.api_key_name,
            action=action,
            target_type=target_description.type if target_description else None,
            target_id=target_description.id if target_description else None,
            target_name=target_description.name if target_description else None,
            previous_name=previous_name,
            parent_type=parent_description.type if parent_description else None,
            parent_id=parent_description.id if parent_description else None,
            parent_name=parent_description.name if parent_description else None,
            route=route,
        )
        # robust: the write has committed, so a failing callback must not turn it into a 500.
        transaction.on_commit(lambda: get_user_audit_sender().send([event]), robust=True)
    except Exception:
        logger.exception("Failed to record user action {} in org {}", action, org_id)


def _retention_days(org_id: int, context: UserActionContext | None) -> int:
    if context is not None and org_id in context.retention_days_by_org:
        return context.retention_days_by_org[org_id]
    # A savepoint, so a failed read caught by the caller leaves its transaction usable.
    with transaction.atomic():
        retention_days = effective_retention_days_for_org(org_id, DataType.AUDIT)
    if context is not None:
        context.retention_days_by_org[org_id] = retention_days
    return retention_days


def record_for_user_orgs(
    *,
    action: str,
    actor: Actor,
    target: models.Model | None = None,
    target_description: TargetDescription | None = None,
    org_user_id: int | None = None,
) -> None:
    """Record the action once in every active organization `actor` is a member of.

    For actions that belong to no single org, such as signing in. Best-effort like
    `record_user_action`.

    Args:
        org_user_id: Fan out over this user's organizations instead of the actor's, for an
            action one user takes on another, such as an administrator resetting a password.
    """
    if not settings.USER_AUDIT_TRAIL_ENABLED:
        return
    try:
        # A savepoint, so a failed read caught below leaves the caller's transaction usable.
        with transaction.atomic():
            org_ids = list(
                OrganizationUser.objects.filter(
                    user_id=org_user_id if org_user_id is not None else actor.user_id,
                    org__is_active=True,
                ).values_list("org_id", flat=True)
            )
        for org_id in org_ids:
            record_user_action(
                action=action,
                org_id=org_id,
                target=target,
                target_description=target_description,
                actor=actor,
            )
    except Exception:
        logger.exception("Failed to record user action {} for user {}", action, actor.user_id)
