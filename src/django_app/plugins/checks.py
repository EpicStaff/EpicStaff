"""Start-up checks for the plugin platform, run only while `PLUGINS_ENABLED` is true.

Most are Django system checks of level Error, so every management command the container
runs at start-up (`check_db_init`, `migrate`) stops before the server starts. One is a
Warning: plugin development mode is on, and allowed.

Adding a check: an id constant here, a case in `test_plugins_system_checks.py`, then a row in
the "What stops at start-up" table of `docs/plugins/operator/enable-plugins.md`.
"""

import re
from urllib.parse import urlsplit

from django.conf import settings
from django.core import checks
from epicstaff_plugin.signing import SignatureFormatError, parse_trusted_keys

from plugins.configuration.grace_period import MAX_GRACE_PERIOD_DAYS, grace_period_days
from plugins.configuration.host_template import (
    MAX_DNS_NAME_LENGTH,
    InvalidHostTemplateError,
    PluginHostTemplate,
)
from plugins.configuration.limits import MAXIMUM_SETTINGS, positive_integer
from plugins.development.development_mode import (
    LOCALHOST_SUFFIX,
    development_mode_on,
    development_mode_problems,
    parse_development_port,
)
from plugins.nodes.node_registration import parse_uid_range

HTTPS_REQUIRED_CHECK_ID = "plugins.E001"
HOST_TEMPLATE_CHECK_ID = "plugins.E002"
FRONTEND_ORIGIN_CHECK_ID = "plugins.E003"
TRUSTED_KEYS_CHECK_ID = "plugins.E004"
CORS_ORIGINS_CHECK_ID = "plugins.E005"
GATEWAY_SECRET_CHECK_ID = "plugins.E006"
NODE_KEY_CHECK_ID = "plugins.E007"
NODE_UID_RANGE_CHECK_ID = "plugins.E008"
PLATFORM_MAXIMUMS_CHECK_ID = "plugins.E009"
EPICSTAFF_HOST_CHECK_ID = "plugins.E010"
GRACE_PERIOD_CHECK_ID = "plugins.E011"
DEVELOPMENT_MODE_CHECK_ID = "plugins.E012"
DEVELOPMENT_API_PORT_CHECK_ID = "plugins.E013"
SAME_SITE_CHECK_ID = "plugins.E014"
DEVELOPMENT_MODE_WARNING_ID = "plugins.W001"

MIN_SHARED_SECRET_LENGTH = 32
UNCONFIGURED = "none"

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
def check_plugin_platform_settings(app_configs, **kwargs) -> list[checks.CheckMessage]:
    """Refuse a plugin platform that would run over plain http or with broken host settings."""
    if not settings.PLUGINS_ENABLED:
        return []
    return [
        *_https_errors(),
        *_host_template_errors(),
        *_frontend_origin_errors(),
        *_trusted_key_errors(),
        *_cors_errors(),
        *_epicstaff_host_errors(),
        *_same_site_errors(),
        *_shared_secret_errors(
            "PLUGINS_GATEWAY_SECRET",
            settings.PLUGINS_GATEWAY_SECRET,
            "nginx proves its gateway checks with it",
            GATEWAY_SECRET_CHECK_ID,
        ),
        *_shared_secret_errors(
            "PLUGINS_NODE_KEY",
            settings.PLUGINS_NODE_KEY,
            "the plugin node authenticates with it",
            NODE_KEY_CHECK_ID,
        ),
        *_uid_range_errors(),
        *_platform_maximum_errors(),
        *_grace_period_errors(),
        *_development_mode_messages(),
    ]


