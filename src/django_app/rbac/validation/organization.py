from typing import Any

from rbac.serializers.organizations import AUDIT_RETENTION_DAYS_MAX
from rbac.validation.base import BaseRBACValidator, FieldError

ORG_NAME_MAX_LENGTH = 255


class OrganizationValidationService(BaseRBACValidator):
    """Validates request payloads for organization create/rename.

    Inherits an empty `_redacted_fields` from the base — organization names
    are not sensitive and are echoed back to the FE in the standard
    FormValidationError envelope to help users locate their typos.

    Public methods accept the raw `request.data` dict, return the cleaned
    payload on success, and raise `FormValidationError` (with structured
    `errors[]`) on failure.
    """

    def validate_create(self, data: dict) -> dict:
        name = self._require_name(data.get("name"))
        return {
            "name": name,
            "audit_retention_days": self._audit_retention_days(data.get("audit_retention_days", 0)),
        }

    def validate_rename(self, data: dict) -> dict:
        """Clean a PATCH body: `name` and `audit_retention_days` are each optional, but one is required.

        A body with neither keeps the original rename contract (a `name` error).
        """
        cleaned = {}
        if "audit_retention_days" in data:
            cleaned["audit_retention_days"] = self._audit_retention_days(
                data["audit_retention_days"]
            )
        if "name" in data or not cleaned:
            cleaned["name"] = self._require_name(data.get("name"))
        return cleaned

    def _audit_retention_days(self, value: Any) -> int:
        # bool is an int subclass; reject it so `true` is not stored as 1 day.
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 0 <= value <= AUDIT_RETENTION_DAYS_MAX
        ):
            self._raise_if_any(
                [
                    FieldError(
                        "audit_retention_days",
                        value,
                        f"Must be an integer from 0 (unlimited) to {AUDIT_RETENTION_DAYS_MAX}.",
                    )
                ]
            )
        return value

    def _require_name(self, value: Any) -> str:
        errors: list[FieldError] = []
        if value is None or not isinstance(value, str):
            errors.append(FieldError("name", value, "Must be a string."))
            self._raise_if_any(errors)

        stripped = value.strip()
        if not stripped:
            errors.append(FieldError("name", value, "This field is required."))
        elif len(stripped) > ORG_NAME_MAX_LENGTH:
            errors.append(
                FieldError(
                    "name",
                    value,
                    f"Must be at most {ORG_NAME_MAX_LENGTH} characters.",
                )
            )

        self._raise_if_any(errors)
        return stripped
