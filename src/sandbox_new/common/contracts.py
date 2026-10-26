"""Wire contracts exchanged between the manager and the worker.

These are the serialized shapes that cross the manager/worker boundary (today an
in-process queue, later a network transport). They are presentation-layer only:
the manager builds an ``ExecutionJobMessage`` when it dispatches and the worker
emits an ``ExecutionResultMessage`` when it is done. Neither type may appear in
any domain or application module -- those layers work with their own models.
"""

from typing import Any, Literal

from foundation.schemas import Schema
from pydantic import Field

__all__ = [
    "ExecutionJobMessage",
    "ExecutionResultMessage",
    "StorageCredentialsMessage",
    "StorageMutationsMessage",
]


class StorageCredentialsMessage(Schema):
    """Object-store credentials issued upstream for one execution."""

    access_key: str
    secret_key: str


class ExecutionJobMessage(Schema):
    """One code-execution request handed from the manager to the worker."""

    execution_id: str
    venv_hash: str
    code: str
    entrypoint: str
    func_kwargs: dict[str, Any] = Field(default_factory=dict)
    global_kwargs: dict[str, Any] = Field(default_factory=dict)
    # Resolved plaintext. Transient: this message lives only in RAM and is never
    # persisted, so secrets reach the worker without ever touching disk.
    secrets: dict[str, str] = Field(default_factory=dict)
    use_storage: bool = False
    storage_allowed_paths: list[str] = Field(default_factory=list)
    storage_org_prefix: str | None = None
    # Issued by django_app, not by this service. Transient like `secrets`: RAM-only,
    # never persisted, so they reach the worker without ever touching disk.
    storage_credentials: StorageCredentialsMessage | None = None
    session_id: int | None = None
    # Per-job override; the worker falls back to its configured default when None.
    timeout: float | None = None
    # Routing hint only, echoed back on the result so the manager can publish it to the
    # channel crew alone reads. The worker never acts on it.
    reply_to_crew_channel: bool = False
    # `time.monotonic()` seconds after which the worker fails the job instead of running
    # it. A monotonic reading means nothing in another process: this is valid only
    # because the manager and the worker are one process.
    queue_deadline: float | None = None


class StorageMutationsMessage(Schema):
    """Storage changes an execution reported, carried back for the manager to publish."""

    org_prefix: str
    session_id: int | None = None
    mutations: list[dict] = Field(default_factory=list)


class ExecutionResultMessage(Schema):
    """The outcome of one execution, handed from the worker back to the manager."""

    execution_id: str
    result: str | None = None
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    mutations: StorageMutationsMessage | None = None
    # Echoed from the job so the publisher knows which result channel this one belongs on.
    reply_to_crew_channel: bool = False
    # True only when the worker really executed the job. A job failed without running
    # (venv failed, dispatch failed, expired in the queue) keeps False, so it does not
    # count towards the drain rate admission control predicts queue waits from.
    ran: bool = False
    # The next two only feed the publisher's BENCH checkpoint; neither is published.
    session_id: int | None = None
    # Set only on a result for a job that never ran. Spelled out rather than imported from
    # manager.domain.types: this module must not depend on either side of the seam.
    not_run_reason: Literal["venv_failed", "dispatch_failed"] | None = None
