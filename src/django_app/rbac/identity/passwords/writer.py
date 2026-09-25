class PasswordWriter:
    """Sets a user's password hash and persists it.

    Extracted from the orchestrator so the single place that mutates
    `User.password` is easy to audit — and so an audit-logging variant
    can be swapped in later without touching the orchestrator (OCP).
    """

    def set(self, user, raw_password: str) -> None:
        user.set_password(raw_password)
        user.save(update_fields=["password"])
