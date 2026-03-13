from src.shared.models import (
    PythonCodeToolData,
)
from services.python_code_executor_service import PythonCodeExecutorService
from models.ai_models import RealtimeTool, ToolParameters
from .base_tool_executor import BaseToolExecutor


class PythonCodeToolExecutor(BaseToolExecutor):
    def __init__(
        self,
        python_code_tool_data: PythonCodeToolData,
        python_code_executor_service: PythonCodeExecutorService,
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
        tool_parameters = ToolParameters(
            properties=python_code_tool_data.args_schema.properties,
            required=python_code_tool_data.args_schema.required,
        )
        return RealtimeTool(
            name=self.tool_name,
            description=python_code_tool_data.description,
            parameters=tool_parameters,
        )

    async def get_realtime_tool_model(self) -> RealtimeTool:
        return self._realtime_model
