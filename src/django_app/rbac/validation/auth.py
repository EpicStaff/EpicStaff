from rbac.validation.base import BaseRBACValidator, FieldError


class AuthValidationService(BaseRBACValidator):
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

    _redacted_fields = frozenset(
        {"password", "new_password", "current_password", "refresh", "token", "access"}
    )

    def validate_first_setup(self, data: dict) -> dict:
        email = data.get("email")
        password = data.get("password")

        errors: list[FieldError] = []
        errors.extend(self._validate_new_account_email(email))
        errors.extend(self._validate_password_field(password, user=self._prospective_user(email)))
        display_name, display_name_errors = self._clean_display_name(data.get("display_name"))
        errors.extend(display_name_errors)

        self._raise_if_any(errors)
        return {"email": email, "password": password, "display_name": display_name}

    def validate_reset_user(self, data: dict) -> dict:
        # Same field contract as first-setup; kept as a distinct method
        # so callers express intent and so future divergence (e.g. a
        # confirmation field) lands in one obvious place.
        return self.validate_first_setup(data)

    def validate_password_reset_request(self, data: dict) -> dict:
        email = data.get("email")

        errors: list[FieldError] = []
        errors.extend(self._validate_email_field(email))

        self._raise_if_any(errors)
        return {"email": email}

    def validate_password_reset_confirm(self, data: dict) -> dict:
        token = data.get("token")
        new_password = data.get("new_password")

        errors: list[FieldError] = []
        errors.extend(self._require_nonblank_string("token", token))
        errors.extend(
            self._validate_password_field(new_password, user=None, field_name="new_password")
        )

        self._raise_if_any(errors)
        return {"token": token, "new_password": new_password}

    def validate_admin_password_reset(self, data: dict) -> dict:
        user_id = data.get("user_id")
        new_password = data.get("new_password")

        errors: list[FieldError] = []
        errors.extend(self._validate_positive_int_field("user_id", user_id))
        errors.extend(
            self._validate_password_field(new_password, user=None, field_name="new_password")
        )

        self._raise_if_any(errors)
        return {"user_id": int(user_id), "new_password": new_password}

    def validate_login(self, data: dict) -> dict:
        email = data.get("email")
        password = data.get("password")

        errors: list[FieldError] = []
        errors.extend(self._require_nonblank_string("email", email))
        errors.extend(self._require_nonblank_string("password", password))

        self._raise_if_any(errors)
        return {"email": email, "password": password}

    def validate_new_password(self, data: dict, *, user) -> dict:
        """Validate `new_password` against the account it is about to be set on.

        Used by `PasswordWriter`, the one place every password-setting flow
        passes through with the real account in hand.

        Raises:
            FormValidationError: the password failed one or more validators.
        """
        new_password = data.get("new_password")

        errors: list[FieldError] = []
        errors.extend(
            self._validate_password_field(new_password, field_name="new_password", user=user)
        )

        self._raise_if_any(errors)
        return {"new_password": new_password}
