"""The messages between the agent and the launcher, over a `SOCK_SEQPACKET` Unix socket.

One request per packet, answered by one response packet. Both are JSON objects. Requests are
validated here with `extra="forbid"`: the launcher runs as root and accepts nothing it does
not expect. A request may carry file descriptors (`SCM_RIGHTS`):

| Operation            | Descriptors in the request             | Descriptors in the response |
|----------------------|----------------------------------------|-----------------------------|
| `spawn`              | the output pipe, then the agent's listening socket | a pidfd of the new process |
| `write_runtime_file` | a memfd holding the file's content     | -                           |
| `measure_disk`       | -                                      | a pipe the result arrives on |
| `remove_plugin`      | -                                      | a pipe the result arrives on |

The content of a runtime file travels in a memfd rather than in the packet: a packet must
fit the socket's buffer, and a runtime file with long text settings may not.

A response is `{"ok": true, "result": {...}}` or `{"ok": false, "error": "<message>"}`.
"""

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, field_validator

from es_plugins.layout import PLUGIN_IDENTIFIER_PATTERN, VERSION_SEGMENT_PATTERN

MAX_MESSAGE_BYTES = 64 * 1024
MAX_DESCRIPTORS = 2  # spawn sends two: the output pipe and the listening socket
MAX_ARGUMENTS = 64
MAX_ARGUMENT_LENGTH = 4096
MAX_ENVIRONMENT_ENTRIES = 64
MAX_ENVIRONMENT_VALUE_LENGTH = 8192

PluginIdentifier = Annotated[str, StringConstraints(pattern=PLUGIN_IDENTIFIER_PATTERN.pattern)]
VersionSegment = Annotated[str, StringConstraints(pattern=VERSION_SEGMENT_PATTERN.pattern)]
Uid = Annotated[int, Field(ge=1, le=2**31 - 1)]
EnvironmentName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")]


class _Message(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PreparePlugin(_Message):
    """Create or repair the plugin's HOME, TMPDIR, code, venv and runtime directories."""

    operation: Literal["prepare_plugin"] = "prepare_plugin"
    plugin: PluginIdentifier
    uid: Uid


class InstallCode(_Message):
    """Copy the agent's unpacked `backend/src` into the plugin's root-owned code directory."""

    operation: Literal["install_code"] = "install_code"
    plugin: PluginIdentifier
    uid: Uid
    version: VersionSegment

    @field_validator("version")
    @classmethod
    def _no_dot_segments(cls, version: str) -> str:
        if ".." in version:
            raise ValueError("must not contain '..'")
        return version


class WriteRuntimeFile(_Message):
    """Replace the plugin's runtime file atomically with the content of the attached memfd."""

    operation: Literal["write_runtime_file"] = "write_runtime_file"
    plugin: PluginIdentifier
    uid: Uid


class Spawn(_Message):
    """Start a process as the plugin's UID.

    Two descriptors are attached, in order: the pipe its output goes to, and the agent's
    listening socket, which becomes the child's fd 3 so it serves on a port only the agent
    could bind. The launcher chooses the working directory (the plugin's HOME), the resource
    limits, `oom_score_adj`, the session and the `EPICSTAFF_PLUGIN_LISTEN_FD` variable; the
    agent chooses the command and the rest of the environment.
    """

    operation: Literal["spawn"] = "spawn"
    plugin: PluginIdentifier
    uid: Uid
    argv: Annotated[
        list[Annotated[str, StringConstraints(min_length=1, max_length=MAX_ARGUMENT_LENGTH)]],
        Field(min_length=1, max_length=MAX_ARGUMENTS),
    ]
    environment: Annotated[
        dict[
            EnvironmentName,
            Annotated[str, StringConstraints(max_length=MAX_ENVIRONMENT_VALUE_LENGTH)],
        ],
        Field(max_length=MAX_ENVIRONMENT_ENTRIES),
    ]
    nice: Literal[0, 10]

    @field_validator("argv", "environment")
    @classmethod
    def _no_nul(cls, value):
        texts = value if isinstance(value, list) else list(value.values())
        if any("\0" in text for text in texts):
            raise ValueError("must not contain NUL characters")
        return value


class TerminateUid(_Message):
    """Send SIGTERM to every process of the UID once, from a helper running as that UID."""

    operation: Literal["terminate_uid"] = "terminate_uid"
    uid: Uid


class KillUid(_Message):
    """SIGKILL every process of the UID until none is left."""

    operation: Literal["kill_uid"] = "kill_uid"
    uid: Uid


class ExitStatus(_Message):
    """The exit status of a process the launcher started and has reaped, if it has."""

    operation: Literal["exit_status"] = "exit_status"
    pid: Annotated[int, Field(gt=1)]


class MeasureDisk(_Message):
    """Measure the plugin's HOME in a helper (see `disk_measurement`); the answer is a pipe.

    The limits only bound the scan's cost: it stops once one is passed.
    """

    operation: Literal["measure_disk"] = "measure_disk"
    plugin: PluginIdentifier
    uid: Uid
    max_bytes: Annotated[int, Field(ge=1)]
    max_files: Annotated[int, Field(ge=1)]


class PurgeData(_Message):
    """Kill the UID's processes and delete the plugin's HOME, as that UID."""

    operation: Literal["purge_data"] = "purge_data"
    plugin: PluginIdentifier
    uid: Uid


class RemovePlugin(_Message):
    """Kill the UID's processes, then delete everything the node keeps for the plugin.

    In order, each step fine to repeat: every process of the UID is killed; then, in a helper
    whose result arrives on the pipe in the answer (see `plugin_removal`), its System V IPC
    objects are removed, its HOME is deleted as the UID, `plugins/<id>/` and `/run/es_plugins/<id>/`
    are deleted, and the empty `venvs/<id>/` is removed (the agent empties it first).
    """

    operation: Literal["remove_plugin"] = "remove_plugin"
    plugin: PluginIdentifier
    uid: Uid


LauncherRequest = Annotated[
    PreparePlugin
    | InstallCode
    | WriteRuntimeFile
    | Spawn
    | TerminateUid
    | KillUid
    | ExitStatus
    | MeasureDisk
    | PurgeData
    | RemovePlugin,
    Field(discriminator="operation"),
]
REQUEST_ADAPTER: TypeAdapter[LauncherRequest] = TypeAdapter(LauncherRequest)
DESCRIPTORS_EXPECTED = {"spawn": 2, "write_runtime_file": 1}


class SpawnResult(_Message):
    pid: int


class KillResult(_Message):
    rounds: int
    remaining: list[int]


class ExitStatusResult(_Message):
    status: int | None
    """`os.waitstatus_to_exitcode` of the process: negative for a signal; null while running."""


def encode_request(request: _Message) -> bytes:
    return request.model_dump_json().encode()


def decode_request(packet: bytes) -> LauncherRequest:
    """Parse a request packet. Raises `pydantic.ValidationError` for anything unexpected."""
    return REQUEST_ADAPTER.validate_json(packet)


def encode_success(result: _Message | None = None) -> bytes:
    payload = {"ok": True, "result": result.model_dump() if result is not None else {}}
    return json.dumps(payload).encode()


def encode_failure(error: str) -> bytes:
    return json.dumps({"ok": False, "error": error[:2000]}).encode()
