from loguru import logger
import websockets
import json
from typing import Optional, Dict, Any, Callable, Awaitable

from infrastructure.transcription.event_handlers.transcription_client_event_handler import (
    TranscriptionClientEventHandler,
)
from infrastructure.transcription.event_handlers.transcription_server_event_handler import (
    TranscriptionServerEventHandler,
)

from domain.ports.i_transcription_client import ITranscriptionClient
from domain.services.chat_buffer import ChatSummarizedBuffer
from utils.openai_endpoints import derive_realtime_ws_url


class OpenaiRealtimeTranscriptionClient(ITranscriptionClient):
    def __init__(
        self,
        api_key: str,
        connection_key: str,
        on_server_event: Optional[Callable[[dict], Awaitable[None]]] = None,
        model: str = "whisper-1",
        language: str | None = None,
        voice_recognition_prompt: str | None = None,
        buffer: ChatSummarizedBuffer = None,
        connection_model: str = "gpt-realtime-1.5",
        org_id: int | None = None,
        user_id: int | None = None,
        base_url: str | None = None,
    ):
        self.api_key = api_key
        self.connection_key = connection_key
        self.on_server_event = on_server_event
        self.org_id = org_id
        self.user_id = user_id
        self.model = model
        self.connection_model = connection_model
        self.ws = None
        self.language = language
        self.voice_recognition_prompt = voice_recognition_prompt
        self.base_url = derive_realtime_ws_url(base_url)
        self.turn_detection_mode = "server_vad"

        self.buffer = buffer
        self.words_qty_in_buffer: int = 0

        self.server_event_handler = TranscriptionServerEventHandler(
            self, transcription_buffer=self.buffer
        )
        self.client_event_handler = TranscriptionClientEventHandler(self, buffer=buffer)

    async def connect(self) -> None:
        url = f"{self.base_url}?intent=transcription"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }

        self.ws = await websockets.connect(url, extra_headers=headers)

        await self.update_session()

    async def send_client(self, data):
        if self.on_server_event:
            await self.on_server_event(data)

    async def update_session(self) -> None:
        transcription: Dict[str, Any] = {"model": self.model}
        if self.language is not None:
            transcription["language"] = self.language
        if self.voice_recognition_prompt is not None:
            transcription["prompt"] = self.voice_recognition_prompt

        data = {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                        },
                        "transcription": transcription,
                        "noise_reduction": {"type": "near_field"},
                    },
                },
                "include": [
                    "item.input_audio_transcription.logprobs",
                ],
            },
        }

        await self.send_server(data)

    async def process_message(
        self, message: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Process incoming message from the frontend WebSocket."""
        return await self.client_event_handler.handle_event(data=message)

    async def handle_messages(self) -> None:
        """Handle incoming messages from the OpenAI API."""
        logger.info("Starting message handler...")
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)

                    await self.server_event_handler.handle_event(data)

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode API message {e}")
                except Exception:
                    logger.exception("Error processing API message")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket connection {self.connection_key} closed")
        except Exception:
            logger.exception("Error in message handler")

    async def close(self) -> None:
        """Close the WebSocket connection."""
        if self.ws:
            await self.ws.close()

    async def send_server(self, event: dict):
        await self.ws.send(json.dumps(event))

    def get_transcription_buffer(self) -> ChatSummarizedBuffer:
        return self.buffer
