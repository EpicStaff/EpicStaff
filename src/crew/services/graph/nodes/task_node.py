from typing import Any

from langgraph.types import StreamWriter
from loguru import logger

from models.state import State
from services.agent_task_service import AgentTaskService
from services.graph.events import StopEvent
from services.graph.nodes import BaseNode
from src.shared.models import TaskNodeData


class _SafeFormatDict(dict):
    def __missing__(self, key):
        logger.warning(
            f"Task node instructions: no input value for placeholder {{{key}}}; left as-is"
        )
        return "{" + key + "}"


class TaskNode(BaseNode):
    TYPE = "TASK"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        task_node_data: TaskNodeData,
        agent_task_service: AgentTaskService,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=task_node_data.input_map or None,
            output_variable_path=None,
        )
        self.task_node_data = task_node_data
        self.agent_task_service = agent_task_service

    def _render_instructions(self, instructions: str, input_: dict) -> str:
        try:
            return instructions.format_map(_SafeFormatDict(input_))
        except (ValueError, IndexError):
            # malformed/positional braces — send verbatim
            return instructions

    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ):
        agent_definition = self.task_node_data.agent_definition
        if agent_definition is None:
            raise ValueError(
                f"TaskNode '{self.node_name}' requires an agent_definition"
            )
        if agent_definition.llm is None:
            raise ValueError(
                f"TaskNode '{self.node_name}' requires agent_definition.llm"
            )

        rendered_instructions = self._render_instructions(
            self.task_node_data.instructions, input_
        )
        task_node_data = self.task_node_data.model_copy(
            update={"instructions": rendered_instructions}
        )

        step_id = 0

        def _on_agent_event(envelope):
            nonlocal step_id
            step_id += 1
            self.custom_session_message_writer.add_custom_message(
                session_id=self.session_id,
                node_name=self.node_name,
                writer=writer,
                execution_order=execution_order,
                message_data={
                    "message_type": "task_node_stream",
                    "event": "tool_call"
                    if envelope.type == "agent.tool_call"
                    else "tool_result",
                    "step_id": step_id,
                    "is_final": False,
                    "sse_visible": True,
                    "data": envelope.payload,
                },
            )

        result = await self.agent_task_service.run_task(
            task_node_data, self.stop_event, on_event=_on_agent_event
        )

        # TODO(remember_output): when task_node_data.remember_output is True,
        # store the final result in a per-agent Redis key so later tasks in
        # the flow can consume it as additional context.

        return {
            "message": result.get("final_text"),
            "token_usage": result.get("token_usage") or {},
            "stop_reason": result.get("stop_reason"),
            "iterations": result.get("iterations"),
            "tool_invocations": result.get("tool_invocations"),
        }
