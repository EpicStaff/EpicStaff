"""GeminiServerEventHandler translates Gemini Live messages into the OpenAI-shaped
events the frontend understands, and records them.

Messages are real `google.genai` SDK objects. The client is a stand-in recording what
the handler sends; the DB write is the recorded side effect, so it is mocked.
"""

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from google.genai import types

from core import config
from infrastructure.providers.gemini.event_handlers.gemini_server_event_handler import (
    GeminiServerEventHandler,
)

pytestmark = pytest.mark.asyncio

_DB_PATCH = "infrastructure.providers.gemini.event_handlers.gemini_server_event_handler.save_realtime_session_item_to_db"


@pytest.fixture
def db_write():
    with patch(_DB_PATCH, new_callable=AsyncMock) as write:
        yield write


@pytest.fixture
def client():
    sent: list[dict] = []

    async def send_client(payload):
        sent.append(payload)

    return SimpleNamespace(
        connection_key="conn_test",
        org_id=77,
        user_id=5,
        is_twilio=False,
        sent=sent,
        send_client=send_client,
        call_tool=AsyncMock(),
        _resample_state_out=None,
    )


@pytest.fixture
def handler(client, db_write):
    return GeminiServerEventHandler(client)


def _types(client) -> list[str]:
    return [event["type"] for event in client.sent]


def _audio(data: bytes = b"\x01\x02" * 50) -> types.LiveServerMessage:
    return types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(
                parts=[types.Part(inline_data=types.Blob(data=data, mime_type="audio/pcm;rate=24000"))]
            )
        )
    )


def _content(**fields) -> types.LiveServerMessage:
    return types.LiveServerMessage(server_content=types.LiveServerContent(**fields))


def _output_transcript(text: str) -> types.LiveServerMessage:
    return _content(output_transcription=types.Transcription(text=text))


async def test_setup_complete_announces_the_session(handler, client):
    await handler.handle_event(types.LiveServerMessage(setup_complete=types.LiveServerSetupComplete()))

    (event,) = client.sent
    assert event["type"] == "session.created"
    assert event["session"]["provider"] == "gemini"


@pytest.mark.parametrize(
    ("is_twilio", "pcm_24k", "expected_audio"),
    [
        (False, b"\x01\x02" * 50, b"\x01\x02" * 50),
        # Twilio plays µ-law 8 kHz: 240 silent 24 kHz samples become 80 µ-law silence bytes.
        (True, b"\x00\x00" * 240, b"\xff" * 80),
    ],
    ids=["browser-pcm-as-is", "twilio-ulaw-8k"],
)
async def test_model_audio_is_forwarded_in_the_callers_format(handler, client, is_twilio, pcm_24k, expected_audio):
    client.is_twilio = is_twilio

    await handler.handle_event(_audio(pcm_24k))

    (delta,) = [event for event in client.sent if event["type"] == "response.audio.delta"]
    assert base64.b64decode(delta["delta"]) == expected_audio


async def test_a_spoken_turn_opens_streams_and_completes_a_response(handler, client):
    for message in (_audio(), _output_transcript("Hello "), _output_transcript("world"), _content(turn_complete=True)):
        await handler.handle_event(message)

    assert _types(client) == [
        "conversation.item.created",  # the user's (audio) turn
        "response.created",
        "response.output_item.added",
        "conversation.item.created",  # the assistant's item
        "response.audio.delta",
        "response.audio_transcript.delta",
        "response.audio_transcript.delta",
        "response.audio_transcript.done",
        "response.audio.done",
        "response.output_item.done",
        "response.done",
    ]
    response_ids = {event.get("response_id") or event.get("response", {}).get("id") for event in client.sent[1:]}
    assert len(response_ids - {None}) == 1
    assert client.sent[7]["transcript"] == "Hello world"


async def _response_id_of_next_audio(handler, client) -> str:
    client.sent.clear()
    await handler.handle_event(_audio())
    (created,) = [event for event in client.sent if event["type"] == "response.created"]
    return created["response"]["id"]


@pytest.mark.parametrize(
    "end_turn",
    [
        lambda handler: handler.handle_event(_content(turn_complete=True)),
        lambda handler: handler.handle_event(_content(interrupted=True)),
        lambda handler: asyncio.sleep(0, handler.reset()),
    ],
    ids=["turn-complete", "interrupted", "reset-on-reconnect"],
)
async def test_audio_after_a_turn_ends_starts_a_new_response(handler, client, end_turn):
    first = await _response_id_of_next_audio(handler, client)
    await end_turn(handler)

    assert await _response_id_of_next_audio(handler, client) != first


