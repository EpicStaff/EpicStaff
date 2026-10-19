from typing import Any

from django.conf import settings
from src.shared.retention import DataType, allowed_org_values

from rbac.exceptions import FormValidationError
from rbac.models import OrganizationRetention
from rbac.validation.base import BaseRBACValidator, FieldError


class OrganizationRetentionValidationService(BaseRBACValidator):
    """Validates the organization retention PATCH body against the instance policy.

    Raises `FormValidationError` with one `FieldError` per rejected field; the message
    names the rejected fields as well.
    """

    def validate_update(
        self, data: Any, current: OrganizationRetention
    ) -> dict[DataType, int | None]:
        """Return the sent values keyed by data type.

        A value is accepted when it is null (the instance default), one of the values the
        policy allows, or the value the organization already stores. The last case keeps a
        form re-savable after an operator lowers a cap below an earlier choice; the cap
        still applies through `effective_days`.

        Args:
            current: The organization's stored retention, or an unsaved empty one.
        """
        fields = OrganizationRetention.FIELD_BY_DATA_TYPE
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
        field_name: str, value: Any, data_type: DataType, current: OrganizationRetention
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
        if value == current.chosen_days(data_type) or value in allowed:
            return None
        return error

    @staticmethod
    def _raise(errors: list[FieldError]) -> None:
        if errors:
            raise FormValidationError(
                [error.to_dict() for error in errors],
                detail="Invalid " + ", ".join(error.field for error in errors) + ".",
            )
