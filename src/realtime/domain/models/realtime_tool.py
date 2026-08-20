from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class ToolClassDataArgsSchema(BaseModel):
    """JSON Schema from the container's `.schema()` call; extra keys are ignored on purpose."""

    model_config = ConfigDict(extra="ignore")

    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)


class ToolClassData(BaseModel):
    """Payload returned by the tool container's `/tool/{alias}/class-data/` endpoint."""

    model_config = ConfigDict(extra="ignore")

    description: str
    args_schema: ToolClassDataArgsSchema = Field(default_factory=ToolClassDataArgsSchema)


class ToolParameters(BaseModel):
    properties: dict[str, Any]
    required: list[str] = []
    type: Literal["object"] = "object"


class RealtimeTool(BaseModel):
    name: str
    _description: str = ""
    parameters: ToolParameters
    type: Literal["function"] = "function"

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value: str) -> None:
        if len(value) > 1024:
            shortened_description = value[:1021].strip() + "..."
            self._description = shortened_description
        else:
            self._description = value
