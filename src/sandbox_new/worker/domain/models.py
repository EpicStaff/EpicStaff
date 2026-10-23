"""Worker domain models: the value objects the worker reasons about.

Pure data, no behavior. The worker owns its own ``Job`` -- deliberately not the
manager's ``Job`` entity nor the ``src/shared`` task contract. It carries no venv
libraries and no status: the manager decides libraries and gates readiness, the
worker only executes. A Job is an immutable execution request, so it is a value
object, not an entity with a lifecycle. ``Jail`` and ``NetworkDecision`` are the
outputs of the isolation domain services (see ``domain/services/isolation.py``).
"""

from typing import Any

from foundation.base import ValueObject
from pydantic import Field

from worker.domain.enums import NetworkPolicy

__all__ = [
    "ExecutionResult",
    "IsolationPlan",
    "Jail",
    "Job",
    "NetworkDecision",
    "StorageCredentials",
    "StorageMutations",
]


class StorageCredentials(ValueObject):
    """Scoped, short-lived storage credentials carried on the job.

    Issued and revoked upstream by django_app, never minted here. Transient: handed
    to the child via env and then dropped; never persisted or logged.
    """

    access_key: str
    secret_key: str


class Job(ValueObject):
    execution_id: str
    venv_hash: str
    code: str
    entrypoint: str
    func_kwargs: dict[str, Any] = Field(default_factory=dict)
    global_kwargs: dict[str, Any] = Field(default_factory=dict)
    # Resolved plaintext, RAM-only. Never persisted and never logged.
    secrets: dict[str, str] = Field(default_factory=dict)
    use_storage: bool = False
    storage_allowed_paths: list[str] = Field(default_factory=list)
    storage_org_prefix: str | None = None
    # Issued upstream and carried here; required whenever `use_storage` is set.
    storage_credentials: StorageCredentials | None = None
    session_id: int | None = None
    # None means "use the worker's configured default timeout".
    timeout: float | None = None
    # Carried for the manager's benefit only: the worker echoes it onto the result so the
    # manager can publish to the channel the submitter listens on. Nothing here reads it.
    reply_to_crew_channel: bool = False
    # `time.monotonic()` seconds after which the job is failed instead of run.
    queue_deadline: float | None = None


class Jail(ValueObject):
    """The filesystem allowlist a confined execution is restricted to."""

    read_write: tuple[str, ...]
    read_only: tuple[str, ...]
    read_exec: tuple[str, ...]


class NetworkDecision(ValueObject):
    policy: NetworkPolicy
    allowed_tcp_ports: tuple[int, ...] = ()


class ExecutionResult(ValueObject):
    """The outcome of one execution, as the worker hands it back to the manager."""

    execution_id: str
    result: str | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    # Echoed from the job; see ``Job.reply_to_crew_channel``.
    reply_to_crew_channel: bool = False
    # The job was really executed, as opposed to failed without running.
    ran: bool = False


class StorageMutations(ValueObject):
    """The storage changes an execution reported, as published to the manager."""

    execution_id: str
    org_prefix: str
    session_id: int | None = None
    mutations: list[dict] = Field(default_factory=list)


class IsolationPlan(ValueObject):
    """The isolation decisions for one execution, aggregated for the launch step.

    The output of the ``BuildIsolationPlan`` application step. ``jail`` is ``None``
    when the execution runs unconfined (no Landlock); the launch step still wraps
    it in the launcher when the network must be blocked via seccomp.
    """

    landlock_abi: int
    network: NetworkDecision
    isolate_signals: bool = False
    jail: Jail | None = None
