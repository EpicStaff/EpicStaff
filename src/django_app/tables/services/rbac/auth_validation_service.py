from dataclasses import asdict, dataclass
from typing import Any, Optional

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email

from tables.services.rbac.rbac_exceptions import FormValidationError


REDACTED_FIELDS: frozenset[str] = frozenset(
    {"password", "new_password", "refresh", "token", "access"}
)
REDACTED_PLACEHOLDER = "***"
NON_FIELD_KEY = "non_field_errors"


@dataclass
class FieldError:
    field: str
    value: Any
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class AuthValidationService:
    """
    Aggregating validator for the auth surface.

    Each `validate_*` method runs every applicable check, collects every
    failure as a `FieldError`, and — only after all fields have been
    checked — raises a single `FormValidationError` carrying the full
    list. It never short-circuits on the first failure.

    On success the cleaned payload is returned to the caller. Sensitive
    submitted values (password/refresh/token) are redacted before being
    echoed back in the error body; non-sensitive values (email) are
    echoed as-is so the FE can highlight the offending input.

    Authentication failures (wrong email/password combination) are NOT
    reported per-field and are not the responsibility of this service —
    they remain a flat 401 to avoid user-enumeration leaks.
    """

    def validate_first_setup(self, data: dict) -> dict:
        email = data.get("email")
        password = data.get("password")

        errors: list[FieldError] = []
        errors.extend(self._validate_email_field(email))
        errors.extend(
            self._validate_password_field(password, user_hints={"email": email})
        )

        self._raise_if_any(errors)
        return {"email": email, "password": password}

    def validate_reset_user(self, data: dict) -> dict:
        # Same field contract as first-setup; kept as a distinct method
        # so callers express intent and so future divergence (e.g. a
        # confirmation field) lands in one obvious place.
        return self.validate_first_setup(data)

    def validate_login(self, data: dict) -> dict:
        email = data.get("email")
        password = data.get("password")

        errors: list[FieldError] = []
        errors.extend(self._require_nonblank_string("email", email))
        errors.extend(self._require_nonblank_string("password", password))

        self._raise_if_any(errors)
        return {"email": email, "password": password}

    # field-level checks

    def _validate_email_field(self, value: Any) -> list[FieldError]:
        required = self._require_nonblank_string("email", value)
        if required:
            return required
        try:
            validate_email(value)
        except DjangoValidationError as exc:
            return [
                FieldError("email", self._echo("email", value), msg)
                for msg in exc.messages
            ]
        return []

    def _validate_password_field(
        self, value: Any, user_hints: Optional[dict] = None
    ) -> list[FieldError]:
        required = self._require_nonblank_string("password", value)
        if required:
            return required
        # `UserAttributeSimilarityValidator` only runs when `user=` is
        # passed, and since Django 5.1 it calls `user._meta.get_field(...)`
        # to render its error — so a plain namespace is not enough. An
        # *unsaved* User instance gives us `_meta` without touching the DB.
        user_stub = get_user_model()(**(user_hints or {}))
        try:
            validate_password(value, user=user_stub)
        except DjangoValidationError as exc:
            return [
                FieldError("password", self._echo("password", value), msg)
                for msg in exc.messages
            ]
        return []

    # ---- primitives ----

    def _require_nonblank_string(self, field: str, value: Any) -> list[FieldError]:
        if value is None or value == "":
            return [
                FieldError(field, self._echo(field, value), "This field is required.")
            ]
        if not isinstance(value, str):
            return [FieldError(field, self._echo(field, value), "Must be a string.")]
        return []

    @staticmethod
    def _echo(field: str, value: Any) -> Any:
        if field in REDACTED_FIELDS:
            return REDACTED_PLACEHOLDER
        return value

    @staticmethod
    def _raise_if_any(errors: list[FieldError]) -> None:
        if errors:
            raise FormValidationError([e.to_dict() for e in errors])
