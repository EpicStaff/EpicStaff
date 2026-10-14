"""VoiceCallService bridges a Twilio media stream to a realtime provider.

Every test runs `execute()`: a scripted Twilio socket feeds frames, a fake provider
records what it is sent and pushes provider events through the callback the factory
gave it, and Django's recording/end API sits behind an httpx MockTransport.
"""

import asyncio
import base64
import json

import httpx
import pytest

from application.voice_call_service import MIN_CHUNK_SIZE, VoiceCallService
from src.shared.models import RealtimeAgentChatData

pytestmark = pytest.mark.asyncio


def _make_chat_data() -> RealtimeAgentChatData:
    return RealtimeAgentChatData(
        connection_key="test_key",
        org_id=1,
        rt_api_key="api_key",
        rt_model_name="gpt-4o",
        rt_provider="openai",
        wake_word=None,
        voice="alloy",
        temperature=0.7,
        language="en",
        goal="help",
        backstory="assistant",
        role="assistant",
        knowledge_collection_id=None,
        memory=False,
        stop_prompt=None,
        voice_recognition_prompt=None,
        tools=[],
        llm=None,
    )


class FakeProvider:
    """A realtime provider client: records audio and stream starts; emits events via `emit`."""

    def __init__(self, on_server_event, handle_messages=None):
        self.emit = on_server_event
        self.stream_sid = None
        self.is_twilio = True
        self.stream_starts = 0
        self.sent_audio: list[bytes] = []
        self.closed = False
        self._handle_messages = handle_messages

    async def connect(self):
        pass

    async def handle_messages(self):
        if self._handle_messages is not None:
            await self._handle_messages()
        else:
            await asyncio.Event().wait()

    async def on_stream_start(self):
        self.stream_starts += 1

    async def send_audio(self, audio_b64: str):
        self.sent_audio.append(base64.b64decode(audio_b64))

    async def close(self):
        self.closed = True


class FakeFactory:
    def __init__(self, handle_messages=None):
        self.handle_messages = handle_messages
        self.provider: FakeProvider | None = None

    def create(self, *, on_server_event, is_twilio, **kwargs):
        self.provider = FakeProvider(on_server_event, self.handle_messages)
        return self.provider


class FakeToolManager:
    def register_tools_from_rt_agent_chat_data(self, **kwargs):
        pass

    async def get_realtime_tool_models(self, connection_key):
        return []


class ScriptedTwilio:
    """Twilio's media-stream socket. A script step is a frame dict, a raw string, or an
    async callable run between frames (e.g. a provider event)."""

    def __init__(self, script):
        self.script = script
        self.sent: list[dict] = []
        self.events: list[str] = []

    async def iter_text(self):
        for step in self.script:
            if callable(step):
                await step()
            else:
                yield step if isinstance(step, str) else json.dumps(step)

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self):
        self.events.append("close")