async def test_interruption_stops_playback_and_cancels_the_response(handler, client):
    await handler.handle_event(_audio())
    (created,) = [event for event in client.sent if event["type"] == "response.created"]
    client.sent.clear()

    await handler.handle_event(_content(interrupted=True))

    assert client.sent[0]["type"] == "input_audio_buffer.speech_started"
    assert client.sent[1]["type"] == "response.cancelled"
    assert client.sent[1]["response"]["id"] == created["response"]["id"]


async def test_after_a_client_cancel_audio_is_dropped_until_gemini_confirms(handler, client):
    await handler.handle_event(_audio())
    await handler.handle_client_cancel()
    client.sent.clear()

    await handler.handle_event(_audio())
    assert "response.audio.delta" not in _types(client)

    await handler.handle_event(_content(interrupted=True))
    await handler.handle_event(_audio())
    assert "response.audio.delta" in _types(client)


async def test_user_speech_transcript_is_shown(handler, client):
    await handler.handle_event(_content(input_transcription=types.Transcription(text="user said this")))

    assert _types(client) == ["conversation.item.created", "conversation.item.input_audio_transcription.completed"]
    assert client.sent[1]["transcript"] == "user said this"


async def test_tool_call_is_announced_and_runs_without_blocking_the_handler(handler, client):
    started, release = asyncio.Event(), asyncio.Event()

    async def slow_tool(call_id, name, args):
        started.set()
        await release.wait()

    client.call_tool = slow_tool
    message = types.LiveServerMessage(
        tool_call=types.LiveServerToolCall(function_calls=[types.FunctionCall(id="c1", name="my_tool", args={"x": 1})])
    )

    async with asyncio.timeout(1):
        await handler.handle_event(message)
        await started.wait()

    done = next(event for event in client.sent if event["type"] == "response.function_call_arguments.done")
    assert (done["call_id"], done["name"], done["arguments"]) == ("c1", "my_tool", '{"x": 1}')
    release.set()


def _audio_part(**part_fields):
    return types.Part(inline_data=types.Blob(data=b"\x00\x01" * 8, mime_type="audio/pcm;rate=24000"), **part_fields)


def _sdk_message(*, audio: bool = True, parts: list | None = None, transcript: str | None = None, **server_content_fields):
    if parts is None and audio:
        parts = [_audio_part()]
    return types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(parts=parts) if parts else None,
            output_transcription=types.Transcription(text=transcript) if transcript else None,
            **server_content_fields,
        )
    )


@pytest.mark.parametrize(
    ("message", "persist_raw_audio", "recorded"),
    [
        # Nothing is left of an audio-only message once its audio is redacted.
        pytest.param(_sdk_message(), False, False, id="audio-only"),
        pytest.param(
            types.LiveServerMessage(server_content=types.LiveServerContent(
                model_turn=types.Content(role="model", parts=[_audio_part(), _audio_part()])
            )),
            False, False, id="several-audio-chunks",
        ),
        pytest.param(_sdk_message(), True, True, id="audio-only-with-raw-audio-persistence"),
        pytest.param(_sdk_message(transcript="hello"), False, True, id="audio-with-transcript"),
        pytest.param(_sdk_message(audio=False, turn_complete=True), False, True, id="turn-complete"),
        pytest.param(_sdk_message(generation_complete=True), False, True, id="generation-complete"),
        pytest.param(
            _sdk_message(grounding_metadata=types.GroundingMetadata(web_search_queries=["weather"])),
            False, True, id="grounding-metadata",
        ),
        pytest.param(_sdk_message(input_transcription=types.Transcription(text="hi")), False, True, id="input-transcription"),
        pytest.param(
            types.LiveServerMessage(
                server_content=_sdk_message().server_content, usage_metadata=types.UsageMetadata(total_token_count=5)
            ),
            False, True, id="usage-metadata",
        ),
        pytest.param(_sdk_message(parts=[_audio_part(thought=True)]), False, True, id="thought-audio-part"),
        pytest.param(
            _sdk_message(parts=[types.Part(inline_data=types.Blob(data=b"x", mime_type="image/png"))]),
            False, True, id="image-inline-data",
        ),
        pytest.param(_sdk_message(parts=[_audio_part(), types.Part(text="hi")]), False, True, id="audio-and-text"),
        # An explicit falsy value still counts as set: the check never interprets fields.
        pytest.param(_sdk_message(turn_complete=False), False, True, id="explicit-turn-complete-false"),
    ],
)
async def test_only_audio_only_messages_are_left_out_of_the_session_record(
    handler, db_write, monkeypatch, message, persist_raw_audio, recorded
):
    monkeypatch.setattr(config, "PERSIST_RAW_AUDIO", persist_raw_audio)

    await handler.handle_event(message)

    assert db_write.await_count == int(recorded)
    if recorded:
        kwargs = db_write.await_args.kwargs
        assert (kwargs["connection_key"], kwargs["org_id"], kwargs["user_id"]) == ("conn_test", 77, 5)
