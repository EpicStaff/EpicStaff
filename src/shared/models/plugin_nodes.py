"""The contract between EpicStaff (django_app) and a plugin node agent (es_plugins).

django_app serves these documents on `/api/plugin-nodes/self/...` and the node agent consumes
them; the node's report travels the other way. Both sides import this one module.

Every model forbids unknown fields, so the side that builds a document cannot misspell one.
The side that reads a document from the other service parses it leniently, so a newer peer
that adds a field does not break an older one:

    DesiredState.model_validate_json(body, extra="ignore")

Pydantic applies the per-call `extra` to every nested model.

This module is deliberately not exported from `shared.models`: it depends on the
`epicstaff-plugin` SDK (the runtime file model), which only django_app and es_plugins
install.
"""

from dataclasses import dataclass
from typing import Annotated, Literal, Self

from epicstaff_plugin.contracts.hook_api import (
    MAX_HOOK_ASSERTION_LENGTH,
    MAX_HOOK_BODY_BYTES,
    MAX_HOOK_ERROR_MESSAGE_LENGTH,
    HookKind,
)
from epicstaff_plugin.contracts.manifest import (
    MAX_HOOK_TIMEOUT_SECONDS,
    MAX_OUTBOUND_HOSTS,
    OUTBOUND_HOST_PATTERN,
)
from epicstaff_plugin.contracts.runtime import RuntimeFile
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

__all__ = [
    "CONTRACT_FORMAT",
    "DATABASE_NAME_PREFIX",
    "MAX_APPLIED_MIGRATIONS",
    "MAX_LAST_ERROR_LENGTH",
    "MAX_LOG_LINE_LENGTH",
    "MAX_LOG_TAIL_LINES",
    "MAX_PENDING_HOOK_JOBS",
    "MAX_PLACEMENTS_PER_NODE",
    "NODE_PORT_RANGE",
    "DatabaseNames",
    "DatabaseReport",
    "DesiredDatabase",
    "DesiredDatabaseServer",
    "DesiredEgress",
    "DesiredHookJob",
    "DesiredPackage",
    "DesiredPlacement",
    "DesiredRuntime",
    "DesiredState",
    "DesiredStateNode",
    "HookInvocation",
    "HookResult",
    "NodeReport",
    "PlacementReport",
    "RuntimeCredentials",
    "RuntimeDatabaseCredentials",
    "database_names_for",
]

CONTRACT_FORMAT = 1
MAX_LAST_ERROR_LENGTH = 2000
MAX_LOG_TAIL_LINES = 200
MAX_LOG_LINE_LENGTH = 1000
# The node's port and UID ranges hold at most this many placements.
MAX_PLACEMENTS_PER_NODE = 1000
# A desired placement lists at most this many pending hook jobs.
MAX_PENDING_HOOK_JOBS = 1000
# The ports a node gives plugin processes: first and last, both included. The node agent
# holds every port of it from start-up; django_app registers the node with it and gives each
# placement the lowest free one.
NODE_PORT_RANGE = (20001, 20999)
DATABASE_NAME_PREFIX = "plugin_"
# A package numbers its migrations 000 to 999, each number once.
MAX_APPLIED_MIGRATIONS = 1000

Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
"""A sha256 digest as 64 lower-case hex characters."""

PluginIdentifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,30}[a-z0-9]$")]
NodeName = Annotated[str, StringConstraints(min_length=1, max_length=64)]
PackageVersion = Annotated[str, StringConstraints(min_length=1, max_length=64)]
NonNegativeInt = Annotated[int, Field(ge=0)]
PositiveInt = Annotated[int, Field(gt=0)]
NetworkPort = Annotated[int, Field(ge=1, le=65535)]
UnixUid = Annotated[int, Field(ge=1, le=2**31 - 1)]
LogLine = Annotated[str, StringConstraints(max_length=MAX_LOG_LINE_LENGTH)]
# At most 63 characters, Postgres's identifier length, so no name is ever truncated.
DatabaseObjectName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,62}$")]
InstallationId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
"""A uuid4 as 32 lower-case hex characters."""

