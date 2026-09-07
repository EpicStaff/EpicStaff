import base64
from typing import Any, Dict

import numpy as np
from loguru import logger


class ElevenLabsClientEventHandler:
    """
    Translates frontend OpenAI-format events into ElevenLabs WebSocket protocol messages.
    Includes real-time 24kHz to 16kHz audio resampling (browser path).
    """

    def __init__(self, client):
        from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import (
            ElevenLabsRealtimeAgentClient,
        )

        self.client: ElevenLabsRealtimeAgentClient = client
        self.event_map = {
            "input_audio_buffer.append": self._handle_audio_append,
            "input_audio_buffer.commit": self._handle_noop,
            "response.create": self._handle_noop,
            "response.cancel": self._handle_noop,
            "conversation.item.create": self._handle_conversation_item_create,
            "session.update": self._handle_noop,
        }

    async def handle_event(self, data: Dict[str, Any]) -> None:
        event_type = data.get("type", "")
        handler = self.event_map.get(event_type, self._handle_unknown)
        await handler(data)

    async def _handle_audio_append(self, data: Dict[str, Any]) -> None:
        audio_b64 = data.get("audio", "")
        if not audio_b64:
            return

        try:
            # Decode incoming audio (OpenAI frontend: PCM 16-bit Mono, 24kHz)
            pcm_data_24k = base64.b64decode(audio_b64)
            audio_array_24k = np.frombuffer(pcm_data_24k, dtype=np.int16)

            # Fast resampling from 24kHz to 16kHz for ElevenLabs (factor 2/3)
            indices = np.arange(0, len(audio_array_24k), 1.5).astype(np.int32)
            audio_array_16k = audio_array_24k[indices]

            resampled_b64 = base64.b64encode(audio_array_16k.tobytes()).decode("utf-8")

            await self.client.send_server({"user_audio_chunk": resampled_b64})
        except Exception as e:
            logger.error(
                f"ElevenLabs client handler: failed to process audio chunk: {e}"
            )

    async def _handle_conversation_item_create(self, data: Dict[str, Any]) -> None:
        """Frontend text-chat path (typed messages, not spoken audio). ElevenLabs'
        Conversational AI WebSocket protocol accepts injected text via a
        {"type": "user_message", "text": ...} frame -- see
        ElevenLabsRealtimeAgentClient.send_conversation_item_to_server."""
        item = data.get("item") or {}
        if item.get("role") not in (None, "user"):
            return

        text = "".join(
            part.get("text", "")
            for part in item.get("content", [])
            if isinstance(part, dict) and part.get("type") in ("input_text", "text")
        )
        if not text:
            return

        await self.client.server_event_handler.emit_user_text_item(text)
        await self.client.send_conversation_item_to_server(text)

    async def _handle_noop(self, data: Dict[str, Any]) -> None:
        pass

    async def _handle_unknown(self, data: Dict[str, Any]) -> None:
        logger.debug(
            f"ElevenLabs client handler: unhandled event type '{data.get('type')}'"
        )
