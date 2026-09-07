import json
from abc import abstractmethod
from typing import Any, Callable, Awaitable, Optional

from domain.ports.i_realtime_agent_client import IRealtimeAgentClient


class BaseRealtimeAgentClient(IRealtimeAgentClient):
    """
    Abstract base class for all realtime AI provider adapters.
    Holds the shared WebSocket state and provides common send_server / send_client helpers.
    Concrete subclasses implement the provider-specific protocol.
    """

    def __init__(
        self,
        api_key: str,
        connection_key: str,
        on_server_event: Optional[Callable[[dict], Awaitable[None]]] = None,
        org_id: Optional[int] = None,
        user_id: Optional[int] = None,
    ):
        self.api_key = api_key
        self.connection_key = connection_key
        self.on_server_event = on_server_event
        self.org_id = org_id
        self.user_id = user_id
        self.ws = None

        self._stream_sid: Optional[str] = None
        self._is_twilio: bool = False

    # ------------------------------------------------------------------
    # IRealtimeAgentClient: state properties
    # ------------------------------------------------------------------

    @property
    def stream_sid(self) -> Optional[str]:
        return self._stream_sid

    @stream_sid.setter
    def stream_sid(self, value: str) -> None:
        self._stream_sid = value

    @property
    def is_twilio(self) -> bool:
        return self._is_twilio

    @is_twilio.setter
    def is_twilio(self, value: bool) -> None:
        self._is_twilio = value

    # ------------------------------------------------------------------
    # Shared communication helpers
    # ------------------------------------------------------------------

    async def send_server(self, event: dict) -> None:
        """Send a message to the provider WebSocket."""
        if self.ws:
            await self.ws.send(json.dumps(event))

    async def send_client(self, data: dict) -> None:
        """Forward a message to the frontend via the on_server_event callback."""
        if self.on_server_event:
            await self.on_server_event(data)

    async def close(self) -> None:
        """Close the provider WebSocket."""
        if self.ws:
            await self.ws.close()

    # ------------------------------------------------------------------
    # Abstract methods left to provider implementations
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def handle_messages(self) -> None: ...

    @abstractmethod
    async def process_message(self, message: dict) -> Optional[dict]: ...

    @abstractmethod
    async def send_audio(self, ulaw8k_b64: str) -> None: ...

    @abstractmethod
    async def send_conversation_item_to_server(self, text: str) -> None: ...

    @abstractmethod
    async def request_response(self, data: dict | None = None) -> None: ...

    @abstractmethod
    async def on_stream_start(self) -> None: ...

    @abstractmethod
    async def call_tool(
        self, call_id: str, tool_name: str, tool_arguments: dict[str, Any]
    ) -> None: ...

    async def replay_audio_buffer(self) -> None:
        """No-op default — providers without a rolling buffer do nothing on reconnect."""
        pass
