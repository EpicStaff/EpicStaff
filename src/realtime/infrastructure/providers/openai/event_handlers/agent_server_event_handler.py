from typing import Callable, Dict, Any, Coroutine
import json

from loguru import logger
from infrastructure.persistence.database import save_realtime_session_item_to_db


class ServerEventHandler:
    """Handles mapping of WebSocket events to their corresponding methods."""

    def __init__(self, client):
        """Initialize the event handler with event mappings."""
        from infrastructure.providers.openai.openai_realtime_agent_client import (
            OpenaiRealtimeAgentClient,
        )

        self.client: OpenaiRealtimeAgentClient = client
        self.event_map: Dict[str, Callable[[Any], Coroutine[Any, Any, None]]] = {
            "response": self.default_handler,
            "response.created": self.default_handler,
            "session.created": self.default_handler,
            "error": self.handle_error,
            "session.updated": self.handle_session_updated,
            "conversation.item.added": self.conversation_item_created_handler,
            "conversation.item.done": self.conversation_item_created_handler,
            "conversation.item.created": self.conversation_item_created_handler,
            "rate_limits.updated": self.default_handler,
            "response.output_item.added": self.default_handler,
            "response.output_item.done": self.default_handler,
            "response.content_part.added": self.default_handler,
            "response.content_part.done": self.default_handler,
            "response.done": self.default_handler,
            "response.output_audio.delta": self.default_handler,
            "response.output_audio.done": self.default_handler,
            "response.output_audio_transcript.delta": self.default_handler,
            "response.output_audio_transcript.done": self.default_handler,
            "response.output_text.delta": self.default_handler,
            "response.output_text.done": self.default_handler,
            "response.audio.delta": self.default_handler,
            "response.audio.done": self.default_handler,
            "response.audio_transcript.delta": self.default_handler,
            "response.audio_transcript.done": self.default_handler,
            "response.text.delta": self.default_handler,
            "response.text.done": self.default_handler,
            "input_audio_buffer.speech_started": self.default_handler,
            "input_audio_buffer.speech_stopped": self.default_handler,
            "input_audio_buffer.committed": self.default_handler,
            "input_audio_buffer.cleared": self.default_handler,
            "response.function_call_arguments.delta": self.handle_function_call_delta,
            "response.function_call_arguments.done": self.handle_function_call_done,
            "conversation.item.input_audio_transcription.delta": self.default_handler,
            "conversation.item.input_audio_transcription.completed": self.default_handler,
            "conversation.item.input_audio_transcription.failed": self.handle_transcription_failed,
        }

    def reset(self) -> None:
        """
        Mirrors GeminiServerEventHandler.reset(). For OpenAI the response/item
        state lives on the client itself, so we clear it via the back-reference.
        """
        self.client._current_response_id = None
        self.client._current_item_id = None
        self.client._is_responding = False
        self.client._output_transcript_buffer = ""

    _GA_TO_INTERNAL_EVENT: Dict[str, str] = {
        "response.output_audio.delta": "response.audio.delta",
        "response.output_audio.done": "response.audio.done",
        "response.output_audio_transcript.delta": "response.audio_transcript.delta",
        "response.output_audio_transcript.done": "response.audio_transcript.done",
        "response.output_text.delta": "response.text.delta",
        "response.output_text.done": "response.text.done",
        "conversation.item.added": "conversation.item.created",
    }

    @classmethod
    def _normalize_event_type(cls, event_type: str) -> str:
        return cls._GA_TO_INTERNAL_EVENT.get(event_type, event_type)

    async def handle_event(self, data: Dict[str, Any]) -> None:
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
        event_type = data.get("type", "")
        normalized = self._normalize_event_type(event_type)
        if normalized != event_type:
            data = {**data, "type": normalized}
        await self.client.send_client(data)

    async def unknown_event_handler(self, data: Dict[str, Any]) -> None:
        """Default handler for unknown events."""
        logger.warning(f"Unknown event type received: {json.dumps(data, indent=2)}")

        await self.default_handler(data)

    async def handle_error(self, data: Dict[str, Any]) -> None:
        logger.error(f"Error received: {data}")
        await self.default_handler(data)

    async def handle_session_updated(self, data: Dict[str, Any]) -> None:
        session = data.get("session", {})
        audio = session.get("audio", {})
        logger.info(
            f"[session.updated] output_format={audio.get('output', {}).get('format')} "
            f"input_format={audio.get('input', {}).get('format')}"
        )
        await self.default_handler(data)

    async def handle_transcription_failed(self, data: Dict[str, Any]) -> None:
        logger.error(f"Input audio transcription failed: {data}")
        await self.default_handler(data)

    async def handle_function_call_delta(self, data: Dict[str, Any]) -> None:
        pass

    async def handle_function_call_done(self, data: Dict[str, Any]) -> None:
        logger.info(
            f"OpenAI: Calling tool '{data['name']}' with args: {str(data.get('arguments') or '')[:200]}"
        )
        await self.client.call_tool(
            call_id=data["call_id"],
            tool_name=data["name"],
            tool_arguments=json.loads(data["arguments"]),
        )
        await self.default_handler(data)

    async def conversation_item_created_handler(self, data: dict):
        if data["item"]["id"] == "dont_show_it":
            return

        await self.default_handler(data)