def _development_mode_messages() -> list[checks.CheckMessage]:
    """Refuse plugin development mode outside a deployment on the developer's own machine;
    warn that it is on where it is allowed."""
    if not development_mode_on():
        return []
    messages: list[checks.CheckMessage] = []
    problems = development_mode_problems()
    if problems:
        messages.append(
            checks.Error(
                "PLUGINS_DEV_MODE is true, but this is not a local development deployment: "
                + "; ".join(problems)
                + ".",
                hint=(
                    "Plugin development mode is only for a deployment on your own machine: "
                    "DJANGO_DEBUG=true, .localhost host names and, under docker compose, "
                    "docker-compose.plugins-dev.yaml added to the docker compose command. "
                    "Otherwise set PLUGINS_DEV_MODE=false."
                ),
                id=DEVELOPMENT_MODE_CHECK_ID,
            )
        )
    if parse_development_port(settings.PLUGINS_DEV_API_PORT) is None:
        messages.append(
            checks.Error(
                f"PLUGINS_DEV_API_PORT ({settings.PLUGINS_DEV_API_PORT!r}) is not a whole number "
                "from 1024 to 65535.",
                hint=(
                    "It is the port on 127.0.0.1 where a development backend reaches EpicStaff's "
                    "API; the default is 8082."
                ),
                id=DEVELOPMENT_API_PORT_CHECK_ID,
            )
        )
    if not messages:
        messages.append(
            checks.Warning(
                "Plugin development mode is on: plugin requests can be served from this "
                "machine's ports.",
                id=DEVELOPMENT_MODE_WARNING_ID,
            )
        )
    return messages


def _is_local_development(host: str | None) -> bool:
    return bool(host) and host.endswith(LOCALHOST_SUFFIX)


def _https_errors() -> list[checks.Error]:
    # Over plain http a plugin page can plant a copy of EpicStaff's login cookie, so plain http
    # is allowed only for *.localhost development.
    # Quiet while the template is invalid or the placeholder: plugins.E002 reports that.
    template = _host_template()
    if settings.REFRESH_COOKIE_SECURE or template is None or _is_local_development(template.parent):
        return []
    return [
        checks.Error(
            "The plugin platform needs HTTPS: DJANGO_REFRESH_COOKIE_SECURE is false and "
            f"PLUGINS_HOST_TEMPLATE ({settings.PLUGINS_HOST_TEMPLATE!r}) does not end in "
            ".localhost.",
            hint=(
                "Serve EpicStaff over HTTPS and set DJANGO_REFRESH_COOKIE_SECURE=true, or use a "
                "template ending in .localhost for local development, or set "
                "PLUGINS_ENABLED=false."
            ),
            id=HTTPS_REQUIRED_CHECK_ID,
        )
    ]


def _host_template_errors() -> list[checks.Error]:
    template = settings.PLUGINS_HOST_TEMPLATE
    try:
        if not PluginHostTemplate.parse(template).is_placeholder:
            return []
        message = f"PLUGINS_HOST_TEMPLATE ({template!r}) is still a placeholder."
    except InvalidHostTemplateError as error:
        message = f"PLUGINS_HOST_TEMPLATE ({template!r}) is not valid: {error}."
    return [
        checks.Error(
            message,
            hint=(
                "Set it to the plugin hosts' name with {id} for the plugin identifier, such as "
                "{id}-app.example.com, and point the wildcard DNS record *.<the part after the "
                "first label> at EpicStaff."
            ),
            id=HOST_TEMPLATE_CHECK_ID,
        )
    ]


def _host_template() -> PluginHostTemplate | None:
    """The deployment's template, or None when it is not valid or still the placeholder
    (plugins.E002 reports both), so the checks built on it stay quiet."""
    try:
        template = PluginHostTemplate.parse(settings.PLUGINS_HOST_TEMPLATE)
    except InvalidHostTemplateError:
        return None
    return None if template.is_placeholder else template


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
    if _NUMERIC_LABEL.fullmatch(host.rsplit(".", 1)[-1]) or len(host) > MAX_DNS_NAME_LENGTH:
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
    template = _host_template()
    if template is None:
        return []
    plugin_origins = [
        origin
        for origin in settings.CORS_ALLOWED_ORIGINS or []
        if template.covers(_origin_host(origin))
    ]
    return [
        checks.Error(
            f"DJANGO_CORS_ALLOWED_ORIGINS lists {origin!r}, a plugin host of "
            f"PLUGINS_HOST_TEMPLATE ({settings.PLUGINS_HOST_TEMPLATE!r}): plugin pages could "
            "call EpicStaff's API with the person's login.",
            hint="Remove it. Plugin pages never call EpicStaff's API directly.",
            id=CORS_ORIGINS_CHECK_ID,
        )
        for origin in plugin_origins
    ]


