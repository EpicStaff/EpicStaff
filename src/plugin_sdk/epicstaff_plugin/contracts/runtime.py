"""Runtime file version 1: what EpicStaff hands a running plugin process.

EpicStaff builds the document (the `runtime_file` of the node's runtime credentials); the node
agent writes it, byte for byte, to `/run/es_plugins/<identifier>/runtime.json` (mode 0400,
owned by the plugin's UID) and rewrites it atomically when it changes; the plugin process
reads it through `epicstaff_plugin.runtime.RuntimeConfig`. It holds the plugin's secret
settings in clear text, so it is never logged and never put anywhere else.

Every model forbids unknown fields, so the side that builds the document cannot misspell
one. The plugin reads it leniently, so a newer EpicStaff that adds a field does not break a
plugin built against an older SDK:

    RuntimeFile.model_validate_json(raw, extra="ignore")

Pydantic applies the per-call `extra` to every nested model.
"""

import unicodedata
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from epicstaff_plugin.contracts.gateway_context import Jwks, PluginIdentity
from epicstaff_plugin.contracts.manifest import SETTING_KEY_PATTERN, PublicPath

RUNTIME_FILE_FORMAT = 1
RUNTIME_FILE_ENVIRONMENT_VARIABLE = "EPICSTAFF_PLUGIN_RUNTIME_FILE"
ENTRYPOINT_ENVIRONMENT_VARIABLE = "EPICSTAFF_PLUGIN_ENTRYPOINT"
"""The backend's ASGI app, `module.path:attribute` (the manifest's `backend.entrypoint`)."""

PORT_ENVIRONMENT_VARIABLE = "PORT"
"""The backend's port. On the node it is for information only: the socket comes in through
`LISTEN_FD_ENVIRONMENT_VARIABLE`."""

LISTEN_FD_ENVIRONMENT_VARIABLE = "EPICSTAFF_PLUGIN_LISTEN_FD"
"""The listening socket the node passes in, as a file descriptor number; set only on the node."""

# What every backend process is told about itself. The three URLs repeat the runtime file's.
PLUGIN_IDENTIFIER_ENVIRONMENT_VARIABLE = "EPICSTAFF_PLUGIN_IDENTIFIER"
PLUGIN_VERSION_ENVIRONMENT_VARIABLE = "EPICSTAFF_PLUGIN_VERSION"
"""The version of the plugin the process runs."""

EPICSTAFF_API_URL_ENVIRONMENT_VARIABLE = "EPICSTAFF_API_URL"
"""The runtime file's `epicstaff_api_url`."""

EPICSTAFF_PUBLIC_URL_ENVIRONMENT_VARIABLE = "EPICSTAFF_PUBLIC_URL"
"""The runtime file's `epicstaff_public_url`."""

PLUGIN_PUBLIC_URL_ENVIRONMENT_VARIABLE = "EPICSTAFF_PLUGIN_PUBLIC_URL"
"""The runtime file's `public_url`."""

# The plugin node sets these in the environment of a backend process, which only the
# plugin's own user can read. Setting secrets stay in the runtime file; these carry the
# platform's database and egress-proxy credentials.
DATABASE_URL_ENVIRONMENT_VARIABLE = "DATABASE_URL"
"""`postgresql://` URL of the plugin's own database, as its app role. Only with a database."""

DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE = "EPICSTAFF_PLUGIN_DB_CONNECTIONS"
"""The app role's connection limit, a positive integer. Only with a database."""

HTTPS_PROXY_ENVIRONMENT_VARIABLE = "HTTPS_PROXY"
"""The proxy variable `epicstaff_plugin.egress.proxy_url()` reads; the node sets all four."""

PROXY_ENVIRONMENT_VARIABLES = (
    HTTPS_PROXY_ENVIRONMENT_VARIABLE,
    "https_proxy",
    "HTTP_PROXY",
    "http_proxy",
)
"""Each holds the egress proxy's URL with the plugin's own credentials. Every backend gets them."""

