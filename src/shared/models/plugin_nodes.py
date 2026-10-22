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

import re
from dataclasses import dataclass
from datetime import UTC, datetime
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
from epicstaff_plugin.package_layout import MAX_MIGRATION_NAME_LENGTH, MIGRATION_NAME_PATTERN
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    model_validator,
)

__all__ = [
    "BACKUP_FILE_NAME_PATTERN",
    "CONTRACT_FORMAT",
    "DATABASE_NAME_PREFIX",
    "MAX_APPLIED_MIGRATIONS",
    "MAX_BACKUPS_PER_PLACEMENT",
    "MAX_LAST_ERROR_LENGTH",
    "MAX_LOG_LINE_LENGTH",
    "MAX_LOG_TAIL_LINES",
    "MAX_PENDING_HOOK_JOBS",
    "MAX_PLACEMENTS_PER_NODE",
    "NODE_PORT_RANGE",
    "BackupFileName",
    "BackupFileReport",
    "BackupReason",
    "DatabaseNames",
    "DatabaseReport",
    "DesiredDatabase",
    "DesiredDatabaseServer",
    "DesiredEgress",
    "DesiredHookJob",
    "DesiredPackage",
    "DesiredPlacement",
    "DesiredRemoval",
    "DesiredRestore",
    "DesiredRuntime",
    "DesiredState",
    "DesiredStateNode",
    "DesiredUpgrade",
    "HookInvocation",
    "HookResult",
    "LedgerEntry",
    "NodeReport",
    "PlacementReport",
    "RemovalReport",
    "RestoreReport",
    "RestoreStep",
    "RuntimeCredentials",
    "RuntimeDatabaseCredentials",
    "Sha256Hex",
    "UpgradeAdvance",
    "UpgradeReport",
    "UpgradeStage",
    "UpgradeStep",
    "backup_file_name",
    "database_names_for",
    "is_reportable_ledger_entry",
    "is_reportable_migration_name",
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
# The node reports at most this many backups of one placement, and is asked to delete at most
# this many at once.
MAX_BACKUPS_PER_PLACEMENT = 50
BACKUP_FILE_NAME_PATTERN = (
    r"^[0-9]{8}T[0-9]{6}Z-u([1-9][0-9]{0,18})-(pre_upgrade|pre_restore)\.dump$"
)
"""A backup's file name: when it was taken (UTC, to the second), the upgrade it belongs to and
why it was taken, e.g. `20261021T101500Z-u7-pre_upgrade.dump`. Group 1 is the upgrade id, group
2 the reason. `backup_file_name` builds one."""

_BACKUP_FILE_NAME = re.compile(BACKUP_FILE_NAME_PATTERN)

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
    StringConstraints(pattern=MIGRATION_NAME_PATTERN, max_length=MAX_MIGRATION_NAME_LENGTH),
]
"""A migration's file name under `database/migrations/`, e.g. `001_places.sql`: the package
layout's rule, so a ledger entry is reportable exactly when a package may hold the file."""

_MIGRATION_NAME = TypeAdapter(MigrationName)


def is_reportable_migration_name(value: object) -> bool:
    """Whether `value` may go in a `DatabaseReport` ledger: a `str` that names a package migration.

    The ledger is a table in the plugin's own database, and the plugin's migrations can write
    any row into it. The node keeps only the entries this accepts, so no row a plugin wrote can
    make its report invalid. Nothing else repeats this rule.
    """
    try:
        _MIGRATION_NAME.validate_python(value, strict=True)
    except ValidationError:
        return False
    return True


_SHA256_HEX = TypeAdapter(Sha256Hex)


def is_reportable_ledger_entry(name: object, sha256: object) -> bool:
    """Whether a row of the plugin's migration ledger may go in `DatabaseReport.ledger`.

    Both columns are plugin-writable, like the name `is_reportable_migration_name` checks: the
    entry is kept only when the name names a package migration and the digest is a sha256 in
    lower-case hex, both as `str`. The node keeps only the entries this accepts, so no row a
    plugin wrote can make its report invalid.
    """
    if not is_reportable_migration_name(name):
        return False
    try:
        _SHA256_HEX.validate_python(sha256, strict=True)
    except ValidationError:
        return False
    return True


BackupFileName = Annotated[str, StringConstraints(pattern=BACKUP_FILE_NAME_PATTERN)]
BackupReason = Literal["pre_upgrade", "pre_restore"]
"""Why a backup was taken: before an upgrade's first migration, or before a restore replaced
the database."""

UpgradeStage = Literal["preparing", "maintenance", "migrating"]
"""How far EpicStaff has let an upgrade go: `preparing` while the plugin keeps running,
`maintenance` once its process may be stopped and its database backed up, `migrating` once the
new version's migrations may run and its process start."""

