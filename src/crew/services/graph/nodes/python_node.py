import json
from services.run_python_code_service import RunPythonCodeService
from services.graph.exceptions import ReturnCodeError
from models.request_models import PythonCodeData
from .base_node import *
from models.state import *


class PythonNode(BaseNode):
    TYPE = "PYTHON"

    def __init__(
        self,
        session_id: int,
        node_name: str,
        input_map: dict,
        output_variable_path: str,
        python_code_executor_service: RunPythonCodeService,
        python_code_data: PythonCodeData,
    ):
        super().__init__(
            session_id=session_id,
            node_name=node_name,
            input_map=input_map,
            output_variable_path=output_variable_path,
        )
        self.python_code_executor_service = python_code_executor_service
        self.python_code_data = python_code_data

    async def execute(
        self, state: State, writer: StreamWriter, execution_order: int, input_: Any
    ):
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
