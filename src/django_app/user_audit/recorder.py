import functools
import threading
from uuid import uuid4

from django.conf import settings
from django.db import connection, models, transaction
from django.utils import timezone
from loguru import logger
from rbac.governance.organization_retention import effective_retention_days_for_org
from rbac.models import OrganizationUser
from src.shared.models import UserAction, UserActionEvent
from src.shared.retention import DataType

from user_audit.actor import Actor, actor_from_request
from user_audit.context import UserActionContext, current_context
from user_audit.sender import get_user_audit_sender
from user_audit.targets import TargetDescription, describe, target_parent

# Records made on this thread and not numbered yet, in record order. Django gives a thread
# one connection, so one transaction at a time: these are its records, plus any a rolled-back
# transaction left behind, which are numbered with the next batch (a gap) and never sent.
_unnumbered = threading.local()

# The only actions recorded without a target: the user themselves is the subject. Every
# other action must name what it changed, or it is not recorded at all.
TARGETLESS_ACTIONS = frozenset(
    {UserAction.SIGNED_IN, UserAction.SIGN_IN_FAILED, UserAction.SIGNED_OUT}
)


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
    """Record one user action, numbered and sent to the auditor once the transaction commits.

    Best-effort: never raises into the caller. Records nothing while the switch is off,
    or when there is no actor: none was passed and the current request (if any) was not
    made by a user or the system API key. So management commands and consumers, which
    run outside a request, record nothing unless they name the actor. Records nothing,
    and logs a warning, when the action needs a target and none was given
    (`TARGETLESS_ACTIONS`).

    Args:
        org_id: The resource's org, or the active org `OrgContextService` resolved for
            the request; never the raw `X-Organization-Id` header.
        target_description: For a target that no longer exists as a model instance;
            takes precedence over `target`.
        parent: Defaults to the target's own parent (`target_parent`), if it has one.
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
        target_description = target_description or (describe(target) if target else None)
        if target_description is None and action not in TARGETLESS_ACTIONS:
            # A record that names no target tells the reader nothing; the warning names the
            # code path that still needs a hook.
            logger.warning(
                "Dropping user action {} in org {} with no target (route {})", action, org_id, route
            )
            return
        if context is not None:
            context.recorded = True

        if parent is None and target is not None:
            parent = target_parent(target)
        parent_description = describe(parent) if parent is not None else None
        # Number and retention are set on commit, outside the caller's transaction.
        event = UserActionEvent(
            id=str(uuid4()),
            org_id=org_id,
            event_time=timezone.now(),
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
        _unnumbered_events().append(event)
        # robust: the write has committed, so a failing callback must not turn it into a 500.
        transaction.on_commit(lambda: _send_committed(event, context), robust=True)
    except Exception:
        logger.exception("Failed to record user action {} in org {}", action, org_id)


def _unnumbered_events() -> list[UserActionEvent]:
    if not hasattr(_unnumbered, "events"):
        _unnumbered.events = []
    return _unnumbered.events


def _send_committed(event: UserActionEvent, context: UserActionContext | None) -> None:
    # Runs after the commit, so a bulk change holding row locks waits on no audit query,
    # and the first record of a commit numbers the whole batch in one query.
    try:
        if event.number is None:
            _number_unnumbered_events()
        if event.number is None:
            # Its batch failed to be numbered, which the batch's first record logged.
            return
        event.retention_days = _retention_days(event.org_id, context)
        get_user_audit_sender().send([event])
    except Exception:
        logger.exception("Failed to record user action {} in org {}", event.action, event.org_id)


def _number_unnumbered_events() -> None:
    # Taken off the list first, so a failed read drops this batch rather than retrying it
    # for every record. Gaps are expected: nextval is not transactional, and a rolled-back
    # record's number is burnt. Sorted, so the numbers follow record order. A savepoint, so
    # a failed read leaves an enclosing transaction usable.
    events = _unnumbered_events()
    batch = list(events)
    events.clear()
    if not batch:
        return
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "SELECT nextval('user_action_record_number_seq') FROM generate_series(1, %s)",
            [len(batch)],
        )
        numbers = sorted(row[0] for row in cursor.fetchall())
    for event, number in zip(batch, numbers, strict=True):
        event.number = number


def _retention_days(org_id: int, context: UserActionContext | None) -> int:
    if context is not None and org_id in context.retention_days_by_org:
        return context.retention_days_by_org[org_id]
    # A savepoint, so a failed read caught by the caller leaves its transaction usable.
    with transaction.atomic():
        retention_days = effective_retention_days_for_org(org_id, DataType.AUDIT)
    if context is not None:
        context.retention_days_by_org[org_id] = retention_days
    return retention_days


def user_audit_hook(function):
    """Run `function` only while the user audit trail is on, and never let it raise.

    For capture code that reads the database to name what a record describes: with the
    switch off it costs nothing, and a failure is logged rather than failing the change it
    describes. The call returns None when skipped or failed. It runs in a savepoint, so a
    failed query caught here leaves the caller's transaction usable.
    """

    @functools.wraps(function)
    def guarded(*args, **kwargs):
        if not settings.USER_AUDIT_TRAIL_ENABLED:
            return None
        try:
            with transaction.atomic():
                return function(*args, **kwargs)
        except Exception:
            logger.exception("User action capture {} failed", function.__qualname__)
            return None

    return guarded


@user_audit_hook
def describe_for_record(instance: models.Model) -> TargetDescription:
    """Describe `instance` now, for a record written once it is deleted, or for a copy's source.

    None while the switch is off, or when describing it failed (logged).
    """
    return describe(instance)


def record_copy(source: models.Model, copy: models.Model) -> None:
    """Record `copy` as copied, in its own org, with the name `source` had as previous name.

    Records nothing for a copy that belongs to no org. Best-effort like `record_user_action`.
    """
    org_id = getattr(copy, "org_id", None)
    if org_id is None:
        return
    source_description = describe_for_record(source)
    record_user_action(
        action=UserAction.COPIED,
        org_id=org_id,
        target=copy,
        previous_name=source_description.name if source_description is not None else None,
    )


def record_for_user_orgs(
    *,
    action: str,
    actor: Actor | None = None,
    target: models.Model | None = None,
    target_description: TargetDescription | None = None,
    org_user_id: int | None = None,
    route: str | None = None,
) -> None:
    """Record the action once in every active organization `actor` is a member of.

    For actions that belong to no single org, such as signing in. Best-effort like
    `record_user_action`, and like it records nothing when no `actor` is passed and the
    current request (if any) was not made by a user or the system API key.

    Args:
        org_user_id: Fan out over this user's organizations instead of the actor's, for an
            action one user takes on another, such as an administrator resetting a password.
            The memberships are read now, so call it before they are deleted.
    """
    if not settings.USER_AUDIT_TRAIL_ENABLED:
        return
    try:
        if actor is None:
            context = current_context()
            actor = actor_from_request(context.request) if context is not None else None
        if actor is None:
            return
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
                route=route,
                actor=actor,
            )
    except Exception:
        logger.exception("Failed to record user action {} across a user's orgs", action)
