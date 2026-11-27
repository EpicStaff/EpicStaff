import re
from datetime import time
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

DASHBOARD_SCHEDULE_FIELDS = ("dashboard_refresh_minutes", "dashboard_refresh_daily_at")
DAILY_AT_PATTERN = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


class OrganizationRetentionValidationService(BaseRBACValidator):
    """Validates the organization retention PATCH body against the instance policy.

    Raises `FormValidationError` with one `FieldError` per rejected field; the message
    names the rejected fields as well.
    """

    def validate_update(
        self, data: Any, current: OrganizationConfig
    ) -> tuple[dict[DataType, int | None], dict[str, int | time | None]]:
        """Return the sent retention values keyed by data type, and the sent dashboard
        schedule keyed by OrganizationConfig field.

        A value is accepted when it is null (the instance default), one of the values the
        policy allows, or the value the organization already stores. The last case keeps a
        form re-savable after an operator lowers a cap or raises a floor past an earlier
        choice; the cap and floor still apply through `effective_retention_days`. The
        dashboard interval follows the same rule against the DASHBOARD_REFRESH_MINUTES_*
        bounds.

        Args:
            current: The organization's stored config, locked by the caller.
        """
        fields = REQUEST_FIELD_BY_DATA_TYPE
        accepted = [*fields.values(), *DASHBOARD_SCHEDULE_FIELDS]
        if not isinstance(data, dict) or not any(name in data for name in accepted):
            self._raise([FieldError("body", None, f"Send at least one of: {', '.join(accepted)}.")])

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
        schedule = self._dashboard_schedule(data, current, errors)
        self._raise(errors)
        return values, schedule

    def _dashboard_schedule(
        self, data: dict, current: OrganizationConfig, errors: list[FieldError]
    ) -> dict[str, int | time | None]:
        schedule: dict[str, int | time | None] = {}
        if "dashboard_refresh_minutes" in data:
            minutes = data["dashboard_refresh_minutes"]
            error = self._refresh_minutes_error(minutes, current)
            if error is not None:
                errors.append(error)
            schedule["dashboard_refresh_minutes"] = minutes
        if "dashboard_refresh_daily_at" in data:
            value = data["dashboard_refresh_daily_at"]
            daily_at = self._daily_at(value)
            if value is not None and daily_at is None:
                errors.append(
                    FieldError(
                        "dashboard_refresh_daily_at",
                        value,
                        "Must be a UTC time as HH:MM, or null.",
                    )
                )
            schedule["dashboard_refresh_daily_at"] = daily_at
        minutes = schedule.get("dashboard_refresh_minutes", current.dashboard_refresh_minutes)
        daily_at = schedule.get("dashboard_refresh_daily_at", current.dashboard_refresh_daily_at)
        if minutes is not None and daily_at is not None:
            errors.append(
                FieldError(
                    "body",
                    None,
                    "Choose either dashboard_refresh_minutes or dashboard_refresh_daily_at, not both.",
                )
            )
        return schedule

    @staticmethod
    def _refresh_minutes_error(value: Any, current: OrganizationConfig) -> FieldError | None:
        if value is None:
            return None
        low, high = settings.DASHBOARD_REFRESH_MINUTES_MIN, settings.DASHBOARD_REFRESH_MINUTES_MAX
        error = FieldError(
            "dashboard_refresh_minutes",
            value,
            f"Must be a whole number from {low} to {high}, or null for the default.",
        )
        if not isinstance(value, int) or isinstance(value, bool):
            return error
        if value == current.dashboard_refresh_minutes or low <= value <= high:
            return None
        return error

    @staticmethod
    def _daily_at(value: Any) -> time | None:
        if not isinstance(value, str) or not DAILY_AT_PATTERN.fullmatch(value):
            return None
        return time.fromisoformat(value)

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
