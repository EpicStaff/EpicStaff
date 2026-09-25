from collections.abc import Iterable, Mapping

from django.conf import settings
from loguru import logger

RBAC_RESOURCE_NAMES: dict[str, str] = {
    # user cascade
    "rbac.OrganizationUser": "memberships",
    "rbac.ApiKey": "api_keys",
    "rbac.PasswordResetToken": "password_reset_tokens",
    # org cascade -- direct
    "rbac.Role": "roles",
}

# Role sub-detail is implied by "roles". The delete target's own row is
# always part of the cascade Collector.collect([instance]) reports, but the
# target is already identified by organization_id/user_id, not an affected
# resource.
RBAC_EXCLUDED_RESOURCE_LABELS: frozenset[str] = frozenset(
    {
        "rbac.RolePermission",
        "rbac.Organization",
        settings.AUTH_USER_MODEL,
    }
)

# Labels owned by other apps, registered at app load through
# rbac.governance.organization_deletion.register_participant.
_registered_resource_names: dict[str, str] = {}
_registered_excluded_resource_labels: set[str] = set()


def register_resource_names(names: Mapping[str, str], excluded_labels: Iterable[str]) -> None:
    """Add another app's model labels to the delete report, refusing any label that is already known."""
    excluded = set(excluded_labels)
    known = known_resource_names().keys() | known_excluded_resource_labels()
    overlap = ((names.keys() | excluded) & known) | (names.keys() & excluded)
    if overlap:
        raise ValueError(f"delete report labels registered twice: {sorted(overlap)}")
    _registered_resource_names.update(names)
    _registered_excluded_resource_labels.update(excluded)


def known_resource_names() -> dict[str, str]:
    """Return every model label the delete report maps to a friendly resource name."""
    return {**RBAC_RESOURCE_NAMES, **_registered_resource_names}


def known_excluded_resource_labels() -> frozenset[str]:
    """Return every model label the delete report deliberately leaves out."""
    return RBAC_EXCLUDED_RESOURCE_LABELS | _registered_excluded_resource_labels


def resource_name(label: str) -> str | None:
    """Friendly display name for a cascade row's model label, or None if it must not be reported at all."""
    mapped = RBAC_RESOURCE_NAMES.get(label) or _registered_resource_names.get(label)
    if mapped is not None:
        return mapped
    if label in RBAC_EXCLUDED_RESOURCE_LABELS or label in _registered_excluded_resource_labels:
        return None
    logger.warning(
        "delete report: unmapped model label {label} -- add it to the owning app's delete resource names",
        label=label,
    )
    return None
