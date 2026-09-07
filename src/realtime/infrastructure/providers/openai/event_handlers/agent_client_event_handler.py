import base64
from typing import Callable, Dict, Any, Coroutine
import json

from loguru import logger
from infrastructure.persistence.database import save_realtime_session_item_to_db


class ClientEventHandler:
    """Handles mapping of client websocket events to their corresponding methods."""

    def __init__(self, client):
        """Initialize the event handler with event mappings."""
        from infrastructure.providers.openai.openai_realtime_agent_client import (
            OpenaiRealtimeAgentClient,
        )

        self.client: OpenaiRealtimeAgentClient = client
        self.event_map: Dict[str, Callable[[Any], Coroutine[Any, Any, None]]] = {
            "input_audio_buffer.commit": self.handle_input_audio_buffer_commit,
            "input_audio_buffer.append": self.handle_input_audio_buffer_append,
            "conversation.item.create": self.handle_conversation_item_create,
            "response.create": self.handle_response_create,
            "response.cancel": self.handle_response_cancel,
            "session.update": self.handle_session_update,
            "transcription_session.update": self._handle_noop,
        }

    async def handle_event(self, data: Dict[str, Any]) -> None:
        """Handle incoming event by calling the appropriate method."""
        event_type = data.get("type")

        if event_type != "input_audio_buffer.append":
            logger.debug(f"Processing event type: {event_type}")

        handler = self.event_map.get(event_type, self.unknown_event_handler)
        await handler(data)
        await save_realtime_session_item_to_db(
            data=data,
            connection_key=self.client.connection_key,
            org_id=self.client.org_id,
            user_id=self.client.user_id,
        )

    async def unknown_event_handler(self, data: Dict[str, Any]) -> None:
        """Default handler for unknown events."""
        logger.error(f"Unknown event type received: {json.dumps(data, indent=2)}")
        return

    async def handle_input_audio_buffer_commit(self, data: Dict[str, Any]) -> None:
        await self.client.send_server(data)

    async def handle_input_audio_buffer_append(self, data: Dict[str, Any]) -> None:
        await self.client.send_server(data)

    async def handle_conversation_item_create(self, data):
        await self.client.send_server(data)

    async def handle_response_create(self, data):
        await self.client.request_response(data)

    async def handle_response_cancel(self, data):
        await self.cancel_response()

    async def handle_session_update(self, data: dict):
        incoming = data.get("session") or {}

        safe_config: Dict[str, Any] = {}

        if "voice" in incoming:
            safe_config["voice"] = incoming["voice"]
        if "instructions" in incoming:
            self.client.instructions = incoming["instructions"]
        if "tool_choice" in incoming:
            safe_config["tool_choice"] = incoming["tool_choice"]
        if "turn_detection" in incoming:
            safe_config["turn_detection"] = incoming["turn_detection"]

        # legacy beta -> GA
        if "modalities" in incoming and "output_modalities" not in incoming:
            safe_config["output_modalities"] = incoming["modalities"]
        if "output_modalities" in incoming:
            safe_config["output_modalities"] = incoming["output_modalities"]

        if "input_audio_format" in incoming:
            safe_config["input_audio_format"] = incoming["input_audio_format"]
        if "output_audio_format" in incoming:
            safe_config["output_audio_format"] = incoming["output_audio_format"]
        if "input_audio_transcription" in incoming:
            safe_config["input_audio_transcription"] = incoming[
                "input_audio_transcription"
            ]

        await self.client.update_session(config=safe_config)

    async def _handle_noop(self, data: dict) -> None:
        """Silently drop an event we intentionally do not forward."""
        logger.debug(
            f"Dropping non-forwardable event on agent socket: {data.get('type')}"
        )

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send audio data to the API."""
        pcm_data = base64.b64encode(audio_bytes).decode()

        append_event = {"type": "input_audio_buffer.append", "audio": pcm_data}
        await self.client.send_server(append_event)

    async def cancel_response(self) -> None:
        """Cancel the current response."""
        event = {"type": "response.cancel"}
        await self.client.send_server(event)
