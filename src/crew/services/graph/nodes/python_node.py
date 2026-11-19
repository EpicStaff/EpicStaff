import json
from typing import Any

from langgraph.types import StreamWriter
from models.graph_models import GraphMessage, PythonMessageData
from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import ReturnCodeError
from services.graph.nodes.base_node import BaseNode
from services.run_python_code_service import (
    RunPythonCodeService,
    build_state_globals,
    code_failure_text,
    streamed_execution_data,
)
from src.shared.models import PythonCodeData
from src.shared.models.storage_scope import StorageCredentials


class PythonNode(BaseNode):
    TYPE = "PYTHON"
    LABEL = "Python node"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        input_map: dict,
        output_variable_path: str,
        python_code_executor_service: RunPythonCodeService,
        python_code_data: PythonCodeData,
        storage_credentials: StorageCredentials | None = None,
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
        self.code_reads_state = "state" in python_code_data.code
        self.storage_credentials = storage_credentials

    async def execute(self, state: State, writer: StreamWriter, execution_order: int, input_: Any):
        self.custom_session_message_writer.add_custom_message(
            session_id=self.session_id,
            node_name=self.node_name,
            writer=writer,
            execution_order=execution_order,
            message_data={
                "message_type": "python_stream",
                "text": f"Executing '{self.node_name}'...",
                "is_final": False,
            },
        )

        additional_global_kwargs = build_state_globals(state) if self.code_reads_state else {}
        python_code_execution_data = await self.python_code_executor_service.run_code(
            self.python_code_data,
            input_,
            additional_global_kwargs=additional_global_kwargs,
            stop_event=self.stop_event,
            storage_credentials=self.storage_credentials,
        )

        return self.read_execution_data(python_code_execution_data, writer, execution_order)

    def read_execution_data(
        self, python_code_execution_data: dict, writer: StreamWriter, execution_order: int
    ) -> Any:
        """Stream the sandbox's execution data and return the code's result.

        Raises:
            ReturnCodeError: The code exited non-zero, or the sandbox couldn't run it;
                carries the code's stderr or the sandbox's error detail.
        """
        self.write_python_message(python_code_execution_data, writer, execution_order)

        if python_code_execution_data["returncode"] != 0:
            raise ReturnCodeError(code_failure_text(python_code_execution_data))

        return json.loads(python_code_execution_data["result_data"])

    def write_python_message(
        self, python_code_execution_data: dict, writer: StreamWriter, execution_order: int
    ):
        python_message_data = PythonMessageData(
            python_code_execution_data=streamed_execution_data(python_code_execution_data),
        )
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=execution_order,
            message_data=python_message_data,
        )
        writer(graph_message)
