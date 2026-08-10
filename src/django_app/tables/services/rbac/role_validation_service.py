from typing import Any

from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.rbac.base_rbac_validator import BaseRBACValidator, FieldError
from tables.services.rbac.permission_catalog import applicable_actions_for
from tables.services.rbac.utils.permission_bitmask import actions_to_bitmask

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


class RoleValidationService(BaseRBACValidator):
    """Static validation for custom-role write payloads. Uniqueness and
    the ceiling/authorization rules are enforced in RoleManagementService
    (they need DB + caller context). Returns cleaned payloads with
    action-code lists already converted to per-resource bitmasks."""

    def validate_create(self, data: dict) -> dict:
        errors: list[FieldError] = []
        errors.extend(self._validate_positive_int_field("org_id", data.get("org_id")))
        errors.extend(self._validate_name(data.get("name")))
        errors.extend(self._validate_description(data.get("description")))
        permissions, perm_errors = self._validate_permissions(data.get("permissions"))
        errors.extend(perm_errors)
        self._raise_if_any(errors)
        return {
            "org_id": int(data["org_id"]),
            "name": data["name"].strip(),
            "description": self._clean_description(data.get("description")),
            "permissions": permissions,
        }

    def validate_update(self, data: dict) -> dict:
        cleaned: dict = {}
        errors: list[FieldError] = []
        if "name" in data:
            name_errors = self._validate_name(data.get("name"))
            errors.extend(name_errors)
            if not name_errors:
                cleaned["name"] = data["name"].strip()
        if "description" in data:
            desc_errors = self._validate_description(data.get("description"))
            errors.extend(desc_errors)
            if not desc_errors:
                cleaned["description"] = self._clean_description(
                    data.get("description")
                )
        if "permissions" in data:
            permissions, perm_errors = self._validate_permissions(
                data.get("permissions")
            )
            errors.extend(perm_errors)
            if not perm_errors:
                cleaned["permissions"] = permissions
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
            return [
                FieldError("name", value, f"Must be {_MAX_NAME} characters or fewer.")
            ]
        if trimmed.lower() in _RESERVED_NAMES:
            return [
                FieldError("name", value, "This name is reserved for built-in roles.")
            ]
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
    def _clean_description(value: Any) -> Any:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    def _validate_permissions(self, value: Any) -> tuple[list[dict], list[FieldError]]:
        if value is None:
            return [], []
        if not isinstance(value, list):
            return [], [FieldError("permissions", value, "Must be a list.")]

        cleaned: list[dict] = []
        errors: list[FieldError] = []
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
            if not isinstance(actions, list):
                errors.append(
                    FieldError(f"{field}.actions", actions, "Must be a list.")
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
            if bitmask != 0:
                cleaned.append({"resource_type": resource_type, "bitmask": bitmask})
        return cleaned, errors