ServerHost = Annotated[str, StringConstraints(pattern=r"^[a-z0-9](?:[a-z0-9._-]{0,251}[a-z0-9])?$")]
OutboundHostText = Annotated[str, StringConstraints(pattern=OUTBOUND_HOST_PATTERN)]
MigrationName = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9]{3}_[a-z0-9][a-z0-9_]*\.sql$", max_length=255),
]
"""A migration's file name under `database/migrations/`, e.g. `001_places.sql`."""

DesiredProcessState = Literal["running", "stopped"]
ObservedProcessState = Literal[
    "unknown", "downloading", "building", "starting", "running", "stopped", "failed"
]
ProcessHealth = Literal["ok", "failing", "unknown"]
CpuPriority = Literal["normal", "low"]
PluginPython = Literal["3.12", "3.13"]
PackageTrust = Literal["trusted", "untrusted"]


@dataclass(frozen=True)
class DatabaseNames:
    """The names of one plugin's database and of its three roles."""

    database: str
    owner_role: str
    app_role: str
    job_role: str


def database_names_for(identifier: str) -> DatabaseNames:
    """Derive the database and role names of the plugin with this identifier.

    With `<id_>` the identifier with `-` replaced by `_`, the database is `plugin_<id_>` and
    the roles are `<id_>_owner`, `<id_>_app` and `<id_>_job`: `my-plugin` gets
    `plugin_my_plugin`, `my_plugin_owner`, `my_plugin_app` and `my_plugin_job`.

    The mapping is injective, so two plugins never share a name: an identifier has no `_`,
    and the three role suffixes end in different letters. The prefix keeps a database name
    off `postgres`, `template0` and `template1`, which is a valid identifier. The longest
    identifier (32 characters) gives names of at most 39 characters.

    Args:
        identifier: A valid plugin identifier; the properties above hold only for one.
    """
    stem = identifier.replace("-", "_")
    return DatabaseNames(
        database=f"{DATABASE_NAME_PREFIX}{stem}",
        owner_role=f"{stem}_owner",
        app_role=f"{stem}_app",
        job_role=f"{stem}_job",
    )


class _NodeContractModel(BaseModel):
    # Errors never show their input: Pydantic formats them with the outermost model's config,
    # so this keeps a secret nested in a runtime file out of any message or log line.
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class DesiredStateNode(_NodeContractModel):
    """The node the desired state was built for."""

    name: NodeName


class DesiredPackage(_NodeContractModel):
    """The package a placement runs; the node downloads and verifies it before unpacking."""

    package_id: PositiveInt
    version: PackageVersion
    sha256: Sha256Hex
    """Digest of the whole `.esplugin` file; the download must match it."""

    size: PositiveInt
    trust: PackageTrust
    signer_public_key: str | None
    """The minisign public key (`RW…`) that signed the package; null for an untrusted package,
    whose `CONTENTS.json` digests the node still checks."""


class DesiredRuntime(_NodeContractModel):
    """How the node starts the plugin's process."""

    python: PluginPython
    entrypoint: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    """The manifest's ASGI entrypoint, `module.path:attribute`."""

    port: NetworkPort
    unix_uid: UnixUid
    memory_mb: PositiveInt
    """The effective memory cap the node's watchdog enforces on the plugin's UID."""

    cpu_priority: CpuPriority


class DesiredHookJob(_NodeContractModel):
    """A lifecycle hook call the node should make to the plugin's process.

    The node claims the job (`POST .../hook-jobs/{job_id}/claim/`) only once the process is
    healthy and its runtime file holds a service-account key for `organization_id`.
    """

    job_id: PositiveInt
    kind: HookKind
    organization_id: PositiveInt


class DesiredDatabaseServer(_NodeContractModel):
    """The database server a plugin's database lives on."""

    name: NodeName
    host: ServerHost
    port: NetworkPort


