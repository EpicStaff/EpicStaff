"""Wire contracts exchanged between the manager and the worker.

These are the serialized shapes that cross the manager/worker boundary (today an
in-process queue, later a network transport). They are presentation-layer only:
the manager builds an ``ExecutionJobMessage`` when it dispatches and the worker
emits an ``ExecutionResultMessage`` when it is done. Neither type may appear in
any domain or application module -- those layers work with their own models.
"""

from typing import Any

from foundation.base import Schema
from pydantic import Field

__all__ = ["ExecutionJobMessage", "ExecutionResultMessage", "StorageMutationsMessage"]


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
    session_id: int | None = None
    # Per-job override; the worker falls back to its configured default when None.
    timeout: float | None = None


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
