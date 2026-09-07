from django.core.exceptions import ImproperlyConfigured


class FirstSetupMode:
    """Valid values for ``settings.FIRST_SETUP_MODE``.

    Which of the two superadmin-creation paths is live on this deployment:

    - ``cli_only`` (default): ``POST /api/auth/first-setup/`` is refused.
      The superadmin comes from ``manage.py create_superadmin``. Required
      for any internet-exposed deployment, because the HTTP endpoint is
      anonymous and would otherwise be claimable by whoever reaches it
      first.
    - ``open``: the HTTP endpoint creates the first superadmin. Intended
      for local development.

    Callers ask :meth:`is_http_allowed` rather than comparing strings, so
    adding a future mode touches this class only.

    Imported by ``django_app.settings``, so this module must not import
    anything that needs the Django app registry (no models, no ORM).
    """

    CLI_ONLY = "cli_only"
    OPEN = "open"

    CHOICES = frozenset({CLI_ONLY, OPEN})

    @classmethod
    def validate(cls, mode: str) -> str:
        """Return ``mode`` unchanged, or raise if it is not a known value.

        Called from settings at import time so a typo fails the process
        instead of silently selecting a mode.

        Raises:
            ImproperlyConfigured: ``mode`` is not in :attr:`CHOICES`.
        """
        if mode not in cls.CHOICES:
            raise ImproperlyConfigured(
                f"FIRST_SETUP_MODE must be one of "
                f"{sorted(cls.CHOICES)}; got {mode!r}."
            )
        return mode

    @classmethod
    def is_http_allowed(cls, mode: str) -> bool:
        """Whether ``POST /api/auth/first-setup/`` may create a superadmin.

        Fails closed: anything other than :attr:`OPEN` returns False, so an
        unvalidated or unexpected value cannot open the endpoint.
        """
        return mode == cls.OPEN
