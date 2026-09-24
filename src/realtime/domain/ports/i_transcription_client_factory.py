from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable

from src.shared.models import RealtimeAgentChatData

from domain.ports.i_transcription_client import ITranscriptionClient
from domain.services.chat_buffer import ChatSummarizedBuffer


class ITranscriptionClientFactory(ABC):
    @abstractmethod
    def create(
        self,
        config: RealtimeAgentChatData,
        on_server_event: Callable[[dict], Awaitable[None]],
        buffer: ChatSummarizedBuffer,
    ) -> ITranscriptionClient | None: ...
