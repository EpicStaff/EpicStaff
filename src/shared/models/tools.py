from pydantic import BaseModel
from typing import Any, Optional
from pydantic import ConfigDict, Field, model_validator
from .ai_providers import LLMData, EmbedderData


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

    timeout: Optional[float] = 30
    """Request timeout in seconds. Recommended to set."""

    auth: Optional[str] = None
    """Authorization token or OAuth string, if the server requires it."""

    auth_secret_id: Optional[int] = Field(default=None, exclude=True)
    """In-memory carrier for SecretResolver; excluded from every dump."""

    init_timeout: Optional[float] = 10
    """Timeout for session initialization. Optional, default is 10 seconds."""

    model_config = ConfigDict(
        from_attributes=True,
        extra="ignore",
    )


class PythonCodeData(BaseModel):
    venv_name: str
    code: str
    entrypoint: str
    libraries: list[str]
    global_kwargs: dict[str, Any] | None = None
    use_storage: bool = False
    storage_allowed_paths: list[str] | None = None
    storage_org_prefix: str | None = None
    session_id: int | None = None

    secret_names: list[str] = Field(default_factory=list, exclude=True)
    """Names this node's code asks for, extracted by scan_secret_names().

    The declaration comes from the code itself, not from the client — there is no
    request field for it, which is why every Python context behaves identically.

    Excluded because this model is nested in GraphData, which becomes
    Session.graph_schema. The names are not credentials, but they are the
    caller's data and nothing downstream of Redis needs them.
    """

    secrets: dict[str, str] = Field(default_factory=dict)
    """{name: plaintext}, filled on the resolved copy only.

    NOT excluded: this is how the resolved value reaches crew — redis_service
    publishes `resolved.model_dump_json()`, and if this field were excluded
    that dump could never carry it, no matter how it was filled.

    This is safe because resolution happens only on the deep copy that
    SecretResolver.resolve_payload() returns, never on the caller's object.
    `Session.graph_schema` is built from that original, unresolved object
    (see session_manager_service.py), so its `secrets` is always the empty
    default here — never plaintext. Nothing prevents future code from
    resolving in place instead of on a copy; that discipline, not a Field
    flag, is what keeps this field's value out of persisted storage.
    """

    model_config = ConfigDict(from_attributes=True)


class PythonCodeToolData(BaseModel):
    id: int
    name: str
    description: str
    variables: list[dict] = []
    python_code: PythonCodeData

    model_config = ConfigDict(from_attributes=True)


class BaseToolData(BaseModel):
    unique_name: str
    data: PythonCodeToolData | ConfiguredToolData | McpToolData

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
        except ValueError:
            raise ValueError(
                "Invalid unique_name. Unique name should be splited by `:`. \nFor example: python-code-tool:1"
            )
        if prefix in {
            "python-code-tool",
            "python-code-tool-config",
        }:
            values["data"] = (
                data
                if isinstance(data, PythonCodeToolData)
                else PythonCodeToolData(**data)
            )
        elif prefix == "configured-tool":
            values["data"] = (
                data
                if isinstance(data, ConfiguredToolData)
                else ConfiguredToolData(**data)
            )
        elif prefix == "mcp-tool":
            values["data"] = (
                data if isinstance(data, McpToolData) else McpToolData(**data)
            )
        else:
            raise ValueError(f"Unknown tool prefix: {prefix}")

        return values

    model_config = ConfigDict(from_attributes=True)


class RunToolParamsModel(BaseModel):
    tool_config: ToolConfigData | None = None
    run_args: list[str]
    run_kwargs: dict[str, Any]


class ToolInitConfigurationModel(BaseModel):
    tool_init_configuration: dict[str, Any] | None = None

    model_config = ConfigDict(from_attributes=True)


class CodeResultData(BaseModel):
    execution_id: str
    result_data: str | None = None
    stderr: str
    stdout: str
    returncode: int = 0

    model_config = ConfigDict(from_attributes=True)


class CodeTaskData(BaseModel):
    venv_name: str
    libraries: list[str]
    code: str
    execution_id: str
    entrypoint: str
    func_kwargs: dict | None = None
    global_kwargs: dict[str, Any] | None = None
    use_storage: bool = False
    storage_allowed_paths: list[str] | None = None
    storage_org_prefix: str | None = None
    session_id: int | None = None

    secrets: dict[str, str] = {}
    """{name: plaintext} for the sandbox. NOT excluded: this message is never
    persisted, and excluding it would silently deliver no secrets."""

    def log_summary(self) -> str:
        """A log-safe description of this task.

        `secrets` holds resolved plaintext, so neither its values nor its keys
        are rendered — only its size, which is what actually helps when
        debugging ("did the node receive its declarations?"). Callers must log
        this instead of the message body.
        """
        return (
            f"execution_id={self.execution_id} venv={self.venv_name} "
            f"entrypoint={self.entrypoint} libraries={len(self.libraries)} "
            f"secrets={len(self.secrets)}"
        )

    model_config = ConfigDict(from_attributes=True)
