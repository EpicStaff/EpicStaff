import pytest

from domain.models.chat_mode import ChatMode
from tool_executors.stop_agent_tool_executor import StopAgentToolExecutor


class RecordingModeController:
    def __init__(self):
        self.modes: list[ChatMode] = []

    def set_chat_mode(self, mode: ChatMode) -> None:
        self.modes.append(mode)


@pytest.mark.asyncio
async def test_calling_the_tool_puts_the_agent_back_to_listening():
    controller = RecordingModeController()

    result = await StopAgentToolExecutor(stop_prompt="stop", chat_mode_controller=controller).execute()

    assert (controller.modes, result) == ([ChatMode.LISTEN], None)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stop_prompt", "description"),
    [("Say goodbye to stop the agent", "Say goodbye to stop the agent"), ("x" * 1025, "x" * 1021 + "...")],
    ids=["short", "over-provider-limit"],
)
async def test_tool_is_offered_with_the_stop_prompt_as_its_description(stop_prompt, description):
    executor = StopAgentToolExecutor(stop_prompt=stop_prompt, chat_mode_controller=RecordingModeController())

    tool = await executor.get_realtime_tool_model()

    assert (tool.name, tool.description) == ("stop_agent_tool", description)
    assert (tool.parameters.properties, tool.parameters.required) == ({}, [])