NO_PROXY_ENVIRONMENT_VARIABLES = ("NO_PROXY", "no_proxy")
"""Hosts reached directly: EpicStaff's internal API host, then the loopback names."""

LOOPBACK_NO_PROXY_HOSTS = ("localhost", "127.0.0.1", "::1")


def _http_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
    except ValueError:
        raise ValueError("must be an http:// or https:// URL") from None
    if (
        parts.scheme not in ("http", "https")
        or not hostname
        or parts.username is not None
        or any(
            character.isspace() or unicodedata.category(character) == "Cc" for character in value
        )
    ):
        raise ValueError("must be an http:// or https:// URL without credentials")
    return value


HttpUrl = Annotated[str, StringConstraints(max_length=2048), AfterValidator(_http_url)]
SettingKey = Annotated[str, StringConstraints(pattern=SETTING_KEY_PATTERN)]
SettingValue = str | int | bool
# An organization id as a JSON object key.
OrgIdText = Annotated[str, StringConstraints(pattern=r"^[1-9][0-9]{0,18}$")]
SERVICE_ACCOUNT_KEY_PREFIX = "esp-"
# `secrets.token_urlsafe(32)`: 43 characters of the URL-safe base64 alphabet.
SERVICE_ACCOUNT_KEY_BODY_PATTERN = r"[A-Za-z0-9_-]{43}"
SERVICE_ACCOUNT_KEY_PATTERN = f"^{SERVICE_ACCOUNT_KEY_PREFIX}{SERVICE_ACCOUNT_KEY_BODY_PATTERN}$"
ServiceAccountKey = Annotated[str, StringConstraints(pattern=SERVICE_ACCOUNT_KEY_PATTERN)]


class ServiceAccountEntry(BaseModel):
    """The plugin's service account in one organization it is granted to.

    `key` authenticates the plugin's calls to EpicStaff's API in that organization
    (`Authorization: PluginKey <key>`). EpicStaff mints a new one every time the node fetches
    the runtime file, and the one before it keeps working for 10 minutes, so always read the
    key from the current file instead of keeping it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    key: ServiceAccountKey
    org_name: Annotated[str, StringConstraints(max_length=255)]
    grant_state: Annotated[str, StringConstraints(min_length=1, max_length=32)]
    """`granting` while the install hook runs, `active` after it, and `upgrading` while the
    organization's upgrade hook runs: do background work for the organization only while it is
    `active`. Read as text: a newer EpicStaff may add states."""


class RuntimeFile(BaseModel):
    """The runtime file of one plugin process.

    `settings` holds every non-secret setting with its stored value, or its default when none
    is stored; an optional setting with neither is left out. `secret_settings` holds only the
    secrets that are set. `service_accounts` has one entry per organization whose grant holds
    a key (`granting`, `active` or `upgrading`), keyed by the organization id as text.
    """

    # A validation error never repeats the input: it may be a secret setting. Pydantic applies
    # the outermost model's setting, so a model that embeds this one must set it too.
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    format: Literal[1]
    plugin: PluginIdentity
    issuer: HttpUrl
    """EpicStaff's public origin, the `iss` of every gateway context."""

    public_url: HttpUrl
    """The plugin's own public address, `<scheme>://<identifier>.<plugin base domain>`."""

    epicstaff_public_url: HttpUrl
    """EpicStaff's address as people's browsers reach it."""

    epicstaff_api_url: HttpUrl
    """EpicStaff's API as the plugin process reaches it (an internal address, ends in `/api/`)."""

    settings: dict[SettingKey, SettingValue]
    secret_settings: dict[SettingKey, str]
    service_accounts: dict[OrgIdText, ServiceAccountEntry]
    jwks: Jwks
    """The public keys gateway contexts are signed with."""

    public_paths: list[PublicPath]
    """The manifest's public paths, as the gateway applies them."""
