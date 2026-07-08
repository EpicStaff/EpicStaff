from typing import Any

from langgraph.types import StreamWriter

from models.state import State
from services.agent_task_service import AgentTaskService
from services.graph.events import StopEvent
from services.graph.nodes import BaseNode
from services.graph.nodes.instruction_render import render_instructions
from services.graph.remembered_outputs import (
    RememberedOutputsStore,
    format_remembered_outputs_preamble,
)
from src.shared.models import TaskNodeData

STREAM_EVENT_BY_ENVELOPE_TYPE = {
    "agent.tool_call": "tool_call",
    "agent.tool_result": "tool_result",
    "agent.task_start": "task_start",
    "agent.task_finish": "task_finish",
}


class TaskNode(BaseNode):
    TYPE = "TASK"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        task_node_data: TaskNodeData,
        agent_task_service: AgentTaskService,
        remembered_outputs_store: RememberedOutputsStore,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=task_node_data.input_map or None,
            output_variable_path=task_node_data.output_variable_path,
        )
        self.task_node_data = task_node_data
        self.agent_task_service = agent_task_service
        self.remembered_outputs_store = remembered_outputs_store

    def get_output_variable_value(self, output: Any) -> Any:
        return output.get("message") if isinstance(output, dict) else output

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

        rendered_instructions = render_instructions(
            self.task_node_data.instructions, input_
        )
        remembered = await self.remembered_outputs_store.fetch_all(self.session_id)
        preamble = format_remembered_outputs_preamble(remembered)
        task_node_data = self.task_node_data.model_copy(
            update={"instructions": preamble + rendered_instructions}
        )

        step_id = 0

        def _on_agent_event(envelope):
            nonlocal step_id
            event = STREAM_EVENT_BY_ENVELOPE_TYPE.get(envelope.type)
            if event is None:
                return

            step_id += 1
            self.custom_session_message_writer.add_custom_message(
                session_id=self.session_id,
                node_name=self.node_name,
                writer=writer,
                execution_order=execution_order,
                message_data={
                    "message_type": "task_node_stream",
                    "event": event,
                    "step_id": step_id,
                    "is_final": False,
                    "sse_visible": True,
                    "data": envelope.payload,
                },
            )

        result = await self.agent_task_service.run_task(
            task_node_data, self.stop_event, on_event=_on_agent_event
        )

        final_text = result.get("final_text")
        if self.task_node_data.remember_output and final_text:
            await self.remembered_outputs_store.store(
                self.session_id, self.node_name, final_text
            )

        return {
            "message": final_text,
            "token_usage": result.get("token_usage") or {},
            "stop_reason": result.get("stop_reason"),
            "iterations": result.get("iterations"),
            "tool_invocations": result.get("tool_invocations"),
        }
