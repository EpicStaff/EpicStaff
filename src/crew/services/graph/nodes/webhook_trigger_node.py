import json
from typing import Any

from langgraph.types import StreamWriter
from models.graph_models import GraphMessage, PythonMessageData
from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import CodeExecutionUnavailableError
from services.graph.nodes.base_node import BaseNode
from services.graph.nodes.code_result_errors import code_failure_error
from services.run_python_code_service import (
    CORRELATION_ID_KEY,
    RunPythonCodeService,
    build_state_globals,
)
from src.shared.models import PythonCodeData
from src.shared.models.storage_scope import StorageCredentials


class WebhookTriggerNode(BaseNode):
    TYPE = "WEBHOOK_TRIGGER"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        stop_event: StopEvent,
        python_code_executor_service: RunPythonCodeService,
        python_code_data: PythonCodeData,
        storage_credentials: StorageCredentials | None = None,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            stop_event=stop_event,
            input_map="__all__",
            output_variable_path="variables",
        )
        self.python_code_executor_service = python_code_executor_service
        self.python_code_data = python_code_data
        self.code_reads_state = "state" in python_code_data.code
        self.storage_credentials = storage_credentials

    async def execute(self, state: State, writer: StreamWriter, execution_order: int, input_: Any):
        additional_global_kwargs = build_state_globals(state) if self.code_reads_state else {}
        python_code_execution_data = await self.python_code_executor_service.run_code(
            python_code_data=self.python_code_data,
            inputs=input_,
            additional_global_kwargs=additional_global_kwargs,
            stop_event=self.stop_event,
            storage_credentials=self.storage_credentials,
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

        correlation_id = python_code_execution_data.get(CORRELATION_ID_KEY)
        if correlation_id is not None:
            raise CodeExecutionUnavailableError(
                f'Webhook Trigger node "{self.node_label}" couldn\'t run its code. '
                f"Try again or contact your administrator (reference: {correlation_id}).",
                correlation_id=correlation_id,
            )
        if python_code_execution_data["returncode"] != 0:
            # Its inputs are the whole flow state, not an input map the user can fix.
            raise code_failure_error(python_code_execution_data)

        return json.loads(python_code_execution_data["result_data"])