UpgradeStep = Literal["download", "verify", "build", "drain", "stop", "backup", "migrate", "start"]
RestoreStep = Literal["verify", "backup", "close", "recreate", "restore", "settings", "assert"]


def backup_file_name(created_at: datetime, upgrade_id: int, reason: str) -> str:
    """The file name of a backup taken at `created_at` for an upgrade, by `reason`.

    The time is written in UTC, to the second, so names sort by when they were taken.

    Raises:
        ValueError: `created_at` has no time zone, or the name would not match
            `BACKUP_FILE_NAME_PATTERN` (an upgrade id that is not a positive integer of at most
            19 digits, or another reason).
    """
    if created_at.tzinfo is None:
        raise ValueError("created_at must carry a time zone")
    name = f"{created_at.astimezone(UTC):%Y%m%dT%H%M%SZ}-u{upgrade_id}-{reason}.dump"
    if not _BACKUP_FILE_NAME.fullmatch(name):
        raise ValueError(f"{name!r} is not a backup file name")
    return name


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
    healthy and runs with the desired `credentials_revision`. An `install` or `upgrade` job
    also waits until the runtime file holds a service-account key for `organization_id`. An
    `org_removed` job does not: the organization's plugin data is being deleted, and it has
    no key any more.
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


class DesiredUpgrade(_NodeContractModel):
    """A new version of the plugin the node should bring the placement to, stage by stage.

    `stage` is as far as EpicStaff has let the upgrade go. In `preparing` the placement's
    `package` and `runtime` are still the running version's, and the node only gets `target`
    ready next to it without touching the running process; it then asks to stop the plugin
    (`POST .../upgrades/{upgrade_id}/advance/`, `to: maintenance`). From `maintenance` on, the
    placement's `package`, `runtime`, `database` and `egress` are the target's. The node asks
    once more (`to: migrations`), with the backup it took when `backup` is `required`.
    """

    upgrade_id: PositiveInt
    stage: UpgradeStage
    from_version: PackageVersion
    """The version the plugin ran when the upgrade started."""

    target: DesiredPackage
    target_runtime: DesiredRuntime
    backup: Literal["required", "taken", "not_needed"]
    """`required`: back the database up before asking for `migrations`; `taken`: EpicStaff has
    recorded this upgrade's backup already; `not_needed`: the plugin had no database ready
    before the upgrade."""

    backup_bytes_needed: NonNegativeInt
    """The database's last reported size when `backup` is `required`, else 0: the free disk
    space the node checks for before it stops the plugin."""

    failed: bool = False
    """The stage failed, as the node reported. The node runs none of its steps again, also
    after an agent restart, until it is false again: a Retry clears it (and raises the
    placement's `restart_generation`), and so does a newer target. A restore of the database
    still runs while it is set."""


class DesiredRestore(_NodeContractModel):
    """A backup the node should restore into the placement's database, during a failed upgrade.

    The node checks the file against `backup_sha256` and the backup's installation before it
    changes anything, takes a `pre_restore` backup of the database as it is, then replaces the
    database with the backup. It does not start the process afterwards.
    """

    restore_id: PositiveInt
    upgrade_id: PositiveInt
    backup_file: BackupFileName
    backup_sha256: Sha256Hex


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
    """`stopped` while the plugin cannot start, e.g. a required setting is missing, and while
    it is uninstalled or being deleted, except when an `org_removed` hook job is due or
    running: the process then runs only to make that call."""

    restart_generation: NonNegativeInt
    package: DesiredPackage
    runtime: DesiredRuntime
    credentials_revision: Sha256Hex
    settings_revision: NonNegativeInt
    hook_jobs: Annotated[list[DesiredHookJob], Field(max_length=MAX_PENDING_HOOK_JOBS)] = Field(
        default_factory=list
    )
    """Pending hook jobs, oldest first. An install job is listed only while its grant exists
    and is still being granted; an `org_removed` job once its next attempt is due."""

    database: DesiredDatabase | None = None
    """Set exactly when the package's manifest has a `database` section, also while the
    plugin is uninstalled or being deleted, so a process started for an `org_removed` hook
    still reaches its data. It moves to the plugin's `DesiredRemoval` once the node is asked
    to remove the plugin."""

    egress: DesiredEgress = Field(default_factory=lambda: DesiredEgress(hosts=[]))
    upgrade: DesiredUpgrade | None = None
    """Set while an upgrade of the plugin is open. A change of `upgrade` alone restarts
    nothing: the running process is stopped only for the `maintenance` stage, and from then on
    the placement's `package` is the target."""

    restore: DesiredRestore | None = None
    """Set while a restore of the database is asked for or running."""

    backups_to_delete: Annotated[
        list[BackupFileName], Field(max_length=MAX_BACKUPS_PER_PLACEMENT)
    ] = Field(default_factory=list)
    """The backups of this plugin the node deletes, dump and metadata both; it deletes no other."""

    @model_validator(mode="after")
    def _database_names_belong_to_the_plugin(self) -> Self:
        _assert_database_names_are_the_plugins(self.database, self.plugin_identifier)
        return self

    @model_validator(mode="after")
    def _upgrade_matches_the_placement(self) -> Self:
        upgrade = self.upgrade
        if upgrade is None:
            return self
        target_runtime = upgrade.target_runtime
        if (target_runtime.port, target_runtime.unix_uid) != (
            self.runtime.port,
            self.runtime.unix_uid,
        ):
            raise ValueError("an upgrade runs on the placement's port and user id")
        if upgrade.stage == "preparing":
            if self.package == upgrade.target:
                raise ValueError("while preparing, package is the running version")
            return self
        if self.package != upgrade.target or self.runtime != target_runtime:
            raise ValueError("from maintenance on, package and runtime are the target's")
        if self.hook_jobs:
            raise ValueError("no hook job is listed while the plugin is stopped for an upgrade")
        return self

    @model_validator(mode="after")
    def _restore_belongs_to_the_open_upgrade(self) -> Self:
        restore = self.restore
        if restore is None:
            return self
        upgrade = self.upgrade
        if (
            upgrade is None
            or upgrade.stage != "migrating"
            or restore.upgrade_id != upgrade.upgrade_id
        ):
            raise ValueError("a restore belongs to the open upgrade, in its migrating stage")
        if self.database is None:
            raise ValueError("a restore needs the placement's database")
        if restore.backup_file in self.backups_to_delete:
            raise ValueError("the backup being restored cannot be deleted")
        return self


