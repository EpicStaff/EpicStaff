from typing import Any

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
        return {"name": self._require_name(data.get("name"))}

    def validate_rename(self, data: dict) -> dict:
        return {"name": self._require_name(data.get("name"))}

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
