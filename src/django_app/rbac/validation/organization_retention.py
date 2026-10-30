from typing import Any

from django.conf import settings
from src.shared.retention import DataType, allowed_org_values

from rbac.exceptions import FormValidationError
from rbac.models import OrganizationConfig
from rbac.validation.base import BaseRBACValidator, FieldError

# The PATCH body's field names; the model stores them as `retention_<name>`. Keep in step
# with OrganizationConfig.RETENTION_FIELD_BY_DATA_TYPE and the `source=` arguments in
# rbac/serializers/organization_retention.py.
REQUEST_FIELD_BY_DATA_TYPE: dict[DataType, str] = {
    DataType.SESSIONS: "sessions_days",
    DataType.CONVERSATIONS: "conversations_days",
    DataType.AUDIT: "audit_days",
}


class OrganizationRetentionValidationService(BaseRBACValidator):
    """Validates the organization retention PATCH body against the instance policy.

    Raises `FormValidationError` with one `FieldError` per rejected field; the message
    names the rejected fields as well.
    """

    def validate_update(self, data: Any, current: OrganizationConfig) -> dict[DataType, int | None]:
        """Return the sent values keyed by data type.

        A value is accepted when it is null (the instance default), one of the values the
        policy allows, or the value the organization already stores. The last case keeps a
        form re-savable after an operator lowers a cap or raises a floor past an earlier
        choice; the cap and floor still apply through `effective_retention_days`.

        Args:
            current: The organization's stored config, locked by the caller.
        """
        fields = REQUEST_FIELD_BY_DATA_TYPE
        if not isinstance(data, dict) or not any(name in data for name in fields.values()):
            self._raise(
                [FieldError("body", None, f"Send at least one of: {', '.join(fields.values())}.")]
            )

        errors: list[FieldError] = []
        values: dict[DataType, int | None] = {}
        for data_type, field_name in fields.items():
            if field_name not in data:
                continue
            value = data[field_name]
            error = self._retention_days_error(field_name, value, data_type, current)
            if error is not None:
                errors.append(error)
            values[data_type] = value
        self._raise(errors)
        return values

    @staticmethod
    def _retention_days_error(
        field_name: str, value: Any, data_type: DataType, current: OrganizationConfig
    ) -> FieldError | None:
        if value is None:
            return None
        # The policy is read per request: it differs between deployments and tests.
        allowed = list(allowed_org_values(settings.RETENTION_POLICY.rules[data_type]))
        error = FieldError(
            field_name, value, f"Must be one of {allowed}, or null for the instance default."
        )
        # Type first: bool is an int subclass and 30.0 == 30, so the comparisons below
        # would otherwise accept `true` or a float.
        if not isinstance(value, int) or isinstance(value, bool):
            return error
        if value == current.chosen_retention_days(data_type) or value in allowed:
            return None
        return error

    @staticmethod
    def _raise(errors: list[FieldError]) -> None:
        if errors:
            raise FormValidationError(
                [error.to_dict() for error in errors],
                detail="Invalid " + ", ".join(error.field for error in errors) + ".",
            )
