"""Start-up checks for the plugin platform, run only while `PLUGINS_ENABLED` is true.

They are Django system checks of level Error, so every management command the container
runs at start-up (`check_db_init`, `migrate`) stops before the server starts.
"""

import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core import checks
from epicstaff_plugin.signing import SignatureFormatError, parse_trusted_keys

HTTPS_REQUIRED_CHECK_ID = "plugins.E001"
BASE_DOMAIN_CHECK_ID = "plugins.E002"
FRONTEND_ORIGIN_CHECK_ID = "plugins.E003"
TRUSTED_KEYS_CHECK_ID = "plugins.E004"
CORS_ORIGINS_CHECK_ID = "plugins.E005"

LOCAL_DEVELOPMENT_SUFFIX = ".localhost"
PLACEHOLDER_SUFFIX = ".invalid"
_DNS_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_DNS_NAME_LENGTH = 253
_HOST_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
# The whole URL, matched in full: urlsplit accepts characters a host cannot have, and the
# origin is written into nginx's configuration.
_HTTP_ORIGIN = re.compile(
    rf"(?P<scheme>[Hh][Tt][Tt][Pp][Ss]?)://(?P<host>{_HOST_LABEL}(?:\.{_HOST_LABEL})*)"
    r"(?::(?P<port>[0-9]{1,5}))?/?"
)
# A last label browsers read as a number makes the host an IP address (10.0.0.1, 0x7f000001).
_NUMERIC_LABEL = re.compile(r"(?:[0-9]+|0[xX][0-9A-Fa-f]*)")


@checks.register("plugins")
def check_plugin_platform_settings(app_configs, **kwargs) -> list[checks.Error]:
    """Refuse a plugin platform that would run over plain http or with broken host settings."""
    if not settings.PLUGINS_ENABLED:
        return []
    return [
        *_https_errors(),
        *_base_domain_errors(),
        *_frontend_origin_errors(),
        *_trusted_key_errors(),
        *_cors_errors(),
    ]


def _is_local_development(host: str | None) -> bool:
    return bool(host) and host.endswith(LOCAL_DEVELOPMENT_SUFFIX)


def _https_errors() -> list[checks.Error]:
    # Over plain http a plugin page can plant a copy of EpicStaff's login cookie, so plain http
    # is allowed only for *.localhost development.
    if settings.REFRESH_COOKIE_SECURE or _is_local_development(settings.PLUGINS_BASE_DOMAIN):
        return []
    return [
        checks.Error(
            "The plugin platform needs HTTPS: DJANGO_REFRESH_COOKIE_SECURE is false and "
            f"PLUGINS_BASE_DOMAIN ({settings.PLUGINS_BASE_DOMAIN!r}) does not end in .localhost.",
            hint=(
                "Serve EpicStaff over HTTPS and set DJANGO_REFRESH_COOKIE_SECURE=true, or use a "
                "*.localhost base domain for local development, or set PLUGINS_ENABLED=false."
            ),
            id=HTTPS_REQUIRED_CHECK_ID,
        )
    ]


def _base_domain_errors() -> list[checks.Error]:
    domain = settings.PLUGINS_BASE_DOMAIN
    if not _is_dns_name(domain):
        message = (
            f"PLUGINS_BASE_DOMAIN ({domain!r}) is not a lower-case DNS name such as "
            "plugins.example.com."
        )
    elif domain.endswith(PLACEHOLDER_SUFFIX):
        message = f"PLUGINS_BASE_DOMAIN ({domain!r}) is still a placeholder."
    else:
        return []
    return [
        checks.Error(
            message,
            hint=(
                "Set it to the parent domain of the plugin hosts, the one the wildcard DNS record "
                "*.<domain> points at."
            ),
            id=BASE_DOMAIN_CHECK_ID,
        )
    ]


def _is_dns_name(domain: str | None) -> bool:
    if not domain or len(domain) > _MAX_DNS_NAME_LENGTH:
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and all(_DNS_LABEL.match(label) for label in labels)


def _frontend_origin_errors() -> list[checks.Error]:
    url = settings.FRONTEND_BASE_URL
    origin = _http_origin(url)
    if origin is None:
        message = (
            f"DJANGO_FRONTEND_BASE_URL ({url!r}) is not an http(s) origin with a host name (not "
            "an IP address) and an optional port, such as https://epicstaff.example.com."
        )
    elif origin[0] == "http" and not _is_local_development(origin[1]):
        message = (
            f"DJANGO_FRONTEND_BASE_URL ({url!r}) uses http, which the plugin platform allows "
            "only for a .localhost host."
        )
    else:
        return []
    return [
        checks.Error(
            message,
            hint="Plugin frames and their messages are checked against this origin.",
            id=FRONTEND_ORIGIN_CHECK_ID,
        )
    ]


def _http_origin(url: str) -> tuple[str, str] | None:
    """Return `(scheme, host)` when `url` is an http(s) origin with a host name.

    Only a host name of letters, digits and hyphens is accepted (no IP address), with an
    optional port and at most a trailing "/", the same as nginx's start-up script accepts.
    """
    match = _HTTP_ORIGIN.fullmatch(url)
    if match is None:
        return None
    host = match["host"].lower()
    port = match["port"]
    if _NUMERIC_LABEL.fullmatch(host.rsplit(".", 1)[-1]) or len(host) > _MAX_DNS_NAME_LENGTH:
        return None
    if port is not None and not 0 < int(port) < 65536:
        return None
    return match["scheme"].lower(), host


def _trusted_key_errors() -> list[checks.Error]:
    try:
        parse_trusted_keys(settings.PLUGINS_TRUSTED_SIGNING_KEYS)
    except SignatureFormatError as error:
        return [
            checks.Error(
                f"PLUGINS_TRUSTED_SIGNING_KEYS: {error}.",
                hint=(
                    "List comma-separated <name>:<minisign public key> entries with distinct "
                    "names and keys, or none."
                ),
                id=TRUSTED_KEYS_CHECK_ID,
            )
        ]
    return []


def _cors_errors() -> list[checks.Error]:
    # CORS_ALLOW_CREDENTIALS is on, so a plugin host in the allow-list could call EpicStaff's
    # API from a plugin page with the person's login.
    base_domain = settings.PLUGINS_BASE_DOMAIN
    if not _is_dns_name(base_domain):
        return []
    plugin_origins = [
        origin
        for origin in settings.CORS_ALLOWED_ORIGINS or []
        if _is_under(_origin_host(origin), base_domain)
    ]
    return [
        checks.Error(
            f"DJANGO_CORS_ALLOWED_ORIGINS lists {origin!r}, a plugin host under "
            f"PLUGINS_BASE_DOMAIN ({base_domain!r}): plugin pages could call EpicStaff's API "
            "with the person's login.",
            hint="Remove it. Plugin pages never call EpicStaff's API directly.",
            id=CORS_ORIGINS_CHECK_ID,
        )
        for origin in plugin_origins
    ]


def _origin_host(origin: str) -> str | None:
    try:
        return urlsplit(origin).hostname
    except ValueError:
        return None


def _is_under(host: str | None, domain: str) -> bool:
    return bool(host) and (host == domain or host.endswith(f".{domain}"))
