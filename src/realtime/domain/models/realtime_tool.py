from typing import Any, Literal
from pydantic import BaseModel


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
