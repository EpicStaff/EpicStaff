import audioop
import base64
import json
import uuid
from typing import Any, Dict, Optional

import numpy as np

from infrastructure.persistence.database import save_realtime_session_item_to_db
from loguru import logger


class ElevenLabsServerEventHandler:
    def __init__(self, client):
        from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import (
            ElevenLabsRealtimeAgentClient,
        )

        self.client: ElevenLabsRealtimeAgentClient = client

        self._current_response_id: Optional[str] = None
        self._current_item_id: Optional[str] = None
        self._current_user_item_id: Optional[str] = None

        self._current_output_index = 0

    def reset(self) -> None:
        """
        Clear transient response state so the next reconnect starts fresh.
        """
        self._current_response_id = None
        self._current_item_id = None
        self._current_user_item_id = None
        self._current_output_index = 0

    async def _send_to_client(self, payload: Dict[str, Any]) -> None:
        if "event_id" not in payload:
            payload["event_id"] = f"evt_{uuid.uuid4().hex[:16]}"
        await self.client.send_client(payload)

    async def _ensure_response_exists(self):
        if not self._current_response_id:
            self._current_response_id = f"resp_{uuid.uuid4().hex[:10]}"
            self._current_output_index = 0

            if not self._current_user_item_id:
                self._current_user_item_id = f"msg_user_{uuid.uuid4().hex[:10]}"
                await self._send_to_client(
                    {
                        "type": "conversation.item.created",
                        "item": {
                            "id": self._current_user_item_id,
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_audio", "transcript": None}],
                        },
                    }
                )

            await self._send_to_client(
                {
                    "type": "response.created",
                    "response": {
                        "id": self._current_response_id,
                        "object": "realtime.response",
                        "status": "in_progress",
                        "output": [],
                    },
                }
            )

    async def _ensure_assistant_item(self):
        await self._ensure_response_exists()

        if not self._current_item_id:
            self._current_item_id = f"msg_{uuid.uuid4().hex[:10]}"
            self._assistant_output_index = self._current_output_index

            agent_item = {
                "id": self._current_item_id,
                "type": "message",
                "role": "assistant",
                "status": "in_progress",
                "content": [{"type": "audio", "transcript": ""}],
            }

            await self._send_to_client(
                {
                    "type": "response.output_item.added",
                    "response_id": self._current_response_id,
                    "output_index": self._assistant_output_index,
                    "item": agent_item,
                }
            )

            await self._send_to_client(
                {"type": "conversation.item.created", "item": agent_item}
            )

            self._current_output_index += 1

    async def handle_event(self, data: Dict[str, Any]) -> None:
        event_type = data.get("type", "")
        if event_type not in ("audio", "ping"):
            logger.debug(f"EL Event Routing: {event_type}")

        handler = {
            "conversation_initiation_metadata": self._handle_initiation_metadata,
            "audio": self._handle_audio,
            "agent_response": self._handle_agent_response,
            "user_transcript": self._handle_user_transcript,
            "interruption": self._handle_interruption,
            "client_tool_call": self._handle_client_tool_call,
            "ping": self._handle_ping,
        }.get(event_type, self._handle_ignored)

        await handler(data)
        await save_realtime_session_item_to_db(
            data=data,
            connection_key=self.client.connection_key,
            org_id=self.client.org_id,
            user_id=self.client.user_id,
        )

    async def _handle_initiation_metadata(self, data: Dict[str, Any]) -> None:
        meta = data.get("conversation_initiation_metadata_event", {})
        await self._send_to_client(
            {
                "type": "session.created",
                "session": {
                    "id": meta.get("conversation_id", ""),
                    "object": "realtime.session",
                    "provider": "elevenlabs",
                },
            }
        )

    async def _handle_audio(self, data: Dict[str, Any]) -> None:
        audio_event = data.get("audio_event", {})
        audio_b64 = (
            audio_event.get("audio_base_64")
            or data.get("audio_base_64")
            or data.get("chunk", "")
        )
        if not audio_b64:
            return

        await self._ensure_assistant_item()

        # Convert PCM 16kHz to the appropriate format for the consumer:
        # - Twilio path: PCM 16kHz → µ-law 8kHz (stateful resampling on client)
        # - Browser path: PCM 16kHz → PCM 24kHz (numpy interpolation)
        if self.client.is_twilio:
            audio_b64 = self._pcm16k_to_ulaw8k(audio_b64)
        else:
            audio_b64 = self._pcm16k_to_pcm24k(audio_b64)

        await self._send_to_client(
            {
                "type": "response.audio.delta",
                "response_id": self._current_response_id,
                "item_id": self._current_item_id,
                "output_index": self._assistant_output_index,
                "content_index": 0,
                "delta": audio_b64,
            }
        )

    def _pcm16k_to_ulaw8k(self, audio_b64: str) -> str:
        """Convert base64 PCM 16kHz → base64 µ-law 8kHz for Twilio output."""
        pcm16k = base64.b64decode(audio_b64)
        pcm8k, self.client._down_resample_state = audioop.ratecv(
            pcm16k, 2, 1, 16000, 8000, self.client._down_resample_state
        )
        return base64.b64encode(audioop.lin2ulaw(pcm8k, 2)).decode()

    def _pcm16k_to_pcm24k(self, audio_b64: str) -> str:
        """Upsample base64 PCM 16kHz → base64 PCM 24kHz for browser output."""
        try:
            pcm_data = base64.b64decode(audio_b64)
            audio_16k = np.frombuffer(pcm_data, dtype=np.int16)
            if len(audio_16k) == 0:
                return audio_b64
            x_16k = np.arange(len(audio_16k))
            x_24k = np.linspace(0, len(audio_16k) - 1, int(len(audio_16k) * 1.5))
            audio_24k = np.interp(x_24k, x_16k, audio_16k).astype("<i2")
            return base64.b64encode(audio_24k.tobytes()).decode()
        except Exception as e:
            logger.error(f"ElevenLabs audio upsample error: {e}")
            return audio_b64

    async def _handle_agent_response(self, data: Dict[str, Any]) -> None:
        agent_response_event = data.get("agent_response_event", {})
        text = agent_response_event.get("agent_response", "")

        if not self._current_response_id or not text:
            return

        rid, iid = self._current_response_id, self._current_item_id
        idx = getattr(self, "_assistant_output_index", 0)

        await self._send_to_client(
            {
                "type": "response.audio_transcript.delta",
                "response_id": rid,
                "item_id": iid,
                "output_index": idx,
                "content_index": 0,
                "delta": text,
            }
        )

        await self._send_to_client(
            {
                "type": "response.audio_transcript.done",
                "response_id": rid,
                "item_id": iid,
                "output_index": idx,
                "content_index": 0,
                "transcript": text,
            }
        )

        await self._send_to_client(
            {
                "type": "response.audio.done",
                "response_id": rid,
                "item_id": iid,
                "output_index": idx,
                "content_index": 0,
            }
        )

        await self._send_to_client(
            {
                "type": "response.output_item.done",
                "response_id": rid,
                "item": {"id": iid, "status": "completed"},
            }
        )

        await self._send_to_client(
            {"type": "response.done", "response": {"id": rid, "status": "completed"}}
        )

        logger.info(f"Assistant turn finished with transcript: {text[:30]}...")

        self._current_response_id = None
        self._current_item_id = None
        self._current_user_item_id = None
        self._current_output_index = 0

    async def emit_user_text_item(self, text: str) -> None:
        """Echo a frontend-typed message back as the user's chat bubble.

        Unlike spoken input (transcribed server-side and delivered via
        `_handle_user_transcript`), ElevenLabs never echoes back text we
        inject via `user_message` -- there is nothing to transcribe. We
        already know the exact text, so synthesize the same
        `conversation.item.created` the frontend expects, immediately,
        instead of leaving the bubble stuck on a null transcript.
        """
        self._current_user_item_id = f"msg_user_{uuid.uuid4().hex[:10]}"
        await self._send_to_client(
            {
                "type": "conversation.item.created",
                "item": {
                    "id": self._current_user_item_id,
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": text}],
                },
            }
        )

    async def _handle_user_transcript(self, data: Dict[str, Any]) -> None:
        user_transcription_event = data.get("user_transcription_event", {})
        text = user_transcription_event.get("user_transcript", "")
        if not text:
            return

        if not self._current_user_item_id:
            self._current_user_item_id = f"msg_user_{uuid.uuid4().hex[:10]}"
            await self._send_to_client(
                {
                    "type": "conversation.item.created",
                    "item": {
                        "id": self._current_user_item_id,
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_audio", "transcript": None}],
                    },
                }
            )

        await self._send_to_client(
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "item_id": self._current_user_item_id,
                "content_index": 0,
                "transcript": text,
            }
        )

    async def _handle_client_tool_call(self, data: Dict[str, Any]) -> None:
        tool_call = data.get("client_tool_call", {})
        tool_call_id = tool_call.get("tool_call_id", "")
        tool_name = tool_call.get("tool_name", "")
        parameters = tool_call.get("parameters", {})

        await self._ensure_response_exists()

        await self._send_to_client(
            {
                "type": "conversation.item.created",
                "item": {
                    "id": tool_call_id,
                    "type": "function_call",
                    "status": "in_progress",
                    "name": tool_name,
                    "call_id": tool_call_id,
                    "arguments": "",
                },
            }
        )

        await self._send_to_client(
            {
                "type": "response.output_item.added",
                "response_id": self._current_response_id,
                "output_index": self._current_output_index,
                "item": {
                    "id": tool_call_id,
                    "type": "function_call",
                    "name": tool_name,
                    "call_id": tool_call_id,
                    "arguments": "",
                },
            }
        )

        await self._send_to_client(
            {
                "type": "response.function_call_arguments.done",
                "response_id": self._current_response_id,
                "item_id": tool_call_id,
                "output_index": self._current_output_index,
                "call_id": tool_call_id,
                "name": tool_name,
                "arguments": json.dumps(parameters),
            }
        )

        self._current_output_index += 1
        logger.info(f"EL Tool Execution: {tool_name}")
        await self.client.call_tool(tool_call_id, tool_name, parameters)

    async def _handle_interruption(self, data: Dict[str, Any]) -> None:
        self._current_response_id = None
        self._current_item_id = None
        self._current_output_index = 0
        await self._send_to_client({"type": "input_audio_buffer.speech_started"})

    async def _handle_ping(self, data: Dict[str, Any]) -> None:
        event_id = data.get("ping_event", {}).get("event_id")
        await self.client.send_server({"type": "pong", "event_id": event_id})

    async def _handle_ignored(self, data: Dict[str, Any]) -> None:
        pass

    async def _handle_unknown(self, data: Dict[str, Any]) -> None:
        logger.warning(f"Unknown EL event: {data.get('type')}")