class DesiredDatabase(_NodeContractModel):
    """The plugin's own database, which the node provisions before it starts the process."""

    server: DesiredDatabaseServer
    installation_id: InstallationId
    """Marks the roles this installation created; the node refuses ones another left behind."""

    database_name: DatabaseObjectName
    owner_role: DatabaseObjectName
    app_role: DatabaseObjectName
    job_role: DatabaseObjectName
    connection_limit: Annotated[int, Field(ge=1, le=100)]
    """The app role's connection limit: the plugin's effective `db_connections`."""

    statement_timeout_seconds: Annotated[int, Field(ge=1, le=600)]
    """The app role's `statement_timeout`: the plugin's effective limit."""


class DesiredEgress(_NodeContractModel):
    """The hosts the plugin's process may reach through the egress proxy."""

    hosts: Annotated[list[OutboundHostText], Field(max_length=MAX_OUTBOUND_HOSTS)]
    """The package's `outbound_hosts`, in manifest order; empty refuses every request."""


class DesiredPlacement(_NodeContractModel):
    """One plugin process the node should run (or keep stopped).

    A change of `settings_revision`, `restart_generation`, `runtime` or `package` makes the
    node refetch the runtime credentials and restart the process; so does a change of
    `database`, after the node provisions the database again. A change of
    `credentials_revision` alone makes it refetch them and rewrite the runtime file without a
    restart. A change of `egress` alone rewrites the egress policy, also without a restart.

    When `database` is set, its four names must be `database_names_for(plugin_identifier)`,
    so even a wrong desired state cannot point one plugin's placement at another plugin's
    database or roles.
    """

    placement_id: PositiveInt
    plugin_identifier: PluginIdentifier
    desired_state: DesiredProcessState
    """`stopped` while the plugin cannot start, e.g. a required setting is missing."""

    restart_generation: NonNegativeInt
    package: DesiredPackage
    runtime: DesiredRuntime
    credentials_revision: Sha256Hex
    settings_revision: NonNegativeInt
    hook_jobs: Annotated[list[DesiredHookJob], Field(max_length=MAX_PENDING_HOOK_JOBS)] = Field(
        default_factory=list
    )
    """Pending hook jobs, oldest first. An install job is listed only while its grant exists
    and is still being granted."""

    database: DesiredDatabase | None = None
    """Set exactly when the package's manifest has a `database` section."""

    egress: DesiredEgress = Field(default_factory=lambda: DesiredEgress(hosts=[]))

    @model_validator(mode="after")
    def _database_names_belong_to_the_plugin(self) -> Self:
        if self.database is None:
            return self
        names = DatabaseNames(
            database=self.database.database_name,
            owner_role=self.database.owner_role,
            app_role=self.database.app_role,
            job_role=self.database.job_role,
        )
        if names != database_names_for(self.plugin_identifier):
            raise ValueError("database names must be the ones derived from plugin_identifier")
        return self


class DesiredState(_NodeContractModel):
    """Everything one node should run, served at `GET /api/plugin-nodes/self/desired-state/`.

    `revision` is the sha256 of the canonical JSON of every field except `revision` and
    `generated_at`; it is also the response's ETag, so an unchanged document answers 304.
    """

    format: Literal[1]
    node: DesiredStateNode
    revision: Sha256Hex
    generated_at: AwareDatetime
    placements: Annotated[list[DesiredPlacement], Field(max_length=MAX_PLACEMENTS_PER_NODE)]


class RuntimeDatabaseCredentials(_NodeContractModel):
    """The secret the node needs, beyond the desired state, for a placement's database."""

    app_password: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")] = Field(
        repr=False
    )
    """The app role's password. It never changes for an installation, so
    `credentials_revision` does not depend on it."""


class RuntimeCredentials(_NodeContractModel):
    """The runtime file of one placement, served at `POST .../placements/{id}/runtime-credentials/`.

    `runtime_file` holds the plugin's secret settings in clear text: the node writes it, as
    is, to the plugin's runtime file (mode 0400, owned by the plugin's UID) and nowhere else.
    `database.app_password` is a secret too, and is not part of the runtime file: the node
    sets it on the app role and builds the process's `DATABASE_URL` from it. Validating
    either never prints a secret (see `_NodeContractModel`); that covers the nested runtime
    file only when it is validated through this model.
    """

    placement_id: PositiveInt
    credentials_revision: Sha256Hex
    settings_revision: NonNegativeInt
    runtime_file: RuntimeFile
    database: RuntimeDatabaseCredentials | None = None
    """Set exactly when the placement's desired state has `database`."""


