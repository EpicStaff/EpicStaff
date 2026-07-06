from src.shared.models import (
    PythonCodeToolData,
)
from domain.ports.i_python_code_executor_service import IPythonCodeExecutorService
from domain.models.realtime_tool import RealtimeTool, ToolParameters
from .base_tool_executor import BaseToolExecutor


class PythonCodeToolExecutor(BaseToolExecutor):
    def __init__(
        self,
        python_code_tool_data: PythonCodeToolData,
        python_code_executor_service: IPythonCodeExecutorService,
    ):
        name = python_code_tool_data.name.replace(" ", "_")
        super().__init__(tool_name=name)
        self.python_code_tool_data = python_code_tool_data
        self.python_code_executor_service = python_code_executor_service
        self._realtime_model = self._gen_python_realtime_tool_model(
            self.python_code_tool_data
        )

    async def execute(self, **kwargs):
        return await self.python_code_executor_service.run_code(
            python_code_data=self.python_code_tool_data.python_code, inputs=kwargs
        )

    def _gen_python_realtime_tool_model(
        self, python_code_tool_data: PythonCodeToolData
    ) -> RealtimeTool:
        properties = {}
        required = []
        for var in python_code_tool_data.variables:
            input_type = var.get("input_type")
            if input_type in ("agent_input", "mixed"):
                prop = {"type": var.get("type", "string"), "description": var.get("description", "")}
                if var.get("properties"):
                    prop["properties"] = var["properties"]
                if var.get("items"):
                    prop["items"] = var["items"]
                properties[var["name"]] = prop
                if var.get("required") and input_type == "agent_input":
                    required.append(var["name"])
        tool_parameters = ToolParameters(
            properties=properties,
            required=required,
        )
        return RealtimeTool(
            name=self.tool_name,
            description=python_code_tool_data.description,
            parameters=tool_parameters,
        )

    async def get_realtime_tool_model(self) -> RealtimeTool:
        return self._realtime_model