@pytest.fixture
def django(monkeypatch):
    """Django's recording and call-end API; returns the requests it received."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        "application.voice_call_service.httpx.AsyncClient",
        lambda **kwargs: real_async_client(transport=httpx.MockTransport(handler), **kwargs),
    )
    return requests


def _service(twilio, factory=None, **overrides) -> tuple[VoiceCallService, FakeFactory]:
    factory = factory or FakeFactory()
    service = VoiceCallService(
        twilio_ws=twilio,
        realtime_agent_chat_data=_make_chat_data(),
        instructions="You are a helpful assistant",
        tool_manager_service=FakeToolManager(),
        connections={},
        factory=factory,
        django_api_base_url="http://django_app:8000/api",
        django_api_key="test-key",
        initial_message=None,
        **{"max_call_duration_seconds": 10, **overrides},
    )
    return service, factory


def _start(stream_sid="MZ1") -> dict:
    return {"event": "start", "start": {"streamSid": stream_sid}}


def _media(audio: bytes) -> dict:
    return {"event": "media", "media": {"payload": base64.b64encode(audio).decode()}}


def _end_call(requests) -> dict:
    (end,) = [request for request in requests if request.url.path.endswith("/realtime-agent-chats/end/")]
    return json.loads(end.content)


async def test_caller_audio_reaches_the_provider_in_chunks_after_the_stream_starts(django):
    half = MIN_CHUNK_SIZE // 2
    twilio = ScriptedTwilio([_start("MZ123"), _media(b"\x01" * half), _media(b"\x02" * half), _media(b"\x03" * 10)])
    service, factory = _service(twilio)

    await service.execute()

    provider = factory.provider
    assert (provider.stream_sid, provider.stream_starts) == ("MZ123", 1)
    # Audio is batched until MIN_CHUNK_SIZE; the short tail never filled a chunk.
    assert provider.sent_audio == [b"\x01" * half + b"\x02" * half]


@pytest.mark.parametrize(
    ("event", "expected_frames"),
    [
        (
            {"type": "response.audio.delta", "delta": base64.b64encode(b"\xaa\xbb").decode()},
            [{"event": "media", "streamSid": "MZ1", "media": {"payload": base64.b64encode(b"\xaa\xbb").decode()}}],
        ),
        # The caller started talking: stop playing the agent's audio.
        ({"type": "input_audio_buffer.speech_started"}, [{"event": "clear", "streamSid": "MZ1"}]),
        ({"type": "interruption"}, [{"event": "clear", "streamSid": "MZ1"}]),
        ({"type": "unknown_event"}, []),
        ({"type": "error", "error": {"message": "boom"}}, []),
    ],
    ids=["audio", "speech-started", "interruption", "unknown", "provider-error"],
)
async def test_provider_events_are_played_or_cleared_on_the_call(django, event, expected_frames):
    factory = FakeFactory()
    twilio = ScriptedTwilio([_start("MZ1"), lambda: factory.provider.emit(event)])
    service, _ = _service(twilio, factory)

    await service.execute()

    assert twilio.sent == expected_frames


async def test_provider_output_before_the_stream_starts_is_not_sent(django):
    factory = FakeFactory()
    audio = {"type": "response.audio.delta", "delta": base64.b64encode(b"\xaa").decode()}
    twilio = ScriptedTwilio([
        lambda: factory.provider.emit(audio),
        lambda: factory.provider.emit({"type": "interruption"}),
    ])
    service, _ = _service(twilio, factory)

    await service.execute()

    assert twilio.sent == []


async def test_both_recordings_and_the_call_end_are_saved_before_execute_returns(django):
    factory = FakeFactory()
    agent_audio = {"type": "response.audio.delta", "delta": base64.b64encode(b"\x01").decode()}
    twilio = ScriptedTwilio([_start(), _media(b"\x00"), lambda: factory.provider.emit(agent_audio)])
    service, _ = _service(twilio, factory)

    await service.execute()

    assert [request.url.path for request in django] == [
        "/api/conversation-recordings/",
        "/api/conversation-recordings/",
        "/api/realtime-agent-chats/end/",
    ]
    assert _end_call(django)["connection_key"] == "test_key"
    assert _end_call(django)["end_reason"] == "completed"


async def test_call_is_ended_after_the_max_duration(django, monkeypatch):
    """Defense in depth: a leaked stream token cannot meter provider costs forever."""
    import application.voice_call_service as voice_call_service_module

    clock = {"now": 1000.0}
    monkeypatch.setattr(voice_call_service_module.time, "monotonic", lambda: clock["now"])

    async def time_passes():
        clock["now"] += 100

    async def must_not_be_reached():
        raise AssertionError("Twilio frames were read past the max-duration break")

    twilio = ScriptedTwilio([_start(), time_passes, _media(b"\x00"), must_not_be_reached])
    service, factory = _service(twilio)

    await service.execute()

    assert _end_call(django)["end_reason"] == "max_duration_exceeded"
    # We stopped reading ourselves, so the call is hung up actively.
    assert twilio.events == ["close"]
    assert factory.provider.closed


async def test_internal_error_hangs_up_before_saving(django):
    twilio = ScriptedTwilio(["not valid json"])
    service, _ = _service(twilio)
    django_requests_at_close = []
    real_close = twilio.close

    async def close():
        django_requests_at_close.append(len(django))
        await real_close()

    twilio.close = close

    await service.execute()

    assert _end_call(django)["end_reason"] == "error"
    # The caller is not left on a dead line while the recording uploads.
    assert django_requests_at_close == [0]


def _service_with_message_handler(handle_messages, message_handler_started):
    # The stream must not end before the message task has started: a task
    # cancelled before its first step never runs its body at all.
    twilio = ScriptedTwilio([message_handler_started.wait])
    return _service(twilio, FakeFactory(handle_messages))


async def _slow_to_stop(started, stopping):
    started.set()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        stopping.set()
        # execute() is awaiting this task, so cancelling execute() forwards the cancel here.
        await asyncio.Event().wait()
        raise


async def _swallows_cancellation(started, stopping):
    # Mirrors providers whose handle_messages catches CancelledError and returns normally.
    started.set()
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        stopping.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return


@pytest.mark.parametrize("handle_messages", [_slow_to_stop, _swallows_cancellation], ids=["slow-to-stop", "swallows-cancel"])
async def test_cancelling_execute_still_tears_down_saves_and_reraises(django, handle_messages):
    started, stopping = asyncio.Event(), asyncio.Event()
    service, factory = _service_with_message_handler(lambda: handle_messages(started, stopping), started)

    execute_task = asyncio.create_task(service.execute())
    async with asyncio.timeout(5):
        await stopping.wait()
    execute_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        async with asyncio.timeout(5):
            await execute_task
    assert factory.provider.closed
    assert _end_call(django)


async def test_provider_crash_still_tears_down_and_saves(django):
    started = asyncio.Event()

    async def crashes():
        started.set()
        raise RuntimeError("re-provisioning failed")

    service, factory = _service_with_message_handler(crashes, started)

    async with asyncio.timeout(5):
        await service.execute()

    assert factory.provider.closed
    assert _end_call(django)
