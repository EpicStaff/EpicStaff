from typing import Any

from langgraph.types import StreamWriter

from models.state import State
from services.agent_task_service import AgentTaskService
from services.graph.events import StopEvent
from services.graph.nodes import BaseNode
from services.graph.nodes.instruction_render import render_instructions
from src.shared.models import AgentNodeData

STREAM_EVENT_BY_ENVELOPE_TYPE = {
    "agent.tool_call": "tool_call",
    "agent.tool_result": "tool_result",
    "agent.task_start": "task_start",
    "agent.task_finish": "task_finish",
}

KNOWLEDGE_SEARCH_ENVELOPE_TYPE = "agent.knowledge_search"


class AgentNode(BaseNode):
    TYPE = "AGENT"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        agent_node_data: AgentNodeData,
        agent_task_service: AgentTaskService,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=agent_node_data.input_map or None,
            output_variable_path=agent_node_data.output_variable_path,
        )
        self.agent_node_data = agent_node_data
        self.agent_task_service = agent_task_service

    def get_output_variable_value(self, output: Any) -> Any:
        return output.get("message") if isinstance(output, dict) else output

    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ):
        agent_definition = self.agent_node_data.agent_definition
        if agent_definition is None:
            raise ValueError(
                f"AgentNode '{self.node_name}' requires an agent_definition"
            )
        if agent_definition.llm is None:
            raise ValueError(
                f"AgentNode '{self.node_name}' requires agent_definition.llm"
            )
        if not self.agent_node_data.tasks:
            raise ValueError(f"AgentNode '{self.node_name}' has no tasks to execute.")

        rendered_tasks = [
            task.model_copy(
                update={"instructions": render_instructions(task.instructions, input_)}
            )
            for task in self.agent_node_data.tasks
        ]
        agent_node_data = self.agent_node_data.model_copy(
            update={"tasks": rendered_tasks}
        )

        step_id = 0

        def _on_agent_event(envelope):
            nonlocal step_id
            if envelope.type == KNOWLEDGE_SEARCH_ENVELOPE_TYPE:
                self.custom_session_message_writer.add_custom_message(
                    session_id=self.session_id,
                    node_name=self.node_name,
                    writer=writer,
                    execution_order=execution_order,
                    message_data={
                        "message_type": "extracted_chunks",
                        "sse_visible": True,
                        **envelope.payload,
                    },
                )
                return

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
                    "message_type": "agent_node_stream",
                    "event": event,
                    "step_id": step_id,
                    "is_final": False,
                    "sse_visible": True,
                    "data": envelope.payload,
                },
            )

        result = await self.agent_task_service.run_agent_node(
            agent_node_data, self.stop_event, on_event=_on_agent_event
        )

        return {
            "message": result.get("final_text"),
            "token_usage": result.get("token_usage") or {},
            "stop_reason": result.get("stop_reason"),
            "iterations": result.get("iterations"),
            "tool_invocations": result.get("tool_invocations"),
            "tasks": [
                {
                    "name": task.get("name"),
                    "order": task.get("order"),
                    "message": task.get("final_text"),
                    "token_usage": task.get("token_usage") or {},
                    "iterations": task.get("iterations"),
                    "tool_invocations": task.get("tool_invocations"),
                }
                for task in (result.get("tasks") or [])
            ],
        }
