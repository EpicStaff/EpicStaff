"""Fakes for the Gemini Live SDK boundary (`genai.Client().aio.live.connect()`).

They mirror google-genai 1.19 on the points the adapter depends on:
- `receive()` ends after every `turn_complete` message while the session stays open;
- a server close raises the websocket's `ConnectionClosedOK` / `ConnectionClosedError`
  out of `receive()`, exactly as `ws.recv()` does underneath the SDK;
- a refused setup raises out of the connect context's `__aenter__`.
"""

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from google.genai import types
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK
from websockets.frames import Close

SESSION_RECORD_PATCH = (
    "infrastructure.providers.gemini.event_handlers.gemini_server_event_handler.save_realtime_session_item_to_db"
)

HANG = object()  # script item: the session stays open with nothing more to say until closed


def server_close(code: int = 1000, reason: str = "") -> ConnectionClosedOK | ConnectionClosedError:
    """The exception the SDK's receive() raises when Gemini closes the websocket."""
    frame = Close(code, reason)
    closed_type = ConnectionClosedOK if code in (1000, 1001) else ConnectionClosedError
    return closed_type(frame, frame, rcvd_then_sent=True)


def resumption_update(handle: str | None, resumable: bool) -> types.LiveServerMessage:
    return types.LiveServerMessage(
        session_resumption_update=types.LiveServerSessionResumptionUpdate(new_handle=handle, resumable=resumable)
    )


def turn_complete() -> types.LiveServerMessage:
    return types.LiveServerMessage(server_content=types.LiveServerContent(turn_complete=True))


class FakeSession:
    def __init__(self, config, script: list):
        self.config = config
        # Server messages, exceptions to raise, or HANG. An exhausted script is a
        # normal server close.
        self._script = list(script)
        self.audio: list[types.Blob] = []
        self.turns: list[tuple[types.Content, bool]] = []
        self.tool_responses: list[types.FunctionResponse] = []
        self.fail_tool_response = False
        self._closed = asyncio.Event()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def close(self) -> None:
        """Close from the client side: a pending receive() then raises ConnectionClosedOK."""
        self._closed.set()

    async def _next_message(self) -> types.LiveServerMessage:
        if self.closed or not self._script:
            raise server_close()
        if self._script[0] is HANG:
            await self._closed.wait()
            raise server_close()
        item = self._script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def receive(self):
        while True:
            message = await self._next_message()
            yield message
            if message.server_content and message.server_content.turn_complete:
                return

    async def send_realtime_input(self, audio):
        self.audio.append(audio)

    async def send_client_content(self, turns, turn_complete):
        self.turns.append((turns, turn_complete))

    async def send_tool_response(self, function_responses):
        if self.fail_tool_response:
            raise RuntimeError("ws closed")
        self.tool_responses.extend(function_responses)


class FakeGeminiLive:
    """`aio.live.connect(model, config)`: session N plays `scripts[N]` (default: stays open)."""

    def __init__(self):
        self.scripts: list[list] = []
        self.sessions: list[FakeSession] = []
        self.refuse_after: int | None = None
        # Raised from __aenter__ on every connect: the websocket upgrade failed
        # (InvalidStatus) or the network is down, before any setup is sent.
        self.upgrade_error: BaseException | None = None
        # Raised from __aenter__ only when the setup message carries a resumption
        # handle: Gemini's answer to that setup (a close frame).
        self.resume_error: BaseException | None = None
        # How many more times upgrade_error / resume_error is raised; None is forever.
        self.errors_left: int | None = None
        # Every connect attempt's resumption handle, failed attempts included.
        self.attempted_handles: list[str | None] = []
        # The setup reply never arrives: __aenter__ waits until cancelled.
        self.hang_connect = False
        # __aexit__ calls on a context whose __aenter__ never returned a session.
        self.exits_without_a_session = 0

    def _fail(self, error: BaseException) -> None:
        if self.errors_left is not None:
            if self.errors_left == 0:
                return
            self.errors_left -= 1
        raise error

    def connect(self, model, config):
        live = self

        class _SessionContext:
            async def __aenter__(self):
                if live.refuse_after is not None and len(live.sessions) >= live.refuse_after:
                    raise ConnectionError("Gemini refused the connection")
                live.attempted_handles.append(config.session_resumption.handle)
                if live.hang_connect:
                    await asyncio.Event().wait()
                if live.upgrade_error is not None:
                    live._fail(live.upgrade_error)
                if live.resume_error is not None and config.session_resumption.handle is not None:
                    live._fail(live.resume_error)
                index = len(live.sessions)
                session = FakeSession(config, live.scripts[index] if index < len(live.scripts) else [HANG])
                live.sessions.append(session)
                self.session = session
                return session

            async def __aexit__(self, *exc_info):
                session = getattr(self, "session", None)
                if session is None:
                    live.exits_without_a_session += 1
                    return
                session.close()

        return _SessionContext()


class FakeClock:
    """time.monotonic() for the adapter and its audio buffer, advanced by hand."""

    def __init__(self):
        self.now = 100.0

    def monotonic(self) -> float:
        return self.now


def patch_gemini_clock(monkeypatch) -> FakeClock:
    """Drive the timestamps of buffered caller audio and of stored resumption handles."""
    clock = FakeClock()
    for module in (
        "infrastructure.providers.gemini.gemini_realtime_agent_client",
        "infrastructure.providers.gemini.event_handlers.gemini_client_event_handler",
    ):
        monkeypatch.setattr(f"{module}.time", clock)
    return clock


class FakeBackoff:
    """Stands in for the adapter module's `asyncio` so connect retries don't really wait.

    Everything but sleep() is the real asyncio. sleep() records the delay and yields
    once; with `hold` set it waits until cancelled, like a long backoff would.
    """

    def __init__(self):
        self.delays: list[float] = []
        self.hold = False

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, delay: float) -> None:
        self.delays.append(delay)
        if self.hold:
            await asyncio.Event().wait()
        await asyncio.sleep(0)


def patch_gemini_backoff(monkeypatch) -> FakeBackoff:
    backoff = FakeBackoff()
    monkeypatch.setattr("infrastructure.providers.gemini.gemini_realtime_agent_client.asyncio", backoff)
    return backoff


@contextmanager
def patched_gemini_live() -> Iterator[FakeGeminiLive]:
    fake = FakeGeminiLive()
    with patch("infrastructure.providers.gemini.gemini_realtime_agent_client.genai") as genai:
        genai.Client.return_value = MagicMock()
        genai.Client.return_value.aio.live.connect = fake.connect
        yield fake
