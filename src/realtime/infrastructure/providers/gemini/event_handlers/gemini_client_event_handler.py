import base64
import time
from typing import Any, Dict

import numpy as np
from google.genai import types
from loguru import logger


class GeminiClientEventHandler:
    """
    Translates frontend OpenAI-format events into Gemini Live API SDK calls.
    Includes real-time 24kHz to 16kHz audio resampling (browser path).

    VAD strategy: Gemini's automatic VAD is disabled; we drive activity signals
    manually using the browser's own VAD events:
      response.cancel            → activity_start (user started speaking / barge-in)
      input_audio_buffer.commit  → activity_end   (user finished speaking)
    This prevents Gemini from closing the session on interruption.
    """

    def __init__(self, client):
        from infrastructure.providers.gemini.gemini_realtime_agent_client import (
            GeminiRealtimeAgentClient,
        )

        self.client: GeminiRealtimeAgentClient = client
        self.event_map = {
            "input_audio_buffer.append": self._handle_audio_append,
            "input_audio_buffer.commit": self._handle_audio_commit,
            "response.create": self._handle_noop,
            "response.cancel": self._handle_response_cancel,
            "conversation.item.create": self._handle_conversation_item_create,
            "conversation.item.truncate": self._handle_noop,  # OpenAI-specific; we use activity signals
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
            # Decode incoming PCM 16-bit Mono 24kHz from browser
            pcm_data_24k = base64.b64decode(audio_b64)
            audio_array_24k = np.frombuffer(pcm_data_24k, dtype=np.int16)

            # Downsample 24kHz → 16kHz (factor 2/3)
            indices = np.arange(0, len(audio_array_24k), 1.5).astype(np.int32)
            pcm16k_bytes = audio_array_24k[indices].tobytes()

            # Always maintain a rolling buffer of the last N seconds.
            # This ensures we capture user speech from before the interruption signal
            # arrives (VAD detection latency can be 300-500 ms).
            now = time.monotonic()
            buf = self.client._audio_rolling_buffer
            buf.append((now, pcm16k_bytes))
            cutoff = now - self.client._rolling_buffer_secs
            while buf and buf[0][0] < cutoff:
                buf.popleft()

            if self.client._session is not None:
                await self.client._session.send_realtime_input(
                    audio=types.Blob(data=pcm16k_bytes, mime_type="audio/pcm;rate=16000")
                )
        except Exception as e:
            logger.error(f"Gemini client handler: failed to process audio chunk: {e}")

    async def _handle_audio_commit(self, data: Dict[str, Any]) -> None:
        pass  # Server VAD mode: Gemini detects speech end automatically

    async def _handle_conversation_item_create(self, data: Dict[str, Any]) -> None:
        """Frontend text-chat path (typed messages, not spoken audio): OpenAI's
        wire format nests the text under item.content[].text. Gemini has no
        equivalent passive "create item" call -- send_client_content with
        turn_complete=True both adds the turn and triggers a response, so this
        is the one place that actually reaches Gemini for a typed message."""
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

    async def _handle_response_cancel(self, data: Dict[str, Any]) -> None:
        """Browser signals user interrupted — reset state and stop browser audio playback."""
        await self.client.server_event_handler.handle_client_cancel()

    async def _handle_noop(self, data: Dict[str, Any]) -> None:
        pass

    async def _handle_unknown(self, data: Dict[str, Any]) -> None:
        logger.debug(
            f"Gemini client handler: unhandled event type '{data.get('type')}'"
        )
