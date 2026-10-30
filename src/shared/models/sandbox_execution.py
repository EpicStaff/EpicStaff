from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "ExecutionRequest",
    "ExecutionStorageCredentials",
]


class ExecutionStorageCredentials(BaseModel):
    """Object-store credentials the producer issues for one execution.

    Plaintext, so both keys are kept out of `repr()` and therefore out of log lines.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    access_key: str = Field(min_length=1, repr=False)
    secret_key: str = Field(min_length=1, repr=False)


class ExecutionRequest(BaseModel):
    """The body a producer posts to the sandbox's `POST /executions`.

    The sandbox's submit schema subclasses this one, so the field set and types are the
    wire contract on both sides. `secrets` and `storage_credentials` carry plaintext
    and are excluded from `repr()`.
    """

    model_config = ConfigDict(frozen=True, from_attributes=True)

    execution_id: str
    # Optional: tool paths at session start can submit without a session.
    session_id: int | None = None
    code: str
    entrypoint: str
    global_kwargs: dict[str, Any] = {}
    func_kwargs: dict[str, Any] = {}
    secrets: dict[str, Any] = Field(default={}, repr=False)
    venv_id: int | None = None
    use_storage: bool = False
    storage_allowed_paths: list[str] = []
    storage_org_prefix: str | None = None
    storage_credentials: ExecutionStorageCredentials | None = Field(default=None, repr=False)
    timeout: float | None = None
    # Asks for the result on crew's private result channel instead of the shared one.
    reply_to_crew_channel: bool = False
