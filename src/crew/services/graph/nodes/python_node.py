import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.types import StreamWriter
from models.graph_models import GraphMessage, PythonMessageData
from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import OutputPathError, PublicNodeError
from services.graph.nodes.base_node import BaseNode
from services.graph.nodes.code_result_errors import code_failure_error
from services.run_python_code_service import RunPythonCodeService, build_state_globals
from src.shared.models import CodeResultData, PythonCodeData
from src.shared.models.storage_scope import StorageCredentials


@dataclass(frozen=True)
class CodeResultReading:
    """What a code node makes of its code's result, read once per run.

    Attributes:
        error: The error the node fails with; None if the code ran.
        shown_result: The result as the run's Python message shows it.
        output: Returns the node's output. Called only when `error` is None, and after
            the message is written, so a result it can't read still shows in the message.
    """

    error: PublicNodeError | None
    shown_result: dict[str, Any]
    output: Callable[[], Any]


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

        reading = self._read_result(python_code_execution_data)
        python_message_data = PythonMessageData(
            python_code_execution_data=reading.shown_result,
            error=None if reading.error is None else str(reading.error),
        )
        graph_message = GraphMessage(
            session_id=self.session_id,
            name=self.node_name,
            execution_order=execution_order,
            message_data=python_message_data,
        )
        writer(graph_message)

        if reading.error is not None:
            raise reading.error
        return reading.output()

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

    def _read_result(self, result: CodeResultData) -> CodeResultReading:
        """Return what the node makes of this `run_code` result."""
        return CodeResultReading(
            error=code_failure_error(
                result,
                kind_name=self.KIND_NAME,
                node_label=self.node_label,
                entrypoint=self.python_code_data.entrypoint,
                session_id=self.session_id,
            ),
            shown_result=result.model_dump(),
            output=lambda: json.loads(result.result_data),
        )
