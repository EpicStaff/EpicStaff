import re
from abc import ABC
from dataclasses import asdict, dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from tables.models.user import DISPLAY_NAME_MAX_LENGTH

from rbac.exceptions import FormValidationError

REDACTED_PLACEHOLDER = "***"

# RFC 5321 limits: 64 characters before the @, 254 for the whole address.
EMAIL_LOCAL_PART_MAX_LENGTH = 64
EMAIL_MAX_LENGTH = 254

# Product rule, stricter than RFC 5322: only symbols common providers allow.
_EMAIL_LOCAL_PART_CHARACTERS = re.compile(r"[A-Za-z0-9._+-]+")

# Product rule: blocks "---@", "+john@", "__proto__@".
_EMAIL_LOCAL_PART_EDGES = re.compile(r"[A-Za-z0-9](?:.*[A-Za-z0-9])?")

# ASCII hostname labels ending in a top-level domain of 2+ letters.
_EMAIL_DOMAIN = re.compile(r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,63}")


@dataclass
class FieldError:
    field: str
    value: Any
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


class BaseRBACValidator(ABC):
    """Shared infrastructure for every RBAC-domain form validator.

    Concrete subclasses expose their own `validate_*` methods, reusing the
    protected primitives below. They override `_redacted_fields` to declare
    which submitted values must never be echoed back in error responses
    (passwords, tokens, refresh tokens — never org names).

    Each subclass `validate_*` method:
      - aggregates every applicable check into a list of FieldError
      - never short-circuits on the first failure
      - raises a single FormValidationError with the full list at the end
      - returns the cleaned payload on success

    `ABC` is used to signal "do not instantiate directly", even though no
    method is `@abstractmethod` — there is no uniform `validate(...)`
    signature across subclasses. Concrete bases would also work; ABC
    documents intent.
    """

    _redacted_fields: frozenset[str] = frozenset()

    # ---- error envelope ----

    def _raise_if_any(self, errors: list[FieldError]) -> None:
        if errors:
            raise FormValidationError([e.to_dict() for e in errors])

    def _echo(self, field: str, value: Any) -> Any:
        if field in self._redacted_fields:
            return REDACTED_PLACEHOLDER
        return value

    # ---- primitives ----

    def _require_nonblank_string(self, field: str, value: Any) -> list[FieldError]:
        if value is None or value == "":
            return [FieldError(field, self._echo(field, value), "This field is required.")]
        if not isinstance(value, str):
            return [FieldError(field, self._echo(field, value), "Must be a string.")]
        return []

    def _validate_email_field(self, value: Any) -> list[FieldError]:
        required = self._require_nonblank_string("email", value)
        if required:
            return required
        if re.search(r"\s", value):
            return [
                FieldError(
                    "email",
                    self._echo("email", value),
                    "Email must not contain whitespace.",
                )
            ]
        try:
            validate_email(value)
        except DjangoValidationError as exc:
            return [FieldError("email", self._echo("email", value), msg) for msg in exc.messages]
        return []

    def _validate_new_account_email(self, value: Any) -> list[FieldError]:
        """Validate a new account's email; lookups keep `_validate_email_field` for old accounts."""
        errors = self._validate_email_field(value)
        if errors:
            return errors
        local_part, _, domain = value.rpartition("@")
        if len(value) > EMAIL_MAX_LENGTH or len(local_part) > EMAIL_LOCAL_PART_MAX_LENGTH:
            reason = (
                f"Must be at most {EMAIL_MAX_LENGTH} characters, "
                f"with at most {EMAIL_LOCAL_PART_MAX_LENGTH} before the @."
            )
        elif not _EMAIL_LOCAL_PART_CHARACTERS.fullmatch(local_part):
            reason = "Use only letters, digits and . _ - + before the @."
        elif not _EMAIL_LOCAL_PART_EDGES.fullmatch(local_part):
            reason = "The part before @ must start and end with a letter or digit."
        elif not _EMAIL_DOMAIN.fullmatch(domain):
            reason = "Enter a valid email address."
        else:
            return []
        return [FieldError("email", self._echo("email", value), reason)]

    def _validate_password_field(
        self,
        value: Any,
        user_hints: dict | None = None,
        field_name: str = "password",
    ) -> list[FieldError]:
        required = self._require_nonblank_string(field_name, value)
        if required:
            return required
        # `UserAttributeSimilarityValidator` only runs when `user=` is passed,
        # and since Django 5.1 it calls `user._meta.get_field(...)` to render
        # its error — so a plain namespace is not enough. An *unsaved* User
        # instance gives us `_meta` without touching the DB.
        user_stub = get_user_model()(**(user_hints or {}))
        try:
            validate_password(value, user=user_stub)
        except DjangoValidationError as exc:
            return [
                FieldError(field_name, self._echo(field_name, value), msg) for msg in exc.messages
            ]
        return []

    def _clean_display_name(
        self,
        value: Any,
        *,
        blank_reason: str = "Must not be blank. Omit it or use null to derive it from the email.",
    ) -> tuple[str | None, list[FieldError]]:
        # None passes through: creation derives a name from it, profile PATCH clears the name.
        if value is None:
            return None, []
        if not isinstance(value, str):
            return None, [
                FieldError(
                    "display_name",
                    self._echo("display_name", value),
                    "Must be a string or null.",
                )
            ]
        trimmed = value.strip()
        if not trimmed:
            return None, [
                FieldError("display_name", self._echo("display_name", value), blank_reason)
            ]
        if len(trimmed) > DISPLAY_NAME_MAX_LENGTH:
            return None, [
                FieldError(
                    "display_name",
                    self._echo("display_name", value),
                    f"Must be {DISPLAY_NAME_MAX_LENGTH} characters or fewer.",
                )
            ]
        return trimmed, []

    def _validate_positive_int_field(self, field: str, value: Any) -> list[FieldError]:
        if value is None or value == "":
            return [FieldError(field, self._echo(field, value), "This field is required.")]
        try:
            coerced = int(value)
        except (TypeError, ValueError):
            return [FieldError(field, self._echo(field, value), "Must be an integer.")]
        if coerced <= 0:
            return [FieldError(field, self._echo(field, value), "Must be a positive integer.")]
        return []
