from domain.models.chat_mode import ChatMode
from domain.models.realtime_tool import RealtimeTool, ToolParameters
from domain.ports.i_chat_mode_controller import IChatModeController

from .base_tool_executor import BaseToolExecutor


class StopAgentToolExecutor(BaseToolExecutor):
    def __init__(
        self,
        stop_prompt: str,
        chat_mode_controller: IChatModeController,
    ):
        super().__init__(tool_name="stop_agent_tool")
        self.stop_prompt = stop_prompt
        self.chat_mode_controller = chat_mode_controller
        self._realtime_model = self._gen_knowledge_realtime_tool_model()

    async def execute(self, **kwargs) -> list[str]:
        self.chat_mode_controller.set_chat_mode(ChatMode.LISTEN)

    def _gen_knowledge_realtime_tool_model(self) -> RealtimeTool:
        tool_parameters = ToolParameters(
            properties={},
            required=[],
        )
        tool = RealtimeTool(
            name=self.tool_name,
            parameters=tool_parameters,
        )
        tool.description = self.stop_prompt
        return tool

    async def get_realtime_tool_model(self) -> RealtimeTool:
        return self._realtime_model
