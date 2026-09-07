from typing import Any

from langgraph.types import StreamWriter

from models.state import State
from services.agent_task_service import AgentTaskService
from services.graph.events import StopEvent
from services.graph.nodes import BaseNode
from services.graph.nodes.agent_output_variable import agent_output_variable_value
from services.graph.nodes.agent_stream_events import AgentStreamEventForwarder
from services.graph.nodes.instruction_render import render_instructions
from src.shared.models import AgentNodeData


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
        return agent_output_variable_value(output)

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

        on_agent_event = AgentStreamEventForwarder(
            custom_session_message_writer=self.custom_session_message_writer,
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            execution_order=execution_order,
            stream_message_type="agent_node_stream",
        )

        result = await self.agent_task_service.run_agent_node(
            agent_node_data, self.stop_event, on_event=on_agent_event
        )

        return {
            "message": result.get("final_text"),
            "structured_output": result.get("structured_output"),
            "token_usage": result.get("token_usage") or {},
            "stop_reason": result.get("stop_reason"),
            "iterations": result.get("iterations"),
            "tool_invocations": result.get("tool_invocations"),
            "tasks": [
                {
                    "name": task.get("name"),
                    "order": task.get("order"),
                    "message": task.get("final_text"),
                    "structured_output": task.get("structured_output"),
                    "token_usage": task.get("token_usage") or {},
                    "iterations": task.get("iterations"),
                    "tool_invocations": task.get("tool_invocations"),
                }
                for task in (result.get("tasks") or [])
            ],
        }
