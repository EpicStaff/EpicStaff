import json
from typing import Any

from langgraph.types import StreamWriter

from src.crew.models.graph_models import PythonMessageData, GraphMessage
from src.crew.models.state import State
from src.crew.services.graph.events import StopEvent
from src.crew.services.graph.nodes import BaseNode
from src.crew.services.run_python_code_service import RunPythonCodeService
from src.crew.services.graph.exceptions import ReturnCodeError
from src.shared.models import PythonCodeData


class PythonNode(BaseNode):
    TYPE = "PYTHON"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        input_map: dict,
        output_variable_path: str,
        python_code_executor_service: RunPythonCodeService,
        python_code_data: PythonCodeData,
        stream_config: dict | None = None,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map=input_map,
            output_variable_path=output_variable_path,
        )
        self.python_code_executor_service = python_code_executor_service
        self.python_code_data = python_code_data
        self.stream_config = stream_config or {}

    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ):
        self.custom_session_message_writer.add_custom_message(
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            execution_order=execution_order,
            message_data={
                "message_type": "python_stream",
                "text": f"Executing '{self.node_name}'...",
                "is_final": False,
                "sse_visible": not self.stream_config
                or self.stream_config.get("execution_status", True),
            },
        )

        additional_global_kwargs = {
            "state": {
                "variables": state["variables"].model_dump(),
                "state_history": state["state_history"],
            }
        }
        python_code_execution_data = await self.python_code_executor_service.run_code(
            self.python_code_data,
            input_,
            additional_global_kwargs=additional_global_kwargs,
            stop_event=self.stop_event,
        )

        python_message_data = PythonMessageData(
            python_code_execution_data=python_code_execution_data,
        )
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=execution_order,
            message_data=python_message_data,
        )
        writer(graph_message)

        if python_code_execution_data["returncode"] != 0:
            raise ReturnCodeError(python_code_execution_data["stderr"])

        return json.loads(python_code_execution_data["result_data"])
