from typing import Callable, Dict, Any, Coroutine
import json

from loguru import logger
from infrastructure.persistence.database import save_realtime_session_item_to_db
from domain.services.chat_buffer import ChatSummarizedBuffer


class TranscriptionClientEventHandler:
    """Handles mapping of client websocket events to their corresponding methods."""

    def __init__(self, client, buffer: ChatSummarizedBuffer):
        """Initialize the event handler with event mappings."""
        from infrastructure.transcription.openai_realtime_transcription_client import (
            OpenaiRealtimeTranscriptionClient,
        )

        self.client: OpenaiRealtimeTranscriptionClient = client
        self.event_map: Dict[str, Callable[[Any], Coroutine[Any, Any, None]]] = {
            "input_audio_buffer.append": self.handle_input_audio_buffer_append,
            "session.update": self.handle_session_update,
            "conversation.item.create": self.handle_conversation_item_create,
        }
        self.buffer = buffer

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
        logger.warning(f"Unknown event type received: {json.dumps(data, indent=2)}")

    async def handle_input_audio_buffer_commit(self, data: Dict[str, Any]) -> None:
        await self.client.send_server(data)

    async def handle_input_audio_buffer_append(self, data: Dict[str, Any]) -> None:
        await self.client.send_server(data)

    async def handle_session_update(self, data: dict):
        pass

    async def handle_conversation_item_create(self, data: dict):
        text = data["item"]["content"][0]["text"]
        logger.debug(f"Text entered with keyboard: {text}")
        self.buffer.append(text)

        import uuid

        event_id = f"event_{str(uuid.uuid4())}"
        item_id = f"item_{str(uuid.uuid4())}"

        e4 = {
            "type": "conversation.item.created",
            "event_id": event_id,
            "previous_item_id": None,
            "item": {
                "id": item_id,
                "object": "realtime.item",
                "type": "message",
                "status": "completed",
                "role": "user",
                "content": [{"type": "input_audio", "transcript": None}],
            },
        }

        e6 = {
            "type": "conversation.item.input_audio_transcription.completed",
            "event_id": event_id,
            "item_id": item_id,
            "content_index": 0,
            "transcript": f"{text}\n",
        }

        await self.client.send_client(e4)
        await self.client.send_client(e6)
