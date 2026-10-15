from django.core.exceptions import ImproperlyConfigured

from django_app.settings import env

MIN_EXECUTION_TIMEOUT_SECONDS = 3
# The largest value PythonCode.execution_timeout (a Postgres int4) can hold.
STORABLE_EXECUTION_TIMEOUT_SECONDS = 2_147_483_647

_max_execution_timeout = env.time("SANDBOX_EXECUTION_TIMEOUT")
_default_execution_timeout = env.time("SANDBOX_DEFAULT_EXECUTION_TIMEOUT")

if _default_execution_timeout is None:
    raise ImproperlyConfigured("SANDBOX_DEFAULT_EXECUTION_TIMEOUT cannot be none.")

# Whole seconds, rounded down so a stored timeout never exceeds SANDBOX_EXECUTION_TIMEOUT.
# None means no upper limit.
MAX_EXECUTION_TIMEOUT_SECONDS = (
    None if _max_execution_timeout is None else int(_max_execution_timeout)
)
DEFAULT_EXECUTION_TIMEOUT_SECONDS = int(_default_execution_timeout)

if DEFAULT_EXECUTION_TIMEOUT_SECONDS < MIN_EXECUTION_TIMEOUT_SECONDS or (
    MAX_EXECUTION_TIMEOUT_SECONDS is not None
    and DEFAULT_EXECUTION_TIMEOUT_SECONDS > MAX_EXECUTION_TIMEOUT_SECONDS
):
    raise ImproperlyConfigured(
        f"SANDBOX_DEFAULT_EXECUTION_TIMEOUT must be at least {MIN_EXECUTION_TIMEOUT_SECONDS}s "
        "and not above SANDBOX_EXECUTION_TIMEOUT."
    )
