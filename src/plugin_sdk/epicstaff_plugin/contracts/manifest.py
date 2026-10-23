"""Manifest version 1: the `manifest.json` at the root of every EpicStaff plugin package.

This model is the one definition of the manifest. EpicStaff validates every upload with it,
`epicstaff-plugin validate` and `pack` validate sources with it, and
`docs/plugins/reference/manifest.schema.json` is generated from it.

Which `access` resource types and actions exist depends on the EpicStaff a plugin is
installed on, so EpicStaff checks those against its own permission catalog at upload; this
model checks only their form.
"""

import json
import re
import unicodedata
from typing import Annotated, Any, Literal, get_args
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    ValidationInfo,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from epicstaff_plugin.json_documents import load_json_object
from epicstaff_plugin.paths import path_problem
from epicstaff_plugin.problems import MANIFEST_LOC, PackageProblemsError, Problem, format_loc

MANIFEST_FILE_NAME = "manifest.json"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

Action = Literal["read", "create", "update", "delete", "export", "use"]
ACTIONS: tuple[str, ...] = get_args(Action)
READ_ACTION = "read"
HttpMethod = Literal["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
SettingType = Literal["string", "text", "integer", "boolean", "url", "enum", "secret"]
BuiltInRoleKey = Literal["org_admin", "member", "viewer"]
BUILT_IN_ROLE_KEYS: tuple[str, ...] = get_args(BuiltInRoleKey)

IDENTIFIER_PATTERN = r"^[a-z][a-z0-9-]{0,30}[a-z0-9]$"
# Names a plugin host or an EpicStaff route could clash with. `packages` collides with the
# admin upload route /api/admin/plugins/packages/.
RESERVED_IDENTIFIERS = frozenset(
    {"www", "api", "admin", "plugins", "epicstaff", "static", "postgres", "public", "packages"}
)
RESERVED_IDENTIFIER_PREFIX = "pg"
# SemVer 2.0 with ASCII digits only: the version becomes part of file and storage paths.
SEMVER_PATTERN = (
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)
ENTRYPOINT_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*:[A-Za-z_][A-Za-z0-9_]*$"
RESOURCE_TYPE_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
SETTING_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
PUBLIC_PATH_PATTERN = r"^/api(?:/[A-Za-z0-9._~-]+)+/?$"
_HOST_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
# The last label starts with a letter, which rules out IP literals; ':' is never allowed,
# so neither is a port (outbound traffic is HTTPS on 443 only).
OUTBOUND_HOST_PATTERN = rf"^(?:\*\.)?(?:{_HOST_LABEL}\.)+[a-z](?:[a-z0-9-]{{0,61}}[a-z0-9])?$"
WILDCARD_HOST_PREFIX = "*."
# Keeps the review of a package readable; the node contract caps the egress allow-list too.
MAX_OUTBOUND_HOSTS = 100

# The app menu EpicStaff draws in its own sidebar while the app is open.
MAX_NAVIGATION_ITEMS = 12
MAX_NAVIGATION_LABEL_LENGTH = 32
MAX_NAVIGATION_PATH_LENGTH = 256
# A strict, already canonical subset of the frame protocol's `nav_path_pattern`: no query, no
# `%` escape, no empty segment, no trailing `/`. `.` and `..` segments are refused on top.
NAVIGATION_PATH_PATTERN = r"^/(?:[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*)?$"
NAVIGATION_PATH_PROBLEM = (
    "must be '/' or '/'-separated segments of letters, digits, '-', '.', '_' and '~', "
    "without a query, a '.' or '..' segment, or a trailing '/'"
)
NAVIGATION_ICON_PATTERN = r"^icons/[a-z0-9][a-z0-9_-]{0,62}\.(?:svg|png)$"
NAVIGATION_ICON_PROBLEM = (
    "must be icons/<name>.svg or icons/<name>.png, where <name> is 1 to 63 lower-case "
    "letters, digits, '-' and '_', starting with a letter or a digit"
)

MAX_HOOK_TIMEOUT_SECONDS = {"install": 900, "upgrade": 1800, "org_removed": 900}


def _rule_error(code: str, message: str, **context: Any) -> PydanticCustomError:
    return PydanticCustomError(code, message, context or None)


def _plain_text(value: str) -> str:
    if not value.strip():
        raise _rule_error("blank_text", "must not be blank")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise _rule_error("control_character", "must not contain control characters")
    return value


def _not_reserved(identifier: str) -> str:
    if identifier in RESERVED_IDENTIFIERS or identifier.startswith(RESERVED_IDENTIFIER_PREFIX):
        raise _rule_error(
            "reserved_identifier", "'{identifier}' is reserved", identifier=identifier
        )
    return identifier


def _https_url(value: str) -> str:
    error = _rule_error("https_url", "must be an https:// URL without credentials")
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
    except ValueError:
        raise error from None
    if (
        parts.scheme != "https"
        or not hostname
        or parts.username is not None
        or any(
            character.isspace() or unicodedata.category(character) == "Cc" for character in value
        )
    ):
        raise error
    return value


def _package_relative_path(value: str) -> str:
    if problem := path_problem(value):
        raise _rule_error("package_path", "path {problem}", problem=problem)
    return value


def _no_dot_segments(path: str) -> str:
    if any(segment in (".", "..") for segment in path.split("/")):
        raise _rule_error("dot_segment", "must not contain '.' or '..' segments")
    return path


def _navigation_path(path: str) -> str:
    # `fullmatch`, not `match`: `$` alone also matches before a trailing newline.
    if not re.fullmatch(NAVIGATION_PATH_PATTERN, path) or any(
        segment in (".", "..") for segment in path.split("/")
    ):
        raise _rule_error("navigation_path", NAVIGATION_PATH_PROBLEM)
    return path


def _navigation_icon(path: str) -> str:
    if not re.fullmatch(NAVIGATION_ICON_PATTERN, path):
        raise _rule_error("navigation_icon", NAVIGATION_ICON_PROBLEM)
    return path


def _unique(values: list[Any], what: str) -> None:
    seen: set[Any] = set()
    for value in values:
        if value in seen:
            raise _rule_error(
                "duplicate", "lists {what} '{value}' more than once", what=what, value=value
            )
        seen.add(value)


ShortText = Annotated[
    str, StringConstraints(min_length=1, max_length=64), AfterValidator(_plain_text)
]
Reason = Annotated[
    str, StringConstraints(min_length=1, max_length=200), AfterValidator(_plain_text)
]
LongText = Annotated[
    str, StringConstraints(min_length=1, max_length=500), AfterValidator(_plain_text)
]
Identifier = Annotated[
    str, StringConstraints(pattern=IDENTIFIER_PATTERN), AfterValidator(_not_reserved)
]
Version = Annotated[str, StringConstraints(max_length=64, pattern=SEMVER_PATTERN)]
UniqueItems = Field(json_schema_extra={"uniqueItems": True})


class _ManifestPart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Publisher(_ManifestPart):
    """Who publishes the plugin. Shown as claimed unless the package is signed by a trusted key."""

    name: ShortText
    url: Annotated[str, StringConstraints(max_length=2048), AfterValidator(_https_url)] | None = (
        None
    )


class Platform(_ManifestPart):
    """The versions of the platform contracts the plugin is written against."""

    frame_protocol: Literal[1]
    gateway_context: Literal[1]
    hook_api: Literal[1]


class NavigationItem(_ManifestPart):
    """An entry of the app's menu, which EpicStaff draws in its own sidebar while the app is open."""

    label: Annotated[
        str,
        StringConstraints(min_length=1, max_length=MAX_NAVIGATION_LABEL_LENGTH),
        AfterValidator(_plain_text),
    ]
    path: Annotated[
        str,
        StringConstraints(max_length=MAX_NAVIGATION_PATH_LENGTH),
        AfterValidator(_navigation_path),
        Field(
            description="The page of the app the item opens; a '.' or '..' segment is refused too.",
            json_schema_extra={"pattern": NAVIGATION_PATH_PATTERN},
        ),
    ]
    icon: Annotated[
        str,
        AfterValidator(_navigation_icon),
        Field(
            description="An SVG or PNG file in the package's icons/ folder.",
            json_schema_extra={"pattern": NAVIGATION_ICON_PATTERN},
        ),
    ]


class Spa(_ManifestPart):
    """The plugin's single-page app. Its files are under `spa/` in the package."""

    entry: Annotated[str, AfterValidator(_package_relative_path)] = "index.html"
    navigation: Annotated[list[NavigationItem], Field(max_length=MAX_NAVIGATION_ITEMS)] = Field(
        default_factory=list
    )

    @field_validator("navigation")
    @classmethod
    def _distinct_paths_and_labels(cls, items: list[NavigationItem]) -> list[NavigationItem]:
        _unique([item.path for item in items], "path")
        _unique([item.label for item in items], "label")
        return items


class Backend(_ManifestPart):
    """The plugin's Python backend. Its files are under `backend/` in the package."""

    python: Literal["3.12", "3.13"]
    entrypoint: Annotated[str, StringConstraints(max_length=200, pattern=ENTRYPOINT_PATTERN)]


class Database(_ManifestPart):
    """Present when the plugin needs its own database; migrations are under `database/migrations/`."""


class AccessDeclaration(_ManifestPart):
    """What the plugin may do in EpicStaff, in the terms of EpicStaff's permission catalog."""

    resource_type: Annotated[str, StringConstraints(pattern=RESOURCE_TYPE_PATTERN)]
    actions: Annotated[list[Action], Field(min_length=1), UniqueItems]
    reason: Reason

    @field_validator("actions")
    @classmethod
    def _distinct_actions(cls, actions: list[str]) -> list[str]:
        _unique(actions, "action")
        return actions


class UserPermissionDefaults(_ManifestPart):
    """Whether each built-in role gets the action. Custom roles start with nothing.

    The built-in roles build on each other: Viewer gets only what Member gets, and Member only
    what Org Admin gets. Assigning a role checks its plugin actions against the assigner's
    own, so an Org Admin could not assign a Member who holds an action Org Admin lacks.
    """

    org_admin: bool
    member: bool
    viewer: bool

    @model_validator(mode="after")
    def _higher_roles_get_what_lower_ones_get(self) -> "UserPermissionDefaults":
        if self.viewer and not self.member:
            raise _rule_error(
                "built_in_roles_not_nested",
                "gives viewer the action but not member; a built-in role must also get "
                "every action of the roles below it (viewer, then member, then org_admin)",
            )
        if self.member and not self.org_admin:
            raise _rule_error(
                "built_in_roles_not_nested",
                "gives member the action but not org_admin; a built-in role must also get "
                "every action of the roles below it (viewer, then member, then org_admin)",
            )
        return self


class UserPermission(_ManifestPart):
    """One action people can be given on the plugin, and what it means inside the plugin."""

    action: Action
    description: Reason
    defaults: UserPermissionDefaults


class PublicPath(_ManifestPart):
    """A backend path reached without an EpicStaff login."""

    path: Annotated[
        str,
        StringConstraints(max_length=512, pattern=PUBLIC_PATH_PATTERN),
        AfterValidator(_no_dot_segments),
    ]
    match: Literal["exact", "prefix"]
    methods: Annotated[list[HttpMethod], Field(min_length=1), UniqueItems]
    rate_limit_per_minute: Annotated[int, Field(ge=1, le=6000)]
    max_body_kb: Annotated[int, Field(ge=0, le=20480)]

    @field_validator("methods")
    @classmethod
    def _distinct_methods(cls, methods: list[str]) -> list[str]:
        _unique(methods, "method")
        return methods


class OutboundHost(_ManifestPart):
    """A host the backend may call over HTTPS (port 443)."""

    host: Annotated[str, StringConstraints(max_length=255, pattern=OUTBOUND_HOST_PATTERN)]
    reason: Reason


class Setting(_ManifestPart):
    """A deployment-wide setting the SuperAdmin fills in."""

    key: Annotated[str, StringConstraints(pattern=SETTING_KEY_PATTERN)]
    type: SettingType
    label: ShortText
    description: LongText
    required: bool
    default: Any = Field(
        default=None,
        description="Must match `type`; never set for a secret setting.",
        json_schema_extra={"type": ["string", "integer", "boolean", "null"]},
    )
    values: Annotated[list[ShortText], Field(min_length=1), UniqueItems] | None = None

    @model_validator(mode="after")
    def _values_and_default_match_type(self) -> "Setting":
        if self.type == "enum":
            if self.values is None:
                raise _rule_error("enum_values_required", "an enum setting must list its values")
            _unique(self.values, "value")
        elif self.values is not None:
            raise _rule_error("values_not_allowed", "only an enum setting has values")
        if self.default is None:
            return self
        if self.type == "secret":
            raise _rule_error("secret_default", "a secret setting cannot have a default")
        if not _default_matches_type(self.default, self.type):
            raise _rule_error(
                "default_type", "default does not fit a {type} setting", type=self.type
            )
        if self.type == "enum" and self.default not in (self.values or []):
            raise _rule_error("default_not_in_values", "default must be one of the values")
        return self


def _default_matches_type(default: Any, setting_type: str) -> bool:
    if setting_type == "integer":
        return type(default) is int
    if setting_type == "boolean":
        return type(default) is bool
    if setting_type == "url":
        return isinstance(default, str) and urlsplit(default).scheme in ("http", "https")
    return isinstance(default, str)


class Limits(_ManifestPart):
    """Resource limits the backend asks for.

    Each one is optional: EpicStaff gives an omitted (or null) limit the platform default,
    and caps every limit at the deployment's maximum, which it checks at upload. The bounds
    here are the most any deployment may allow.
    """

    memory_mb: Annotated[int, Field(ge=64, le=8192)] | None = None
    db_connections: Annotated[int, Field(ge=1, le=100)] | None = None
    statement_timeout_seconds: Annotated[int, Field(ge=1, le=600)] | None = None
    requests_per_minute: Annotated[int, Field(ge=1, le=6000)] | None = None
    cpu_priority: Literal["normal", "low"] | None = None


class HookTimeouts(_ManifestPart):
    """Shorter timeouts for the lifecycle hooks, in seconds."""

    install: Annotated[int, Field(ge=1, le=MAX_HOOK_TIMEOUT_SECONDS["install"])] | None = None
    upgrade: Annotated[int, Field(ge=1, le=MAX_HOOK_TIMEOUT_SECONDS["upgrade"])] | None = None
    org_removed: Annotated[int, Field(ge=1, le=MAX_HOOK_TIMEOUT_SECONDS["org_removed"])] | None = (
        None
    )


class Hooks(_ManifestPart):
    """The lifecycle hooks the backend implements."""

    install: bool = False
    upgrade: bool = False
    org_removed: bool = False
    timeouts_seconds: HookTimeouts | None = None

    @property
    def any_enabled(self) -> bool:
        return self.install or self.upgrade or self.org_removed


class PluginManifest(_ManifestPart):
    """An EpicStaff plugin manifest, version 1."""

    model_config = ConfigDict(title="EpicStaff plugin manifest, version 1")

    manifest_version: Literal[1]
    id: Identifier
    version: Version
    name: ShortText
    description: LongText
    publisher: Publisher
    icon: Literal["icon.svg", "icon.png"]
    platform: Platform
    spa: Spa | None = None
    backend: Backend | None = None
    database: Database | None = None
    access: list[AccessDeclaration] = Field(default_factory=list)
    user_permissions: Annotated[list[UserPermission], Field(min_length=1)]
    public_paths: list[PublicPath] = Field(default_factory=list)
    outbound_hosts: Annotated[list[OutboundHost], Field(max_length=MAX_OUTBOUND_HOSTS)] = Field(
        default_factory=list
    )
    settings: list[Setting] = Field(default_factory=list)
    limits: Limits | None = None
    hooks: Hooks = Field(default_factory=Hooks)

    # `backend` is declared before every field that needs it, so `info.data` holds it here.
    @field_validator("access", "public_paths", "outbound_hosts", "settings")
    @classmethod
    def _declarations_require_backend(cls, values: list[Any], info: ValidationInfo) -> list[Any]:
        if values and info.data.get("backend") is None:
            raise _rule_error("requires_backend", "needs a backend section")
        return values

    @field_validator("database", "limits")
    @classmethod
    def _sections_require_backend(
        cls, section: Database | Limits | None, info: ValidationInfo
    ) -> Database | Limits | None:
        if section is not None and info.data.get("backend") is None:
            raise _rule_error("requires_backend", "needs a backend section")
        return section

    @field_validator("hooks")
    @classmethod
    def _hooks_require_backend(cls, hooks: Hooks, info: ValidationInfo) -> Hooks:
        if hooks.any_enabled and info.data.get("backend") is None:
            raise _rule_error("requires_backend", "an enabled hook needs a backend section")
        return hooks

    @field_validator("access")
    @classmethod
    def _one_declaration_per_resource_type(
        cls, declarations: list[AccessDeclaration]
    ) -> list[AccessDeclaration]:
        _unique([declaration.resource_type for declaration in declarations], "resource type")
        return declarations

    @field_validator("public_paths")
    @classmethod
    def _distinct_public_paths(cls, paths: list[PublicPath]) -> list[PublicPath]:
        _unique([public_path.path for public_path in paths], "path")
        return paths

    @field_validator("outbound_hosts")
    @classmethod
    def _distinct_outbound_hosts(cls, hosts: list[OutboundHost]) -> list[OutboundHost]:
        _unique([outbound_host.host for outbound_host in hosts], "host")
        return hosts

    @field_validator("settings")
    @classmethod
    def _distinct_setting_keys(cls, settings: list[Setting]) -> list[Setting]:
        _unique([setting.key for setting in settings], "key")
        return settings

    @field_validator("user_permissions")
    @classmethod
    def _user_permissions_build_on_read(
        cls, permissions: list[UserPermission]
    ) -> list[UserPermission]:
        _unique([permission.action for permission in permissions], "action")
        read = next(
            (permission for permission in permissions if permission.action == READ_ACTION), None
        )
        if read is None:
            raise _rule_error("read_required", "must include the read action (View)")
        for role in BUILT_IN_ROLE_KEYS:
            gets_any = any(getattr(permission.defaults, role) for permission in permissions)
            if gets_any and not getattr(read.defaults, role):
                raise _rule_error(
                    "read_required_for_role",
                    "gives {role} an action without read; a role with any action must also get read",
                    role=role,
                )
        return permissions

    @property
    def navigation_icon_paths(self) -> tuple[str, ...]:
        """The package paths of the icons the app menu names, each once, sorted."""
        if self.spa is None:
            return ()
        return tuple(sorted({item.icon for item in self.spa.navigation}))

    def user_permission_defaults(self, role: str) -> list[str]:
        """Return the actions a built-in role (`org_admin`, `member`, `viewer`) gets by default."""
        return [
            permission.action
            for permission in self.user_permissions
            if getattr(permission.defaults, role)
        ]


def parse_manifest(raw: bytes) -> PluginManifest:
    """Parse and validate the bytes of a `manifest.json`.

    Raises:
        PackageProblemsError: The bytes are not a JSON object or break a manifest rule. Every
            problem is listed, located under `manifest`.
    """
    return validate_manifest(load_json_object(raw, MANIFEST_LOC, MANIFEST_FILE_NAME))


def validate_manifest(document: dict[str, Any]) -> PluginManifest:
    """Validate an already decoded manifest document.

    Raises:
        PackageProblemsError: The document breaks a manifest rule.
    """
    try:
        return PluginManifest.model_validate(document)
    except ValidationError as error:
        raise PackageProblemsError(
            Problem(format_loc(MANIFEST_LOC, detail["loc"]), detail["msg"])
            for detail in error.errors(include_url=False)
        ) from None


def manifest_json_schema() -> dict[str, Any]:
    """Return the manifest's JSON Schema, as published in the plugin documentation."""
    return {"$schema": JSON_SCHEMA_DIALECT, **PluginManifest.model_json_schema()}


def render_manifest_json_schema() -> str:
    """Return the manifest's JSON Schema as the exact text of `manifest.schema.json`."""
    return json.dumps(manifest_json_schema(), indent=2, ensure_ascii=False) + "\n"
