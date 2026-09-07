import audioop
import base64
import json
import uuid
from typing import Optional, List, Dict, Any, Callable, Awaitable

import websockets
from loguru import logger
from starlette.websockets import WebSocketDisconnect

from domain.models.realtime_tool import RealtimeTool
from infrastructure.providers.base_realtime_agent_client import BaseRealtimeAgentClient
from infrastructure.providers.elevenlabs.elevenlabs_agent_provisioner import (
    ElevenLabsAgentProvisioner,
)
from infrastructure.providers.elevenlabs.event_handlers.elevenlabs_server_event_handler import (
    ElevenLabsServerEventHandler,
)
from infrastructure.providers.elevenlabs.event_handlers.elevenlabs_client_event_handler import (
    ElevenLabsClientEventHandler,
)
from application.tool_manager_service import ToolManagerService


class ElevenLabsRealtimeAgentClient(BaseRealtimeAgentClient):
    """
    ElevenLabs ConvAI adapter.  Implements IRealtimeAgentClient via BaseRealtimeAgentClient.

    Audio paths:
    - Browser input: frontend sends 24kHz PCM via process_message() →
      ElevenLabsClientEventHandler resamples 24k→16k → user_audio_chunk
    - Twilio input: VoiceCallService calls send_audio(ulaw8k_b64) →
      _ulaw_to_pcm16k() converts µ-law 8kHz → PCM 16kHz → user_audio_chunk
    - Browser output: ElevenLabsServerEventHandler._handle_audio() upsamples PCM 16k → 24k
    - Twilio output: ElevenLabsServerEventHandler._handle_audio() converts PCM 16k → µ-law 8k
    """

    def __init__(
        self,
        api_key: str,
        connection_key: str,
        on_server_event: Optional[Callable[[dict], Awaitable[None]]] = None,
        tool_manager_service: ToolManagerService = None,
        rt_tools: Optional[List[RealtimeTool]] = None,
        voice: str = "21m00Tcm4TlvDq8ikWAM",  # Rachel
        instructions: str = "You are a helpful assistant",
        temperature: float = 0.8,
        agent_id: str = "",
        agent_provisioner: ElevenLabsAgentProvisioner | None = None,
        llm_model: str = "",
        language: Optional[str] = None,
        org_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ):
        super().__init__(
            api_key=api_key,
            connection_key=connection_key,
            on_server_event=on_server_event,
            org_id=org_id,
            user_id=user_id,
        )

        self.tool_manager_service = tool_manager_service
        self.rt_tools = rt_tools or []
        self.voice = voice
        self.instructions = instructions
        self.temperature = temperature
        self.agent_id = agent_id
        self.agent_provisioner = agent_provisioner
        self.language = language
        self.llm_model = llm_model

        self.base_url = "wss://api.elevenlabs.io/v1/convai/conversation"

        # Stateful resampling for audio format conversion
        self._up_resample_state = None  # ulaw 8kHz → PCM 16kHz (Twilio input)
        self._down_resample_state = (
            None  # PCM 16kHz → ulaw 8kHz (Twilio output, used by server event handler)
        )

        self.server_event_handler = ElevenLabsServerEventHandler(self)
        self.client_event_handler = ElevenLabsClientEventHandler(self)

        self.tools = []
        for rt_tool in self.rt_tools:
            if not isinstance(rt_tool, dict):
                rt_tool = rt_tool.model_dump()
            self.tools.append(rt_tool)

    async def connect(self) -> None:
        if not self.agent_id:
            logger.info("ElevenLabs: Provisioning agent...")
            self.agent_id = await self.agent_provisioner.get_or_create_agent(
                api_key=self.api_key,
                instructions=self.instructions,
                voice=self.voice,
                rt_tools=self.rt_tools,
                llm_model=self.llm_model,
                language=self.language,
            )

        await self._do_connect(allow_reprovision=True)

    async def _do_connect(self, *, allow_reprovision: bool = False) -> None:
        """Open the WebSocket to ElevenLabs.

        If the handshake fails (e.g. HTTP 404 because the agent was deleted on
        ElevenLabs' side without sending close code 3000), and ``allow_reprovision``
        is True, the cache is invalidated, a fresh agent is provisioned, and the
        connection is retried once.
        """
        url = f"{self.base_url}?agent_id={self.agent_id}"
        headers = {"xi-api-key": self.api_key}

        try:
            self.ws = await websockets.connect(url, extra_headers=headers)
        except websockets.exceptions.InvalidHandshake as exc:
            if allow_reprovision and self.agent_provisioner:
                logger.warning(
                    f"ElevenLabs: WS handshake failed ({exc}) — stale agent_id={self.agent_id}. "
                    "Invalidating cache and re-provisioning..."
                )
                await self.agent_provisioner.invalidate_cache(
                    api_key=self.api_key,
                    instructions=self.instructions,
                    voice=self.voice,
                    rt_tools=self.rt_tools,
                    llm_model=self.llm_model,
                    language=self.language,
                )
                self.agent_id = await self.agent_provisioner.get_or_create_agent(
                    api_key=self.api_key,
                    instructions=self.instructions,
                    voice=self.voice,
                    rt_tools=self.rt_tools,
                    llm_model=self.llm_model,
                    language=self.language,
                )
                await self._do_connect(allow_reprovision=False)
                return
            raise

        logger.info(f"ElevenLabs WebSocket connected: agent_id={self.agent_id} | voice_id={self.voice!r} | language={self.language!r}")

        config_override = {}
        if self.language:
            config_override["agent"] = {"language": self.language}

        await self.send_server(
            {
                "type": "conversation_initiation_client_data",
                "conversation_config_override": config_override,
            }
        )

    async def on_stream_start(self) -> None:
        """ElevenLabs starts automatically — no action needed on Twilio stream start."""
        pass

    async def send_audio(self, ulaw8k_b64: str) -> None:
        """
        Accept base64-encoded µ-law 8kHz audio from Twilio and forward to ElevenLabs
        as PCM 16kHz (the format ElevenLabs expects).
        """
        ulaw_bytes = base64.b64decode(ulaw8k_b64)
        pcm16k = self._ulaw_to_pcm16k(ulaw_bytes)
        resampled_b64 = base64.b64encode(pcm16k).decode()
        await self.send_server({"user_audio_chunk": resampled_b64})

    def _ulaw_to_pcm16k(self, ulaw_bytes: bytes) -> bytes:
        """Convert µ-law 8kHz to PCM 16kHz with stateful resampling."""
        pcm_8k = audioop.ulaw2lin(ulaw_bytes, 2)
        pcm_16k, self._up_resample_state = audioop.ratecv(
            pcm_8k, 2, 1, 8000, 16000, self._up_resample_state
        )
        return pcm_16k

    async def handle_messages(self) -> None:
        """ElevenLabs message loop with automatic cache-invalidation retry on code 3000."""
        _retried = False
        try:
            while True:
                logger.info("ElevenLabs: Message handler started.")
                try:
                    async for message in self.ws:
                        try:
                            data = json.loads(message)

                            if data.get("type") == "ping":
                                event_id = data.get("ping_event", {}).get("event_id")
                                await self.send_server(
                                    {"type": "pong", "event_id": event_id}
                                )
                                continue

                            await self.server_event_handler.handle_event(data)

                        except WebSocketDisconnect:
                            logger.info(
                                "ElevenLabs: Client disconnected, stopping message handler"
                            )
                            return
                        except Exception as e:
                            logger.exception(
                                f"ElevenLabs: Error processing message: {str(e)}"
                            )
                except websockets.exceptions.ConnectionClosed as e:
                    code = e.rcvd.code if e.rcvd else None
                    if code == 3000 and not _retried and self.agent_provisioner:
                        logger.warning(
                            "ElevenLabs: Agent not found (3000) — invalidating cache and re-provisioning..."
                        )
                        await self.agent_provisioner.invalidate_cache(
                            api_key=self.api_key,
                            instructions=self.instructions,
                            voice=self.voice,
                            rt_tools=self.rt_tools,
                            llm_model=self.llm_model,
                            language=self.language,
                        )
                        self.agent_id = ""
                        _retried = True
                        await self.connect()
                        continue
                    logger.info("ElevenLabs: Connection closed")
                break
        finally:
            await self.close()

    async def process_message(
        self, message: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Process messages from the frontend WebSocket."""
        return await self.client_event_handler.handle_event(data=message)

    async def send_conversation_item_to_server(self, text: str) -> None:
        """Send a user text message to ElevenLabs."""
        await self.send_server({"type": "user_message", "text": text})

    async def send_function_result(self, call_id: str, result: Any) -> None:
        """Send tool execution result back to ElevenLabs and the frontend."""
        clean_result = ""
        if isinstance(result, dict):
            clean_result = (
                result.get("result_data") or result.get("stdout") or str(result)
            )
        else:
            clean_result = str(result)

        clean_result = clean_result.strip('"').replace("\\n", "\n")

        await self.send_server(
            {
                "type": "client_tool_result",
                "tool_call_id": call_id,
                "result": clean_result,
                "is_error": False,
            }
        )

        await self.send_client(
            {
                "type": "conversation.item.created",
                "item": {
                    "id": f"res_{uuid.uuid4().hex[:10]}",
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": clean_result,
                },
            }
        )

        await self.send_client(
            {"type": "response.done", "response": {"status": "completed"}}
        )

    async def call_tool(
        self, call_id: str, tool_name: str, tool_arguments: Dict[str, Any]
    ) -> None:
        """Execute a tool via ToolManagerService."""
        logger.info(f"ElevenLabs: Calling tool {tool_name}")
        try:
            tool_result = await self.tool_manager_service.execute(
                connection_key=self.connection_key,
                tool_name=tool_name,
                call_arguments=tool_arguments,
            )
            await self.send_function_result(call_id, tool_result)
        except Exception as e:
            logger.error(f"Tool execution failed: {str(e)}")
            await self.send_function_result(call_id, f"Error: {str(e)}")

    async def request_response(self, data: dict | None = None) -> None:
        """ElevenLabs operates in auto-response mode — no-op."""
        pass
