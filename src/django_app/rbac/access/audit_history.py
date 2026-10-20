"""The audit history limit a role grants: storage mapping and the ceiling rule.

The only module that knows how "unlimited" is stored. In the API and in the audit
token, `0` means unlimited; in the database, unlimited is the absence of a
`RoleAuditPolicy` row, and a row always holds a real limit.
"""

from collections.abc import Mapping

from django.core.exceptions import ObjectDoesNotExist

from rbac.models.enums import Permission, ResourceType

AUDIT_HISTORY_DAYS_MAX = 36_500  # Product cap: 100 years.
UNLIMITED = 0

_AUDIT_ACTIONS = int(Permission.READ) | int(Permission.EXPORT)


def grants_audit(by_resource: Mapping[str, int]) -> bool:
    """Whether these per-resource bits let the holder read or export audit data."""
    return bool(by_resource.get(ResourceType.AUDIT.value, 0) & _AUDIT_ACTIONS)


def history_days_of(role) -> int:
    """The role's limit in days, or `UNLIMITED` when it has no policy row.

    Callers load the role with `select_related("audit_policy")`, so this issues no
    query; a missing reverse one-to-one is cached as missing by that join too.
    """
    try:
        return role.audit_policy.history_days
    except ObjectDoesNotExist:
        return UNLIMITED


def is_within(actor_days: int, granted_days: int) -> bool:
    """Whether granting `granted_days` stays within an actor limited to `actor_days`.

    Unlimited is the widest value: an unlimited actor may grant anything, and a
    limited actor may grant neither unlimited nor more days than their own.
    """
    if actor_days == UNLIMITED:
        return True
    return granted_days != UNLIMITED and granted_days <= actor_days


def sync_audit_policy(role, history_days: int) -> None:
    """Store `history_days` as the role's limit: `UNLIMITED` deletes the row.

    The single write path for the policy, shared by role create/update and the
    built-in seeder so they cannot store "unlimited" differently.
    """
    # Imported here: rbac.models imports this module for AUDIT_HISTORY_DAYS_MAX.
    from rbac.models import RoleAuditPolicy

    if history_days == UNLIMITED:
        RoleAuditPolicy.objects.filter(role=role).delete()
    else:
        RoleAuditPolicy.objects.update_or_create(role=role, defaults={"history_days": history_days})
