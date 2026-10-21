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

from typing import Annotated, Literal

from epicstaff_plugin.contracts.hook_api import (
    MAX_HOOK_ASSERTION_LENGTH,
    MAX_HOOK_BODY_BYTES,
    MAX_HOOK_ERROR_MESSAGE_LENGTH,
    HookKind,
)
from epicstaff_plugin.contracts.manifest import MAX_HOOK_TIMEOUT_SECONDS
from epicstaff_plugin.contracts.runtime import RuntimeFile
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints

__all__ = [
    "CONTRACT_FORMAT",
    "MAX_HOOK_ERROR_LENGTH",
    "MAX_LAST_ERROR_LENGTH",
    "MAX_LOG_LINE_LENGTH",
    "MAX_LOG_TAIL_LINES",
    "MAX_PENDING_HOOK_JOBS",
    "MAX_PLACEMENTS_PER_NODE",
    "NODE_PORT_RANGE",
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
]

CONTRACT_FORMAT = 1
MAX_LAST_ERROR_LENGTH = 2000
MAX_LOG_TAIL_LINES = 200
MAX_LOG_LINE_LENGTH = 1000
# The node's port and UID ranges hold at most this many placements.
MAX_PLACEMENTS_PER_NODE = 1000
# A desired placement lists at most this many pending hook jobs.
MAX_PENDING_HOOK_JOBS = 1000
MAX_HOOK_ERROR_LENGTH = MAX_HOOK_ERROR_MESSAGE_LENGTH
# The ports a node gives plugin processes: first and last, both included. The node agent
# holds every port of it from start-up; django_app registers the node with it and gives each
# placement the lowest free one.
NODE_PORT_RANGE = (20001, 20999)

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

DesiredProcessState = Literal["running", "stopped"]
ObservedProcessState = Literal[
    "unknown", "downloading", "building", "starting", "running", "stopped", "failed"
]
ProcessHealth = Literal["ok", "failing", "unknown"]
CpuPriority = Literal["normal", "low"]
PluginPython = Literal["3.12", "3.13"]
PackageTrust = Literal["trusted", "untrusted"]


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


class DesiredPlacement(_NodeContractModel):
    """One plugin process the node should run (or keep stopped).

    A change of `settings_revision`, `restart_generation`, `runtime` or `package` makes the
    node refetch the runtime credentials and restart the process. A change of
    `credentials_revision` alone makes it refetch them and rewrite the runtime file without a
    restart.
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


class RuntimeCredentials(_NodeContractModel):
    """The runtime file of one placement, served at `POST .../placements/{id}/runtime-credentials/`.

    `runtime_file` holds the plugin's secret settings in clear text: the node writes it, as
    is, to the plugin's runtime file (mode 0400, owned by the plugin's UID) and nowhere else.
    Validating it never prints a secret (see `_NodeContractModel`); that covers the nested
    runtime file only when it is validated through this model.
    """

    placement_id: PositiveInt
    credentials_revision: Sha256Hex
    settings_revision: NonNegativeInt
    runtime_file: RuntimeFile


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
    error: Annotated[str, StringConstraints(max_length=MAX_HOOK_ERROR_LENGTH)] | None = None
    """Why the call failed, for the SuperAdmin; null when it succeeded."""

    http_status: Annotated[int, Field(ge=100, le=599)] | None = None
    duration_ms: NonNegativeInt
