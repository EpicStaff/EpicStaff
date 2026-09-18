from typing import Callable, Awaitable, Optional

from domain.ports.i_transcription_client import ITranscriptionClient
from domain.ports.i_transcription_client_factory import ITranscriptionClientFactory
from domain.services.chat_buffer import ChatSummarizedBuffer
from src.shared.models import RealtimeAgentChatData

from infrastructure.transcription.openai_realtime_transcription_client import (
    OpenaiRealtimeTranscriptionClient,
)


class TranscriptionClientFactory(ITranscriptionClientFactory):
    """
    Composition-root factory: the only place that decides which transcription
    client to instantiate (or return None for providers with built-in STT).
    """

    def create(
        self,
        config: RealtimeAgentChatData,
        on_server_event: Callable[[dict], Awaitable[None]],
        buffer: ChatSummarizedBuffer,
    ) -> Optional[ITranscriptionClient]:
        if config.rt_provider in ("elevenlabs", "gemini"):
            return None
        if not config.transcript_api_key:
            return None
        return OpenaiRealtimeTranscriptionClient(
            api_key=config.transcript_api_key,
            connection_key=config.connection_key,
            on_server_event=on_server_event,
            model="gpt-4o-mini-transcribe",
            language=config.language,
            voice_recognition_prompt=config.voice_recognition_prompt,
            buffer=buffer,
            org_id=config.org_id,
            user_id=config.user_id,
            base_url=config.rt_base_url,
        )
