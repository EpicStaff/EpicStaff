import math

from django.core.exceptions import ImproperlyConfigured

from django_app.settings import env

_SECONDS_PER_MINUTE = 60


def max_execution_timeout_minutes(ceiling_seconds: float | None) -> int:
    """Convert the sandbox execution ceiling into the largest per-node timeout in minutes.

    Node timeouts are whole minutes and must never exceed what the sandbox enforces, so a
    ceiling that is not a whole number of minutes is floored. A ceiling that is unlimited or
    shorter than one minute leaves no valid node timeout, so it stops Django from starting.

    Raises:
        ImproperlyConfigured: The ceiling is ``none`` or shorter than one minute.
    """
    if ceiling_seconds is None:
        raise ImproperlyConfigured(
            "SANDBOX_EXECUTION_TIMEOUT=none is not supported: per-node execution timeouts "
            "need a finite ceiling of at least 1 minute."
        )
    if ceiling_seconds < _SECONDS_PER_MINUTE:
        raise ImproperlyConfigured(
            f"SANDBOX_EXECUTION_TIMEOUT must be at least 1 minute, got {ceiling_seconds:g} seconds."
        )
    return math.floor(ceiling_seconds / _SECONDS_PER_MINUTE)


SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = max_execution_timeout_minutes(
    env.time("SANDBOX_EXECUTION_TIMEOUT")
)
