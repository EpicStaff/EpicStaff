from typing import Callable, Awaitable, List

from src.shared.models import RealtimeAgentChatData

from domain.models.realtime_tool import RealtimeTool
from domain.ports.i_realtime_agent_client import IRealtimeAgentClient
from infrastructure.providers.elevenlabs.elevenlabs_agent_provisioner import (
    ElevenLabsAgentProvisioner,
)
from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import (
    ElevenLabsRealtimeAgentClient,
)
from infrastructure.providers.openai.openai_realtime_agent_client import (
    OpenaiRealtimeAgentClient,
    TurnDetectionMode,
)
from application.tool_manager_service import ToolManagerService

_DEFAULT_LLM = "gemini-2.5-flash"


class RealtimeAgentClientFactory:
    """
    The single location where rt_provider → concrete adapter selection lives.
    Adding a new provider means adding one elif here and implementing IRealtimeAgentClient.
    """

    def __init__(self, elevenlabs_agent_provisioner: ElevenLabsAgentProvisioner):
        self._el_provisioner = elevenlabs_agent_provisioner

    def create(
        self,
        config: RealtimeAgentChatData,
        rt_tools: List[RealtimeTool],
        instructions: str,
        tool_manager_service: ToolManagerService,
        on_server_event: Callable[[dict], Awaitable[None]],
        is_twilio: bool = False,
    ) -> IRealtimeAgentClient:
        """
        Construct and return the correct provider adapter.
        Returns a fully built but NOT yet connected client — caller must await connect().
        """
        if config.rt_provider == "gemini":
            from infrastructure.providers.gemini.gemini_realtime_agent_client import (
                GeminiRealtimeAgentClient,
            )

            client = GeminiRealtimeAgentClient(
                api_key=config.rt_api_key,
                connection_key=config.connection_key,
                on_server_event=on_server_event,
                tool_manager_service=tool_manager_service,
                rt_tools=rt_tools,
                model=config.rt_model_name,
                voice=config.voice,
                instructions=instructions,
                temperature=config.temperature or 1.0,
                org_id=config.org_id,
                user_id=config.user_id,
            )
            client.is_twilio = is_twilio
            return client

        if config.rt_provider == "elevenlabs":
            llm_model = config.llm.config.model if config.llm else _DEFAULT_LLM
            client = ElevenLabsRealtimeAgentClient(
                api_key=config.rt_api_key,
                connection_key=config.connection_key,
                on_server_event=on_server_event,
                tool_manager_service=tool_manager_service,
                agent_provisioner=self._el_provisioner,
                rt_tools=rt_tools,
                voice=config.voice,
                instructions=instructions,
                temperature=config.temperature,
                llm_model=llm_model,
                language=config.language,
                org_id=config.org_id,
                user_id=config.user_id,
            )
            client.is_twilio = is_twilio
            return client

        # Default: OpenAI
        client = OpenaiRealtimeAgentClient(
            api_key=config.rt_api_key,
            connection_key=config.connection_key,
            on_server_event=on_server_event,
            tool_manager_service=tool_manager_service,
            rt_tools=rt_tools,
            model=config.rt_model_name,
            voice=config.voice,
            instructions=instructions,
            input_audio_format="g711_ulaw" if is_twilio else config.input_audio_format,
            output_audio_format="g711_ulaw"
            if is_twilio
            else config.output_audio_format,
            turn_detection_mode=TurnDetectionMode.SERVER_VAD,
            org_id=config.org_id,
            user_id=config.user_id,
        )
        client.is_twilio = is_twilio
        return client