class DatabaseReport(_NodeContractModel):
    """What the node observes about one placement's database."""

    installation_id: InstallationId
    """The installation the node provisioned; django_app ignores a report for another one."""

    state: Literal["provisioning", "ready", "failed"]
    applied_migrations: Annotated[list[MigrationName], Field(max_length=MAX_APPLIED_MIGRATIONS)]
    """The migration ledger, in the order the migrations were applied."""

    size_bytes: NonNegativeInt | None = None
    last_error: Annotated[str, StringConstraints(max_length=MAX_LAST_ERROR_LENGTH)] | None = None
    limits_restored_at: AwareDatetime | None = None
    """When the node last restored the app role's settings, in this agent's life."""


class PlacementReport(_NodeContractModel):
    """What the node observes about one placement."""

    placement_id: PositiveInt
    observed_state: ObservedProcessState
    observed_version: PackageVersion | None = None
    """The package version the running (or last started) process belongs to."""

    health: ProcessHealth
    pid: PositiveInt | None = None
    restarts: NonNegativeInt
    rss_mb: Annotated[float, Field(ge=0)] | None = None
    """Resident memory of every process of the plugin's UID, in MiB."""

    last_error: Annotated[str, StringConstraints(max_length=MAX_LAST_ERROR_LENGTH)] | None = None
    log_tail: Annotated[list[LogLine], Field(max_length=MAX_LOG_TAIL_LINES)] = Field(
        default_factory=list
    )
    """The last lines of the plugin's log; sent only when `observed_state` is `failed`."""

    applied_credentials_revision: Sha256Hex | None = None
    applied_settings_revision: NonNegativeInt | None = None
    applied_restart_generation: NonNegativeInt | None = None
    database: DatabaseReport | None = None
    """Null until the node has tried to provision the database in this agent's life."""


class NodeReport(_NodeContractModel):
    """The node's report, sent to `POST /api/plugin-nodes/self/reports/` every 10 s and on change."""

    format: Literal[1]
    agent_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    reported_at: AwareDatetime
    placements: Annotated[list[PlacementReport], Field(max_length=MAX_PLACEMENTS_PER_NODE)]


class HookInvocation(_NodeContractModel):
    """The answer to a hook job claim: the one call the node makes to the plugin's process.

    Sent as `POST http://127.0.0.1:<port><HOOK_PATHS[kind]>` with `assertion` in the
    `X-EpicStaff-Hook` header and `body` as the exact request body. The assertion is bound to
    the body's sha256 and expires `timeout_seconds` plus a minute after the claim, so the node
    makes the call at once. Neither is ever logged.
    """

    job_id: PositiveInt
    kind: HookKind
    attempt: PositiveInt
    organization_id: PositiveInt
    timeout_seconds: Annotated[int, Field(ge=1, le=max(MAX_HOOK_TIMEOUT_SECONDS.values()))]
    assertion: Annotated[str, StringConstraints(min_length=1, max_length=MAX_HOOK_ASSERTION_LENGTH)]
    body: Annotated[str, StringConstraints(min_length=2, max_length=MAX_HOOK_BODY_BYTES)]
    """The exact JSON text to send, UTF-8."""


class HookResult(_NodeContractModel):
    """What came of a claimed hook call, posted to `.../hook-jobs/{job_id}/result/`.

    `attempt` is the one the claim returned; a result for another attempt is refused.
    """

    attempt: PositiveInt
    outcome: Literal["succeeded", "failed"]
    error: Annotated[str, StringConstraints(max_length=MAX_HOOK_ERROR_MESSAGE_LENGTH)] | None = None
    """Why the call failed, for the SuperAdmin; null when it succeeded."""

    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    duration_ms: NonNegativeInt
