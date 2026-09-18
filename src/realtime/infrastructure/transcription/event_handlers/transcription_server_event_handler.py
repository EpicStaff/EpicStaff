from typing import Callable, Dict, Any, Coroutine
import json

from loguru import logger
from infrastructure.persistence.database import save_realtime_session_item_to_db
from domain.services.chat_buffer import ChatSummarizedBuffer


class TranscriptionServerEventHandler:
    """Handles mapping of WebSocket events to their corresponding methods."""

    def __init__(self, client, transcription_buffer: ChatSummarizedBuffer):
        self.transcription_buffer: ChatSummarizedBuffer = transcription_buffer
        from infrastructure.transcription.openai_realtime_transcription_client import (
            OpenaiRealtimeTranscriptionClient,
        )

        self.client: OpenaiRealtimeTranscriptionClient = client
        self.event_map: Dict[str, Callable[[Any], Coroutine[Any, Any, None]]] = {
            "response": self.default_handler,
            "response.created": self.default_handler,
            "session.created": self.transcription_session_created_handler,
            "session.updated": self.default_handler,
            "error": self.handle_error,
            "conversation.item.added": self.default_handler,
            "conversation.item.done": self.default_handler,

            "conversation.item.created": self.default_handler,
            "rate_limits.updated": self.default_handler,
            "input_audio_buffer.speech_started": self.default_handler,
            "input_audio_buffer.speech_stopped": self.default_handler,
            "input_audio_buffer.committed": self.default_handler,
            "input_audio_buffer.cleared": self.default_handler,
            "response.content_part.added": self.default_handler,
            "conversation.item.input_audio_transcription.delta": self.default_handler,
            "conversation.item.input_audio_transcription.completed": self.input_audio_transcription_completed_handler,
            "conversation.item.input_audio_transcription.failed": self.default_handler,
        }

    async def handle_event(self, data: Dict[str, Any]):
        """Handle incoming event by calling the appropriate method."""
        event_type = data.get("type", "")
        handler = self.event_map.get(event_type, self.unknown_event_handler)
        await handler(data)
        await save_realtime_session_item_to_db(
            data=data,
            connection_key=self.client.connection_key,
            org_id=self.client.org_id,
            user_id=self.client.user_id,
        )

    async def default_handler(self, data: Dict[str, Any]) -> None:
        await self.client.send_client(data)

    async def unknown_event_handler(self, data: Dict[str, Any]) -> None:
        """Default handler for unknown events."""
        logger.warning(f"Unknown event type received: {json.dumps(data, indent=2)}")

        await self.default_handler(data)

    async def handle_error(self, data: Dict[str, Any]) -> None:
        logger.error(f"Error received: {data}")
        await self.default_handler(data)

    async def handle_function_call_delta(self, data: Dict[str, Any]) -> None:
        pass

    async def handle_function_call_done(self, data: Dict[str, Any]) -> None:
        await self.client.call_tool(
            call_id=data["call_id"],
            tool_name=data["name"],
            tool_arguments=json.loads(data["arguments"]),
        )
        await self.default_handler(data)

    async def transcription_session_created_handler(self, data):
        pass

    async def input_audio_transcription_completed_handler(self, data: dict):
        transcript_data = data["transcript"]
        logger.debug(f"Transcript data in handler {transcript_data}")
        self.transcription_buffer.append(transcript_data)
        logger.debug(
            f"self.transcription_buffer {self.transcription_buffer.get_buffer()}"
        )

        await self.default_handler(data)