class DesiredRemoval(_NodeContractModel):
    """A plugin the node should remove for good, and everything the node keeps for it.

    The node stops its process, drops its database and roles when `database` is set, deletes
    its code, environment, logs and data, and reports the outcome in `RemovalReport` until
    the removal leaves the desired state. EpicStaff frees the port and the Unix user id only
    after the node has reported the removal done.

    When `database` is set, its four names must be `database_names_for(plugin_identifier)`,
    so a removal can never name another plugin's database or roles.
    """

    placement_id: PositiveInt
    plugin_identifier: PluginIdentifier
    unix_uid: UnixUid
    """Every process of this user id is ended, and its files are deleted."""

    port: NetworkPort
    generation: NonNegativeInt
    """The placement's `restart_generation`: a change asks the node to try a failed removal
    again."""

    database: DesiredDatabase | None = None
    """The database and roles to drop; None when the plugin never had a database. The node
    drops them only when their marker is this record's `installation_id`. The limit fields
    mean nothing for a drop."""

    @model_validator(mode="after")
    def _database_names_belong_to_the_plugin(self) -> Self:
        _assert_database_names_are_the_plugins(self.database, self.plugin_identifier)
        return self


def _assert_database_names_are_the_plugins(
    database: DesiredDatabase | None, identifier: str
) -> None:
    if database is None:
        return
    names = DatabaseNames(
        database=database.database_name,
        owner_role=database.owner_role,
        app_role=database.app_role,
        job_role=database.job_role,
    )
    if names != database_names_for(identifier):
        raise ValueError("database names must be the ones derived from plugin_identifier")


class DesiredState(_NodeContractModel):
    """Everything one node should run, served at `GET /api/plugin-nodes/self/desired-state/`.

    `revision` is the sha256 of the canonical JSON of every field except `revision` and
    `generated_at`; it is also the response's ETag, so an unchanged document answers 304.
    A placement is either run (`placements`) or removed (`removals`), never both.
    """

    format: Literal[1]
    node: DesiredStateNode
    revision: Sha256Hex
    generated_at: AwareDatetime
    placements: Annotated[list[DesiredPlacement], Field(max_length=MAX_PLACEMENTS_PER_NODE)]
    removals: Annotated[list[DesiredRemoval], Field(max_length=MAX_PLACEMENTS_PER_NODE)] = Field(
        default_factory=list
    )
    """Plugins the node should remove, with what to drop and delete."""

    @model_validator(mode="after")
    def _no_placement_is_run_and_removed(self) -> Self:
        run = {placement.placement_id for placement in self.placements}
        if any(removal.placement_id in run for removal in self.removals):
            raise ValueError("a placement cannot be in both placements and removals")
        return self


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


class LedgerEntry(_NodeContractModel):
    """One migration the plugin's database has applied, as its ledger records it."""

    name: MigrationName
    sha256: Sha256Hex
    """Of the file's bytes as packaged: the digest the package's `CONTENTS.json` lists for it."""


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

    ledger: Annotated[list[LedgerEntry], Field(max_length=MAX_APPLIED_MIGRATIONS)] | None = None
    """The ledger with each file's digest, in the order the migrations were applied, as the
    node last read it, whatever `state` is: after a failed migration it holds the files
    applied before the failure. None while the node has not read it in this agent's life, so
    EpicStaff keeps the ledger it has. Only entries `is_reportable_ledger_entry` accepts."""


