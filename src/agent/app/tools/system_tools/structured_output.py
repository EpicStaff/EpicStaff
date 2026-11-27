from __future__ import annotations

from app.output.schema import as_object_schema
from app.tools.registry import ToolSpec
from shared.models.agent_service import ToolResult

ANSWER_TOOL = "submit_final_answer"


class AnswerCapture:
    def __init__(self, field_names: set[str]) -> None:
        self.args: dict | None = None
        self.fields_called_as_tools: list[str] = []
        self._field_names = field_names

    async def __call__(self, args: dict) -> ToolResult:
        self.args = args
        return ToolResult(tool_call_id="", content="received")

    async def reject_field_called_as_tool(self, name: str, args: dict) -> ToolResult:
        """Explain that ``name`` is a field of the answer, not a tool.

        Raises:
            KeyError: ``name`` is not a top-level field of the answer schema.
        """
        if name not in self._field_names:
            raise KeyError(name)

        if name not in self.fields_called_as_tools:
            self.fields_called_as_tools.append(name)

        return ToolResult(
            tool_call_id="",
            content=(
                f"'{name}' is not a tool: it is a field of the {ANSWER_TOOL} arguments. "
                f"Call {ANSWER_TOOL} once, with all fields in its arguments."
            ),
            is_error=True,
        )


def build_answer_tool(output_schema: dict) -> tuple[ToolSpec, AnswerCapture, bool]:
    obj_schema, wrapped = as_object_schema(output_schema)
    spec = ToolSpec(
        name=ANSWER_TOOL,
        description="Return the final answer; arguments MUST match the required schema.",
        parameters_schema=obj_schema,
    )
    return spec, AnswerCapture(set(obj_schema.get("properties", {}))), wrapped
