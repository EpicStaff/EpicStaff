from rbac.validation.auth import AuthValidationService


class PasswordWriter:
    """Sets a user's password hash and persists it.

    Extracted from the orchestrator so the single place that mutates
    `User.password` is easy to audit — and so an audit-logging variant
    can be swapped in later without touching the orchestrator (OCP).

    It is also the one place every password-setting flow passes through
    with the real account in hand, so it owns the account-aware strength
    check: request validators run before the account is resolved (a reset
    link's owner is known only once its token is looked up) and so cannot
    reject a password that resembles the account's email.
    """

    def __init__(self, validator: AuthValidationService | None = None):
        self._validator = validator or AuthValidationService()

    def validate(self, user, raw_password: str) -> None:
        """Check `raw_password` against AUTH_PASSWORD_VALIDATORS for `user`.

        Raises:
            FormValidationError: on field `new_password`, value redacted —
                the same 400 envelope the request validators produce.
        """
        self._validator.validate_new_password({"new_password": raw_password}, user=user)

    def set(self, user, raw_password: str) -> None:
        """Validate `raw_password` for `user`, then hash and save it.

        Validation runs before any write, so a caller inside
        `transaction.atomic()` that calls this first leaves the database
        untouched on rejection.

        Raises:
            FormValidationError: the password failed a validator.
        """
        self.validate(user, raw_password)
        user.set_password(raw_password)
        user.save(update_fields=["password"])