class BackupFileReport(_NodeContractModel):
    """A complete backup the node holds: the dump and its metadata, both under final names."""

    file_name: BackupFileName
    installation_id: InstallationId
    """The installation whose database was dumped; EpicStaff ignores a backup of another."""

    upgrade_id: PositiveInt
    reason: BackupReason
    version: PackageVersion
    """The plugin version whose migrations the database held when it was dumped."""

    size_bytes: PositiveInt
    sha256: Sha256Hex
    """Of the dump file."""

    created_at: AwareDatetime
    """When the dump was taken, by the node's clock."""

    @model_validator(mode="after")
    def _file_name_matches_the_fields(self) -> Self:
        match = _BACKUP_FILE_NAME.fullmatch(self.file_name)
        named = (int(match.group(1)), match.group(2)) if match else None
        if named != (self.upgrade_id, self.reason):
            raise ValueError("file_name names another upgrade or reason than the backup's")
        return self


class UpgradeReport(_NodeContractModel):
    """How the node's work on the desired placement's upgrade goes.

    EpicStaff ignores a report whose `generation` or `stage` is not the upgrade's current one,
    so a report sent before the node saw a Retry or a newer target cannot fail it again.
    """

    upgrade_id: PositiveInt
    generation: NonNegativeInt
    """The placement's `restart_generation` the node is working to."""

    stage: UpgradeStage
    step: UpgradeStep
    """The step the node is at, or the one that failed."""

    state: Literal["working", "failed"]
    """`failed` on an error the node does not retry by itself, until `generation` changes."""

    last_error: Annotated[str, StringConstraints(max_length=MAX_LAST_ERROR_LENGTH)] | None = None
    """Why the step failed, or the error a retried step last hit."""


class RestoreReport(_NodeContractModel):
    """How the node's restore of a backup into the placement's database goes."""

    restore_id: PositiveInt
    state: Literal["running", "succeeded", "failed"]
    step: RestoreStep
    pre_restore_backup: BackupFileName | None = None
    """The backup of the database taken before it was replaced, once there is one."""

    last_error: Annotated[str, StringConstraints(max_length=MAX_LAST_ERROR_LENGTH)] | None = None


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

    upgrade: UpgradeReport | None = None
    """Set while the desired placement has an upgrade."""

    restore: RestoreReport | None = None
    """Set while the desired placement has a restore."""

    backups: (
        Annotated[list[BackupFileReport], Field(max_length=MAX_BACKUPS_PER_PLACEMENT)] | None
    ) = None
    """Every complete backup the node holds for the plugin, newest first: the whole inventory,
    so EpicStaff marks a recorded backup it does not list deleted. None when the node could not
    read its backups, which marks none."""


class RemovalReport(_NodeContractModel):
    """How the node's removal of one placement goes.

    `removing` while the steps run, `removed` once nothing of the plugin is left on the node
    (kept while the removal stays in the desired state), `failed` with `last_error` on an
    error the node does not retry by itself. EpicStaff ignores a report whose `generation`
    is not the removal's current one.
    """

    placement_id: PositiveInt
    generation: NonNegativeInt
    state: Literal["removing", "removed", "failed"]
    last_error: Annotated[str, StringConstraints(max_length=MAX_LAST_ERROR_LENGTH)] | None = None
    """Why the removal failed, or the error a retried step last hit."""


class NodeReport(_NodeContractModel):
    """The node's report, sent to `POST /api/plugin-nodes/self/reports/` every 10 s and on change."""

    format: Literal[1]
    agent_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    reported_at: AwareDatetime
    placements: Annotated[list[PlacementReport], Field(max_length=MAX_PLACEMENTS_PER_NODE)]
    removals: Annotated[list[RemovalReport], Field(max_length=MAX_PLACEMENTS_PER_NODE)] = Field(
        default_factory=list
    )


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


class UpgradeAdvance(_NodeContractModel):
    """The node asking to take an upgrade to its next stage.

    Posted to `POST /api/plugin-nodes/self/upgrades/{upgrade_id}/advance/`. `maintenance` once
    the target is ready, to stop the plugin; `migrations` once it is stopped and, when the
    desired upgrade's `backup` is `required`, backed up, with that backup. Asking for the stage
    the upgrade is already in changes nothing.
    """

    to: Literal["maintenance", "migrations"]
    backup: BackupFileReport | None = None

    @model_validator(mode="after")
    def _backup_only_with_migrations(self) -> Self:
        if self.to == "maintenance" and self.backup is not None:
            raise ValueError("a backup comes only with the request for migrations")
        return self
