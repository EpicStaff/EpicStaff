from abc import ABC, abstractmethod
from typing import Any


class IRealtimeAgentClient(ABC):
    """
    Port: contract every realtime AI provider adapter must fulfill.

    Audio conventions:
    - send_audio() accepts raw Twilio µ-law 8kHz, base64-encoded.
      Each adapter converts to its own native format internally.
    - stream_sid / is_twilio are set lazily once the Twilio `start` event arrives.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Open provider WebSocket and perform session handshake."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Gracefully close the provider WebSocket."""
        ...

    @abstractmethod
    async def handle_messages(self) -> None:
        """
        Long-running loop: receive frames from provider WebSocket and
        dispatch to server event handler.  Meant to run as asyncio.Task.
        """
        ...

    # ------------------------------------------------------------------
    # Frontend → Provider
    # ------------------------------------------------------------------

    @abstractmethod
    async def process_message(self, message: dict) -> dict | None:
        """
        Translate a frontend WebSocket message into the provider's wire
        format and send it.  Returns an optional immediate response to
        forward back to the frontend.
        """
        ...

    @abstractmethod
    async def send_audio(self, ulaw8k_b64: str) -> None:
        """
        Accept base64-encoded µ-law 8kHz audio (from Twilio) and forward
        it to the provider in its expected format.
        Implementations handle any sample-rate conversion internally.
        """
        ...

    @abstractmethod
    async def send_conversation_item_to_server(self, text: str) -> None:
        """Inject a user text turn directly (used in LISTEN mode wake-word trigger)."""
        ...

    @abstractmethod
    async def request_response(self, data: dict | None = None) -> None:
        """
        Request the provider to generate a response.
        No-op for providers that operate in auto-response mode (e.g. ElevenLabs).
        """
        ...

    @abstractmethod
    async def on_stream_start(self) -> None:
        """
        Called when the Twilio `start` event is received.
        OpenAI sends response.create; ElevenLabs is a no-op.
        """
        ...

    # ------------------------------------------------------------------
    # Provider → Application (tool execution)
    # ------------------------------------------------------------------

    @abstractmethod
    async def call_tool(self, call_id: str, tool_name: str, tool_arguments: dict[str, Any]) -> None:
        """Execute a tool and send the result back to the provider."""
        ...

    @abstractmethod
    async def replay_audio_buffer(self) -> None:
        """
        Replay any buffered user audio to the provider after a reconnect.
        Providers that do not buffer audio should implement this as a no-op.
        """
        ...

    # ------------------------------------------------------------------
    # State properties (Twilio bridge support)
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def stream_sid(self) -> str | None: ...

    @stream_sid.setter
    @abstractmethod
    def stream_sid(self, value: str) -> None: ...

    @property
    @abstractmethod
    def is_twilio(self) -> bool: ...

    @is_twilio.setter
    @abstractmethod
    def is_twilio(self, value: bool) -> None: ...
