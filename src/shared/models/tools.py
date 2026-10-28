from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .ai_providers import EmbedderData, LLMData
from .storage_scope import StorageCredentials, StorageScopedData


class ToolConfigData(BaseModel):
    id: int
    llm: LLMData | None = None
    embedder: EmbedderData | None = None
    tool_init_configuration: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class ConfiguredToolData(BaseModel):
    name_alias: str
    tool_config: ToolConfigData

    model_config = ConfigDict(from_attributes=True)


class McpToolData(BaseModel):
    """
    Configuration for a FastMCP client connecting to remote MCP tools via SSE.
    """

    transport: str
    """URL of the remote MCP server (SSE). Required."""
    tool_name: str

    timeout: float | None = 30
    """Request timeout in seconds. Recommended to set."""

    auth: str | None = None
    """Authorization token or OAuth string, if the server requires it."""

    auth_secret_id: int | None = Field(default=None, exclude=True)
    """In-memory carrier for SecretResolver; excluded from every dump."""

    init_timeout: float | None = 10
    """Timeout for session initialization. Optional, default is 10 seconds."""

    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
    )


class PythonCodeData(StorageScopedData):
    code: str
    entrypoint: str
    # The venv this code runs in; None means the sandbox's default venv. The venv
    # is the only place libraries come from, so there is nothing else to declare.
    venv_id: int | None = None
    global_kwargs: dict[str, Any] | None = None
    execution_timeout: int | None = None
    """Seconds a single run of this code may take. None makes the sandbox apply
    SANDBOX_DEFAULT_EXECUTION_TIMEOUT."""

    secret_names: list[str] = Field(default_factory=list, exclude=True)
    """Names this code is *allowed* to read — its declared allow-list.

    Read from PythonCode.secrets, the relation written through `secret_ids`. Not
    from the code: parse_secret_names() only checks that the code asks for nothing
    outside this set. Everything listed here is injected whether the code reads it
    or not, which is what lets a computed name like get_secret(f"KEY_{env}")
    resolve.

    Excluded from every dump, so the names never reach the Redis payload or
    anything persisted from this model. They are not credentials, but they are
    the caller's data and nothing downstream of Redis needs them.
    """

    secrets: dict[str, str] = Field(default_factory=dict)
    """{name: plaintext}, filled on the resolved copy only.

    NOT excluded: this is how the resolved value reaches crew — redis_service
    publishes `resolved.model_dump_json()`, and if this field were excluded
    that dump could never carry it, no matter how it was filled.

    This is safe because resolution happens only on the deep copy that
    SecretResolver.resolve_payload() returns, never on the caller's object.
    The caller's object stays unresolved (see redis_service.publish_session_data),
    so its `secrets` is always the empty default — never plaintext; only the
    published copy carries values. Nothing prevents future code from resolving
    in place instead of on a copy; that discipline, not a Field flag, is what
    keeps plaintext off the caller's object and out of anything persisted from it.
    """

    model_config = ConfigDict(from_attributes=True)


class ArgsSchema(BaseModel):
    type: Literal["object"] = "object"
    title: str = "ArgumentsSchema"
    properties: dict[str, Any]
    required: list[str] = []


class PythonCodeToolData(BaseModel):
    id: int
    name: str
    description: str
    variables: list[dict] = []
    args_schema: ArgsSchema | None = None
    python_code: PythonCodeData

    model_config = ConfigDict(from_attributes=True)


class BaseToolData(BaseModel):
    unique_name: str
    data: PythonCodeToolData | McpToolData

    # validator exist only in crew and realtime
    @model_validator(mode="before")
    @classmethod
    def validate_data(cls, values: dict):
        unique_name = values.get("unique_name", "")
        data = values.get("data", {})

        try:
            prefix, id = unique_name.split(":")
            assert prefix != ""
            assert id != ""
        except ValueError as e:
            raise ValueError(
                "Invalid unique_name. Unique name should be splited by `:`. \nFor example: python-code-tool:1"
            ) from e
        if prefix in {
            "python-code-tool",
            "python-code-tool-config",
        }:
            values["data"] = (
                data if isinstance(data, PythonCodeToolData) else PythonCodeToolData(**data)
            )
        elif prefix == "mcp-tool":
            values["data"] = data if isinstance(data, McpToolData) else McpToolData(**data)
        else:
            raise ValueError(f"Unknown tool prefix: {prefix}")

        return values

    model_config = ConfigDict(from_attributes=True)


class CodeResultData(BaseModel):
    execution_id: str
    result_data: str | None = None
    stderr: str
    stdout: str
    returncode: int = 0

    model_config = ConfigDict(from_attributes=True)


class CodeTaskData(StorageScopedData):
    # The venv this code runs in; None means the sandbox's default venv.
    venv_id: int | None = None
    code: str
    execution_id: str
    entrypoint: str
    func_kwargs: dict | None = None
    global_kwargs: dict[str, Any] | None = None
    execution_timeout: float | None = Field(default=None, gt=0)
    """Requested execution timeout in seconds. Untrusted: the sandbox caps it at
    SANDBOX_MAX_EXECUTION_TIMEOUT. None makes the sandbox apply
    SANDBOX_DEFAULT_EXECUTION_TIMEOUT."""

    storage_credentials: StorageCredentials | None = None
    """Ephemeral temporary storage credentials for sandbox execution.

    Injected by crew/django at task publication time if use_storage=True.
    Never persisted — payload-only field, set only on the copy published to
    Redis and never part of any stored state.
    """

    secrets: dict[str, str] = {}
    """{name: plaintext} for the sandbox. NOT excluded: this message is never
    persisted, and excluding it would silently deliver no secrets."""

    reply_to_crew_channel: bool = False
    """Publish the result to `crew_code_result_channel(CODE_RESULT_CHANNEL)`
    instead of the shared `CODE_RESULT_CHANNEL`. Only crew sets it; every other
    caller keeps listening on the shared channel."""

    @model_validator(mode="after")
    def _validate_storage_scope(self) -> "CodeTaskData":
        """Second echelon of defense (fail-closed):
        a task that asks for storage access must already carry:
        1. The trusted scope a publisher is responsible for filling in (org_id, storage_org_prefix)
        2. The temporary credentials (storage_credentials) injected by crew/agent at publication time

        Without both, sandbox cannot execute the task safely.
        """
        if self.use_storage:
            if not self.org_id or not self.storage_org_prefix:
                raise ValueError(
                    "use_storage=True requires both org_id and storage_org_prefix "
                    "to be set on CodeTaskData."
                )
            if self.storage_credentials is None:
                raise ValueError(
                    "use_storage=True requires storage_credentials to be set on CodeTaskData."
                )
        return self

    def log_summary(self) -> str:
        """A log-safe description of this task.

        `secrets` holds resolved plaintext, so neither its values nor its keys
        are rendered — only its size, which is what actually helps when
        debugging ("did the node receive its declarations?"). Callers must log
        this instead of the message body. `storage_credentials.secret_key` is
        also never rendered.
        """
        creds_summary = "present" if self.storage_credentials else "none"
        return (
            f"execution_id={self.execution_id} venv_id={self.venv_id} "
            f"entrypoint={self.entrypoint} "
            f"execution_timeout={self.execution_timeout} "
            f"secrets={len(self.secrets)} storage_credentials={creds_summary}"
        )

    model_config = ConfigDict(from_attributes=True)
