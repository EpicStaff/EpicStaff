from pydantic import BaseModel
from typing import Literal, Any, Optional
from pydantic import ConfigDict, model_validator
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
    args_schema: ArgsSchema
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

    model_config = ConfigDict(from_attributes=True)
