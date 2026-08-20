from __future__ import annotations

from app.output.schema import as_object_schema
from app.tools.registry import ToolSpec
from shared.models.agent_service import ToolResult

ANSWER_TOOL = "submit_final_answer"


class AnswerCapture:
    def __init__(self) -> None:
        self.args: dict | None = None

    async def __call__(self, args: dict) -> ToolResult:
        self.args = args
        return ToolResult(tool_call_id="", content="received")


def build_answer_tool(output_schema: dict) -> tuple[ToolSpec, AnswerCapture, bool]:
    obj_schema, wrapped = as_object_schema(output_schema)
    spec = ToolSpec(
        name=ANSWER_TOOL,
        description="Return the final answer; arguments MUST match the required schema.",
        parameters_schema=obj_schema,
    )
    return spec, AnswerCapture(), wrapped