def _epicstaff_host_errors() -> list[checks.Error]:
    # A plugin identifier could name EpicStaff's own host, and the Origin policy, which refuses
    # every plugin-zone origin, would refuse EpicStaff's own pages.
    template = _host_template()
    if template is None:
        return []
    host = _origin_host(settings.FRONTEND_BASE_URL)
    if not template.covers(host):
        return []
    return [
        checks.Error(
            f"DJANGO_FRONTEND_BASE_URL's host ({host!r}) is in the plugin zone of "
            f"PLUGINS_HOST_TEMPLATE ({settings.PLUGINS_HOST_TEMPLATE!r}): it has the shape of a "
            "plugin host, or is under one or under the plugins' own parent.",
            hint=(
                "Pick a template whose hosts can never be EpicStaff's, such as "
                "{id}-app.example.com or {id}.plugins.example.com for epicstaff.example.com."
            ),
            id=EPICSTAFF_HOST_CHECK_ID,
        )
    ]


def _same_site_errors() -> list[checks.Error]:
    # A plugin in EpicStaff's frame signs its user in through EpicStaff inside that frame, and
    # the browser sends EpicStaff's SameSite=Lax login cookie there only when the frame and the
    # page around it are the same site.
    template = _host_template()
    if template is None or _frontend_origin_errors():
        return []
    _, host = _http_origin(settings.FRONTEND_BASE_URL)
    if template.shares_site_with(host):
        return []
    return [
        checks.Error(
            f"DJANGO_FRONTEND_BASE_URL's host ({host!r}) and the plugin hosts of "
            f"PLUGINS_HOST_TEMPLATE ({settings.PLUGINS_HOST_TEMPLATE!r}) are not the same site: "
            "they do not end in the same domain of two or more labels.",
            hint=(
                "Serve the plugins under EpicStaff's own domain, such as {id}-app.example.com "
                "for epicstaff.example.com. Did EpicStaff move to another domain without the "
                "template?"
            ),
            id=SAME_SITE_CHECK_ID,
        )
    ]


def _origin_host(origin: str) -> str | None:
    try:
        return urlsplit(origin).hostname
    except ValueError:
        return None


def _shared_secret_errors(
    name: str, value: str | None, purpose: str, check_id: str
) -> list[checks.Error]:
    if value and value != UNCONFIGURED and len(value) >= MIN_SHARED_SECRET_LENGTH:
        return []
    problem = "is not set (none)" if not value or value == UNCONFIGURED else "is too short"
    return [
        checks.Error(
            f"{name} {problem}: {purpose}, so it must be at least "
            f"{MIN_SHARED_SECRET_LENGTH} characters.",
            hint="Generate one with: openssl rand -hex 32",
            id=check_id,
        )
    ]


def _uid_range_errors() -> list[checks.Error]:
    if parse_uid_range(settings.PLUGINS_NODE_UID_RANGE) is not None:
        return []
    return [
        checks.Error(
            f"PLUGINS_NODE_UID_RANGE ({settings.PLUGINS_NODE_UID_RANGE!r}) is not "
            "<start>-<end> with 10000 < start <= end < 60000 and at least 10 user ids.",
            hint=(
                "Pick a range no other process on the Docker host uses, such as 20000-20999; "
                "every plugin with a backend runs under one id of it."
            ),
            id=NODE_UID_RANGE_CHECK_ID,
        )
    ]


def _platform_maximum_errors() -> list[checks.Error]:
    return [
        checks.Error(
            f"{setting} ({getattr(settings, setting)!r}) is not a positive integer.",
            hint="Set it to a whole number greater than 0.",
            id=PLATFORM_MAXIMUMS_CHECK_ID,
        )
        for setting in MAXIMUM_SETTINGS.values()
        if positive_integer(getattr(settings, setting)) is None
    ]


def _grace_period_errors() -> list[checks.Error]:
    if grace_period_days(settings.PLUGINS_GRACE_PERIOD_DAYS) is not None:
        return []
    return [
        checks.Error(
            f"PLUGINS_GRACE_PERIOD_DAYS must be a whole number from 1 to {MAX_GRACE_PERIOD_DAYS}.",
            hint=(
                "It is how many days a suspended plugin keeps its data in an organization; "
                "the default is 30."
            ),
            id=GRACE_PERIOD_CHECK_ID,
        )
    ]
