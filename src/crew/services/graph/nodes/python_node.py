import json
from typing import Any

from langgraph.types import StreamWriter
from models.graph_models import GraphMessage, PythonMessageData
from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import (
    CodeExecutionUnavailableError,
    NodeFileError,
    OutputPathError,
    PublicNodeError,
)
from services.graph.nodes.base_node import BaseNode
from services.graph.nodes.code_result_errors import code_failure_error
from services.run_python_code_service import (
    CORRELATION_ID_KEY,
    RunPythonCodeService,
    build_state_globals,
)
from src.shared.models import PythonCodeData
from src.shared.models.storage_scope import StorageCredentials


class PythonNode(BaseNode):
    TYPE = "PYTHON"
    # How messages name the node's kind, as the canvas does.
    KIND_NAME = "Python"

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
                "text": f"Executing '{self.node_label}'...",
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

        error = self._result_error(python_code_execution_data)
        python_message_data = PythonMessageData(
            python_code_execution_data=self._shown_result(python_code_execution_data, error),
        )
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=execution_order,
            message_data=python_message_data,
        )
        writer(graph_message)

        if error is not None:
            raise error
        return json.loads(python_code_execution_data["result_data"])

    def store_output(self, state: State, output: Any) -> None:
        # The path is only walked here: a missing list item, or a path through a value
        # that isn't an object or a list, fails while storing.
        try:
            super().store_output(state=state, output=output)
        except (IndexError, KeyError, TypeError, AttributeError, ValueError) as error:
            raise OutputPathError(
                f'Output path "{self.output_variable_path}" of {self.KIND_NAME} node '
                f'"{self.node_label}" doesn\'t exist. Check the output variable path.'
            ) from error

    def _result_error(self, result: dict[str, Any]) -> PublicNodeError | None:
        """Return the error the node fails with for this `run_code` result, or None if it ran."""
        correlation_id = result.get(CORRELATION_ID_KEY)
        if correlation_id is not None:
            return CodeExecutionUnavailableError(
                f'{self.KIND_NAME} node "{self.node_label}" couldn\'t run its code. '
                f"Try again or contact your administrator (reference: {correlation_id}).",
                correlation_id=correlation_id,
            )
        if result["returncode"] != 0:
            return code_failure_error(result, entrypoint=self.python_code_data.entrypoint)
        return None

    @staticmethod
    def _shown_result(result: dict[str, Any], error: PublicNodeError | None) -> dict[str, Any]:
        """Return the result as the run's Python message shows it.

        The stderr of a file the node couldn't use is crew's generated report, raw error
        text included, so the message shows the node's error in its place.
        """
        if isinstance(error, NodeFileError):
            return {**result, "stderr": str(error)}
        return result
