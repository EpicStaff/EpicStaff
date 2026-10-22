"""The plugin development mode rule, in one place.

A deployment may run in development mode only when it is a local development deployment:
`DJANGO_DEBUG` is true (the project's "never in production" switch), `PLUGINS_BASE_DOMAIN`
ends in `.localhost`, and the host of `DJANGO_FRONTEND_BASE_URL` is `localhost` or ends in
`.localhost`. Browsers resolve `.localhost` names only to the loopback interface of their own
machine (RFC 6761). The plugins.E012 start-up check refuses the mode anywhere else.

Every development code path calls `development_mode_on()` when it runs, never a cached
value, so turning the flag off makes every stored development target and every development
key inert at once. Runtime paths do not read `DEBUG`: the start-up check is the gate.
"""

from urllib.parse import urlsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from plugins.models.development import MAX_DEVELOPMENT_PORT, MIN_DEVELOPMENT_PORT

LOCALHOST_NAME = "localhost"
LOCALHOST_SUFFIX = ".localhost"
DEVELOPMENT_API_HOST = "127.0.0.1"


def development_mode_on() -> bool:
    return settings.PLUGINS_DEV_MODE


def development_mode_problems() -> list[str]:
    """Each condition of the rule this deployment fails, named for the operator."""
    problems = []
    if not settings.DEBUG:
        problems.append("DJANGO_DEBUG is not true")
    base_domain = settings.PLUGINS_BASE_DOMAIN or ""
    if not base_domain.endswith(LOCALHOST_SUFFIX):
        problems.append(f"PLUGINS_BASE_DOMAIN ({base_domain!r}) does not end in .localhost")
    host = _host_of(settings.FRONTEND_BASE_URL)
    if not is_localhost_name(host):
        problems.append(
            f"the host of DJANGO_FRONTEND_BASE_URL ({host!r}) is neither localhost nor a "
            ".localhost name"
        )
    return problems


def is_localhost_name(host: str | None) -> bool:
    return bool(host) and (host == LOCALHOST_NAME or host.endswith(LOCALHOST_SUFFIX))


def parse_development_port(value) -> int | None:
    """`value` as a port development mode may use (1024-65535), or None.

    Accepts an int or the decimal digits of one, as an environment variable holds it.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text.isascii() or not text.isdigit():
            return None
        value = int(text)
    if not isinstance(value, int):
        return None
    return value if MIN_DEVELOPMENT_PORT <= value <= MAX_DEVELOPMENT_PORT else None


def development_api_port() -> int:
    """`PLUGINS_DEV_API_PORT` as a number.

    Raises:
        ImproperlyConfigured: The value is not a port from 1024 to 65535; the plugins.E013
            start-up check stops such a deployment before it serves anything.
    """
    port = parse_development_port(settings.PLUGINS_DEV_API_PORT)
    if port is None:
        raise ImproperlyConfigured("PLUGINS_DEV_API_PORT is not a port from 1024 to 65535.")
    return port


def development_api_url() -> str:
    """EpicStaff's API as a development backend on the author's machine reaches it."""
    return f"http://{DEVELOPMENT_API_HOST}:{development_api_port()}/api/"


def _host_of(url: str | None) -> str | None:
    try:
        return urlsplit(url or "").hostname
    except ValueError:
        return None
