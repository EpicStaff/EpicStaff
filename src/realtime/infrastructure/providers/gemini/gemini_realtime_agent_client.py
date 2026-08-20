import asyncio
import audioop
import base64
from collections import deque
from typing import Any, Callable, Awaitable, Dict, List, Optional

from google import genai
from google.genai import types
from loguru import logger

from domain.models.realtime_tool import RealtimeTool
from infrastructure.providers.base_realtime_agent_client import BaseRealtimeAgentClient
from infrastructure.providers.gemini.event_handlers.gemini_client_event_handler import (
    GeminiClientEventHandler,
)
from infrastructure.providers.gemini.event_handlers.gemini_server_event_handler import (
    GeminiServerEventHandler,
)
from application.tool_manager_service import ToolManagerService


class GeminiRealtimeAgentClient(BaseRealtimeAgentClient):
    """
    Google Gemini Live API adapter.  Implements IRealtimeAgentClient via BaseRealtimeAgentClient.

    Audio paths:
    - Browser input: frontend sends 24kHz PCM via process_message() →
      GeminiClientEventHandler downsamples 24k→16k → send_realtime_input
    - Twilio input: VoiceCallService calls send_audio(ulaw8k_b64) →
      audioop converts µ-law 8kHz → PCM 16kHz → send_realtime_input
    - Browser output: Gemini outputs 24kHz PCM — passed through as-is
    - Twilio output: GeminiServerEventHandler converts PCM 24kHz → µ-law 8kHz
    """

    def __init__(
        self,
        api_key: str,
        connection_key: str,
        on_server_event: Optional[Callable[[dict], Awaitable[None]]] = None,
        tool_manager_service: ToolManagerService = None,
        rt_tools: Optional[List[RealtimeTool]] = None,
        model: str = "gemini-2.0-flash-live-001",
        voice: str = "Puck",
        instructions: str = "You are a helpful assistant",
        temperature: float = 1.0,
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

        _VALID_GEMINI_VOICES = {
            "Puck",
            "Charon",
            "Kore",
            "Fenrir",
            "Aoede",
            "Leda",
            "Orus",
            "Zephyr",
        }
        self.tool_manager_service = tool_manager_service
        self.model = model
        self.voice = voice if voice in _VALID_GEMINI_VOICES else "Puck"
        if self.voice != voice:
            logger.warning(f"Gemini: invalid voice '{voice}', falling back to 'Puck'")
        self.instructions = instructions
        self.temperature = temperature

        self._genai_client = genai.Client(api_key=api_key)
        self._session = None
        self._session_cm = None
        # Incremented on every reconnect — lets call_tool() detect session replacement
        self._session_version: int = 0
        # Prevents concurrent close() calls from racing on _session_cm.__aexit__
        self._close_lock = asyncio.Lock()

        # Stateful resampling state for Twilio paths
        self._resample_state_in = None  # µ-law 8kHz → PCM 16kHz
        self._resample_state_out = None  # PCM 24kHz → µ-law 8kHz

        # Rolling buffer: always keeps the last _ROLLING_BUFFER_SECS seconds of user audio.
        # On reconnect after session close, the buffer is replayed to the new session so
        # Gemini hears the user's speech that happened during the interruption window.
        # 16kHz 16-bit mono = 32 000 B/s → 5 s ≈ 160 KB, negligible overhead.
        _ROLLING_BUFFER_SECS = 5.0
        self._audio_rolling_buffer: deque[tuple[float, bytes]] = deque()
        self._rolling_buffer_secs: float = _ROLLING_BUFFER_SECS

        # Conversation history for context injection on reconnect.
        # Each entry: {"role": "user" | "model", "text": str}
        self._conversation_history: list[dict] = []

        self.server_event_handler = GeminiServerEventHandler(self)
        self.client_event_handler = GeminiClientEventHandler(self)

        self.tools = self._build_tools(rt_tools or [])

    def _build_tools(self, rt_tools: List[RealtimeTool]) -> list:
        """Convert RealtimeTool list to Gemini function_declarations format."""
        if not rt_tools:
            return []
        declarations = []
        for t in rt_tools:
            if isinstance(t, dict):
                name = t["name"]
                description = t.get("description", name)
                parameters = t["parameters"]
            else:
                name = t.name
                description = t.description or name
                parameters = t.model_dump()["parameters"]
            declarations.append(
                {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "OBJECT",
                        "properties": parameters["properties"],
                        "required": parameters.get("required", []),
                    },
                }
            )
        return [{"function_declarations": declarations}]

    def _build_system_instruction(self) -> str:
        """Return system instruction with conversation history appended when reconnecting."""
        if not self._conversation_history:
            return self.instructions
        history_lines = []
        for entry in self._conversation_history:
            role = "User" if entry["role"] == "user" else "Assistant"
            history_lines.append(f"{role}: {entry['text']}")
        return (
            self.instructions
            + "\n\n---\nConversation so far (continue naturally from here):\n"
            + "\n".join(history_lines)
        )

    async def connect(self) -> None:
        """Establish session with the Gemini Live API."""
        config = types.LiveConnectConfig(
            response_modalities=[types.Modality.AUDIO],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=self.voice
                    )
                )
            ),
            system_instruction=types.Content(
                parts=[types.Part(text=self._build_system_instruction())]
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
            ),
        )
        if self.tools:
            config.tools = self.tools

        logger.info(
            f"Gemini: connecting model={self.model}, voice={self.voice}, "
            f"tools={[d['name'] for t in self.tools for d in t.get('function_declarations', [])]}"
        )
        self._session_cm = self._genai_client.aio.live.connect(
            model=self.model, config=config
        )
        try:
            self._session = await self._session_cm.__aenter__()
        except Exception as e:
            reason = getattr(getattr(e, "rcvd", None), "reason", None)
            code = getattr(getattr(e, "rcvd", None), "code", None)
            logger.error(
                f"Gemini: connection failed — code={code}, reason={reason}, exc={e}"
            )
            raise
        logger.info(f"Gemini Live connected: model={self.model}, voice={self.voice}")

    async def close(self) -> None:
        """Close the Gemini Live session. Protected by a lock to prevent races."""
        async with self._close_lock:
            if self._session_cm:
                self._session = None  # stop send_audio immediately
                cm, self._session_cm = self._session_cm, None
                try:
                    await cm.__aexit__(None, None, None)
                except Exception as e:
                    logger.warning(f"Gemini: error closing session: {e}")

    async def handle_messages(self) -> None:
        """Long-running loop receiving LiveServerMessage objects from Gemini.
        Automatically reconnects when the server closes the session."""
        logger.info("Gemini: Message handler started.")
        while True:
            msg_count = 0
            try:
                async for response in self._session.receive():
                    msg_count += 1

                    signal_fields = [
                        f
                        for f in (
                            "setup_complete",
                            "tool_call",
                            "go_away",
                            "session_resumption_update",
                        )
                        if getattr(response, f, None) is not None
                    ]
                    if signal_fields:
                        logger.debug(f"Gemini msg #{msg_count}: {signal_fields}")
                    if getattr(response, "go_away", None) is not None:
                        logger.warning(
                            f"Gemini: go_away — time_left={getattr(response.go_away, 'time_left', '?')}"
                        )
                    try:
                        await self.server_event_handler.handle_event(response)
                    except Exception as e:
                        logger.exception(f"Gemini: Error processing message: {e}")
                # Server closed the connection normally — reconnect to keep the call alive
                logger.warning(
                    f"Gemini: receive() loop ended after {msg_count} messages — server closed connection, reconnecting"
                )
            except asyncio.CancelledError:
                logger.info(
                    f"Gemini: handle_messages cancelled after {msg_count} messages"
                )
                break
            except Exception as e:
                logger.exception(
                    f"Gemini: handle_messages error after {msg_count} messages: {e}"
                )
                break

            try:
                await self.close()
                self.server_event_handler.reset()
                await self.connect()
                self._session_version += 1
                logger.info("Gemini: reconnected successfully")
            except asyncio.CancelledError:
                logger.info("Gemini: reconnect cancelled")
                break
            except Exception as e:
                logger.error(f"Gemini: reconnect failed: {e}")
                break

        await self.close()

    async def send_audio(self, ulaw8k_b64: str) -> None:
        """
        Accept base64-encoded µ-law 8kHz audio from Twilio and forward to Gemini
        as PCM 16kHz (the format Gemini Live expects).
        """
        if self._session is None:
            logger.warning("Gemini: session is closed, dropping audio chunk")
            return
        ulaw_bytes = base64.b64decode(ulaw8k_b64)
        pcm_8k = audioop.ulaw2lin(ulaw_bytes, 2)
        pcm_16k, self._resample_state_in = audioop.ratecv(
            pcm_8k, 2, 1, 8000, 16000, self._resample_state_in
        )
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm_16k, mime_type="audio/pcm;rate=16000")
        )

    async def process_message(
        self, message: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Process incoming message from the frontend WebSocket."""
        return await self.client_event_handler.handle_event(data=message)

    async def send_conversation_item_to_server(self, text: str) -> None:
        """Send a user text message to Gemini (used in LISTEN wake-word mode)."""
        if self._session is None:
            logger.warning("Gemini: session is closed, dropping text message")
            return
        await self._session.send_client_content(
            turns=types.Content(
                role="user",
                parts=[types.Part(text=text)],
            ),
            turn_complete=True,
        )

    async def request_response(self, data: dict | None = None) -> None:
        """Gemini operates with automatic VAD — no explicit response trigger needed."""
        pass

    async def on_stream_start(self) -> None:
        """Twilio stream started — Gemini starts automatically, no action needed."""
        pass

    async def replay_audio_buffer(self) -> None:
        """Replay the rolling audio buffer to the new session after a reconnect.

        History context is already baked into system_instruction by connect().
        No audio_stream_end is sent — live audio continues after the buffer and
        Gemini's VAD detects end-of-speech naturally.
        """
        if not self._audio_rolling_buffer or self._session is None:
            return
        chunks = [chunk for _, chunk in self._audio_rolling_buffer]
        logger.info(
            f"Gemini: replaying {len(chunks)} buffered audio chunks to new session"
        )
        for chunk in chunks:
            await self._session.send_realtime_input(
                audio=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )
        self._audio_rolling_buffer.clear()

    async def call_tool(
        self, call_id: str, tool_name: str, tool_arguments: Dict[str, Any]
    ) -> None:
        """Execute a tool via ToolManagerService and send the result back to Gemini.

        Spawned as a background task by _handle_tool_call so the receive loop
        is not blocked while the tool executes.  A session-version guard ensures
        the response is discarded if a reconnect happened during execution.
        """
        session_version = self._session_version
        try:
            tool_result = await self.tool_manager_service.execute(
                connection_key=self.connection_key,
                tool_name=tool_name,
                call_arguments=tool_arguments,
            )
            result_str = str(tool_result)
        except Exception as e:
            logger.error(f"Gemini: Tool execution failed: {e}")
            result_str = f"Error: {e}"

        # Save to history so context survives reconnects regardless of outcome
        self._conversation_history.append(
            {
                "role": "model",
                "text": f"[Tool {tool_name}({tool_arguments}) → {result_str[:300]}]",
            }
        )

        if self._session is None:
            logger.warning(
                f"Gemini: session is closed, dropping tool response "
                f"(tool={tool_name}, call_id={call_id})"
            )
            return

        if self._session_version != session_version:
            logger.warning(
                f"Gemini: session was replaced during tool execution, dropping response "
                f"(tool={tool_name}, call_id={call_id})"
            )
            return

        try:
            await self._session.send_tool_response(
                function_responses=[
                    types.FunctionResponse(
                        id=call_id,
                        name=tool_name,
                        response={"result": result_str},
                    )
                ]
            )
        except Exception as e:
            logger.warning(
                f"Gemini: send_tool_response failed (session may have closed): "
                f"tool={tool_name}, call_id={call_id}, err={e}"
            )
