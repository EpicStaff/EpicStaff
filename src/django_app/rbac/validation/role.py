from typing import Any

from rbac.access.audit_history import AUDIT_HISTORY_DAYS_MAX, UNLIMITED, grants_audit
from rbac.access.bitmask import actions_to_bitmask
from rbac.access.catalog import (
    applicable_actions_for,
    platform_actions_for,
)
from rbac.models.enums import BuiltInRole, ResourceType
from rbac.validation.base import BaseRBACValidator, FieldError

_RESERVED_NAMES = frozenset(
    name.lower()
    for name in (
        BuiltInRole.SUPERADMIN,
        BuiltInRole.ORG_ADMIN,
        BuiltInRole.MEMBER,
        BuiltInRole.VIEWER,
    )
)
_MAX_NAME = 255
_MAX_DESCRIPTION = 1000
_AUDIT_HISTORY_DAYS = "audit_history_days"


class RoleValidationService(BaseRBACValidator):
    """Static validation for custom-role write payloads. Uniqueness and
    the ceiling/authorization rules are enforced in RoleManagementService
    (they need DB + caller context). Returns cleaned payloads with
    action-code lists already converted to per-resource bitmasks.

    The audit history limit travels inside the `audit` permission entry
    (0 or omitted = unlimited). The cleaned payload lifts it to a top-level
    `audit_history_days`, present exactly when `permissions` is."""

    def validate_create(self, data: dict) -> dict:
        errors: list[FieldError] = []
        errors.extend(self._validate_positive_int_field("org_id", data.get("org_id")))
        errors.extend(self._validate_name(data.get("name")))
        errors.extend(self._validate_description(data.get("description")))
        errors.extend(self._reject_top_level_audit_history_days(data))
        permissions, audit_history_days, perm_errors = self._validate_permissions(
            data.get("permissions")
        )
        errors.extend(perm_errors)
        self._raise_if_any(errors)
        return {
            "org_id": int(data["org_id"]),
            "name": data["name"].strip(),
            "description": self._clean_description(data.get("description")),
            "permissions": permissions,
            "audit_history_days": audit_history_days,
        }

    def validate_update(self, data: dict) -> dict:
        cleaned: dict = {}
        errors: list[FieldError] = self._reject_top_level_audit_history_days(data)
        if "name" in data:
            name_errors = self._validate_name(data.get("name"))
            errors.extend(name_errors)
            if not name_errors:
                cleaned["name"] = data["name"].strip()
        if "description" in data:
            desc_errors = self._validate_description(data.get("description"))
            errors.extend(desc_errors)
            if not desc_errors:
                cleaned["description"] = self._clean_description(data.get("description"))
        if "permissions" in data:
            permissions, audit_history_days, perm_errors = self._validate_permissions(
                data.get("permissions")
            )
            errors.extend(perm_errors)
            if not perm_errors:
                cleaned["permissions"] = permissions
                cleaned["audit_history_days"] = audit_history_days
        self._raise_if_any(errors)
        return cleaned

    # ---- field helpers ----

    def _validate_name(self, value: Any) -> list[FieldError]:
        errors = self._require_nonblank_string("name", value)
        if errors:
            return errors
        trimmed = value.strip()
        if len(trimmed) == 0:
            return [FieldError("name", value, "Must not be blank.")]
        if len(trimmed) > _MAX_NAME:
            return [FieldError("name", value, f"Must be {_MAX_NAME} characters or fewer.")]
        if trimmed.lower() in _RESERVED_NAMES:
            return [FieldError("name", value, "This name is reserved for built-in roles.")]
        return []

    def _validate_description(self, value: Any) -> list[FieldError]:
        if value is None:
            return []
        if not isinstance(value, str):
            return [FieldError("description", value, "Must be a string or null.")]
        if len(value) > _MAX_DESCRIPTION:
            return [
                FieldError(
                    "description",
                    value,
                    f"Must be {_MAX_DESCRIPTION} characters or fewer.",
                )
            ]
        return []

    @staticmethod
    def _reject_top_level_audit_history_days(data: dict) -> list[FieldError]:
        # Refused rather than ignored: a client still sending the old shape would
        # otherwise reset the role to unlimited on every permissions save.
        if _AUDIT_HISTORY_DAYS in data:
            return [
                FieldError(
                    _AUDIT_HISTORY_DAYS,
                    data[_AUDIT_HISTORY_DAYS],
                    "Moved: send audit_history_days inside the audit permission entry.",
                )
            ]
        return []

    @staticmethod
    def _validate_audit_history_days(
        field: str, entry: dict, resource_type: str, bitmask: int
    ) -> list[FieldError]:
        if _AUDIT_HISTORY_DAYS not in entry:
            return []
        value = entry[_AUDIT_HISTORY_DAYS]
        where = f"{field}.{_AUDIT_HISTORY_DAYS}"
        if resource_type != ResourceType.AUDIT.value:
            return [FieldError(where, value, "Only the audit entry accepts audit_history_days.")]
        # bool is an int subclass; reject it so `true` is not stored as 1 day.
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not UNLIMITED <= value <= AUDIT_HISTORY_DAYS_MAX
        ):
            return [
                FieldError(
                    where,
                    value,
                    f"Must be an integer from 0 (unlimited) to {AUDIT_HISTORY_DAYS_MAX}.",
                )
            ]
        if value != UNLIMITED and not grants_audit({resource_type: bitmask}):
            return [
                FieldError(
                    where, value, "A history limit needs the read or export action on audit."
                )
            ]
        return []

    @staticmethod
    def _clean_description(value: Any) -> Any:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    def _validate_permissions(self, value: Any) -> tuple[list[dict], int, list[FieldError]]:
        """Return the cleaned `[{resource_type, bitmask}]` list, the audit
        history limit from the audit entry (0 when absent), and the errors."""
        if value is None:
            return [], UNLIMITED, []
        if not isinstance(value, list):
            return [], UNLIMITED, [FieldError("permissions", value, "Must be a list.")]

        cleaned: list[dict] = []
        audit_history_days = UNLIMITED
        errors: list[FieldError] = []
        seen_resource_types: set = set()
        for index, entry in enumerate(value):
            field = f"permissions[{index}]"
            if not isinstance(entry, dict):
                errors.append(FieldError(field, entry, "Must be an object."))
                continue
            resource_type = entry.get("resource_type")
            actions = entry.get("actions", [])
            applicable = applicable_actions_for(resource_type) if resource_type else []
            if not applicable:
                errors.append(
                    FieldError(
                        f"{field}.resource_type",
                        resource_type,
                        "Unknown resource type.",
                    )
                )
                continue
            if resource_type in seen_resource_types:
                errors.append(
                    FieldError(
                        f"{field}.resource_type",
                        resource_type,
                        "Duplicate resource_type; list each resource at most once.",
                    )
                )
                continue
            seen_resource_types.add(resource_type)
            if not isinstance(actions, list):
                errors.append(FieldError(f"{field}.actions", actions, "Must be a list."))
                continue
            platform = platform_actions_for(resource_type)
            bad_platform = [a for a in actions if a in platform]
            if bad_platform:
                errors.append(
                    FieldError(
                        f"{field}.{resource_type}.actions",
                        actions,
                        f"Actions {bad_platform} are platform-level (superadmin-only) "
                        f"and cannot be granted.",
                    )
                )
                continue
            bad = [a for a in actions if a not in applicable]
            if bad:
                errors.append(
                    FieldError(
                        f"{field}.{resource_type}.actions",
                        actions,
                        f"Actions {bad} are not applicable to {resource_type}.",
                    )
                )
                continue
            bitmask = actions_to_bitmask(actions)
            days_errors = self._validate_audit_history_days(field, entry, resource_type, bitmask)
            if days_errors:
                errors.extend(days_errors)
                continue
            if resource_type == ResourceType.AUDIT.value:
                audit_history_days = entry.get(_AUDIT_HISTORY_DAYS, UNLIMITED)
            if bitmask != 0:
                cleaned.append({"resource_type": resource_type, "bitmask": bitmask})
        return cleaned, audit_history_days, errors
