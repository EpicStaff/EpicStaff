"""Audio does not reach `realtime_session_item`, whichever handler saves it, unless
`PERSIST_RAW_AUDIO` is turned on.

The sink (`save_realtime_session_item_to_db`) is the single path all six event
handlers take, so these tests drive the real sink and read back what it stores.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from core import config as core_config
from infrastructure.persistence.database import save_realtime_session_item_to_db
from infrastructure.persistence.event_redaction import AUDIO_REDACTED

pytestmark = pytest.mark.asyncio


@pytest.fixture
def stored_items(monkeypatch):
    """Patch the DB session and collect every row the sink adds.

    Pins the default (redaction on) so results never depend on a local `.env`.
    """
    monkeypatch.setattr(core_config, "PERSIST_RAW_AUDIO", False)
    stored: list = []
    session = AsyncMock()
    session.add = MagicMock(side_effect=stored.append)
    session_cm = AsyncMock()
    session_cm.__aenter__.return_value = session
    session_cm.__aexit__.return_value = None
    with patch("infrastructure.persistence.database.SessionLocal", return_value=session_cm):
        yield stored


async def _save(event):
    return await save_realtime_session_item_to_db(data=event, connection_key="key", org_id=1)


@pytest.mark.parametrize(
    "audio_frame",
    [
        {"type": "input_audio_buffer.append", "audio": "QUJD"},
        {"type": "response.audio.delta", "delta": "QUJD", "item_id": "i"},
        {"type": "response.output_audio.delta", "delta": "QUJD"},
        {"audio_event": {"audio_base_64": "QUJD"}, "type": "audio"},
    ],
)
async def test_audio_frame_events_are_not_stored(stored_items, audio_frame):
    assert await _save(audio_frame) is None

    assert stored_items == []


@pytest.mark.parametrize(
    "event",
    [
        # Browser chat (OpenAI client microphone frame) and provider output frames,
        # which Twilio calls also produce.
        {"type": "input_audio_buffer.append", "audio": "QUJD"},
        {"type": "response.audio.delta", "delta": "QUJD", "item_id": "i"},
        {"type": "audio", "audio_event": {"audio_base_64": "QUJD"}},
        {"type": "conversation.item.create", "item": {"content": [{"audio": "QUJD"}]}},
        {"type": "gemini_event", "raw": "Blob(data=b'abc', mime_type='audio/pcm')"},
    ],
)
async def test_raw_audio_is_stored_verbatim_when_persisting_audio_is_enabled(
    stored_items, monkeypatch, event
):
    monkeypatch.setattr(core_config, "PERSIST_RAW_AUDIO", True)

    await _save(event)

    (row,) = stored_items
    assert row.data == event


async def test_user_audio_message_keeps_its_transcript_but_loses_the_audio(stored_items):
    await _save(
        {
            "type": "conversation.item.create",
            "item": {
                "role": "user",
                "content": [{"type": "input_audio", "audio": "QUJD", "transcript": "hi there"}],
            },
        }
    )

    (row,) = stored_items
    content = row.data["item"]["content"][0]
    assert content["audio"] == AUDIO_REDACTED
    assert content["transcript"] == "hi there"


async def test_transcripts_are_still_stored(stored_items):
    event = {
        "type": "conversation.item.input_audio_transcription.completed",
        "transcript": "hello",
    }

    await _save(event)

    (row,) = stored_items
    assert row.data == event


async def test_session_update_audio_config_is_not_mistaken_for_audio(stored_items):
    event = {
        "type": "session.update",
        "session": {"audio": {"input": {"format": {"type": "audio/pcmu"}}}},
    }

    await _save(event)

    (row,) = stored_items
    assert row.data == event


@pytest.mark.parametrize(
    "audio_bytes",
    [
        b"\x00\x01plain",
        b"it's got a quote and a \\ backslash",
        b"""both ' and " quotes""",
    ],
)
async def test_gemini_sdk_message_audio_is_redacted_and_transcript_kept(stored_items, audio_bytes):
    # Built with the real SDK so the stored repr is exactly what the handler saves.
    message = types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(
                parts=[
                    types.Part(inline_data=types.Blob(data=audio_bytes, mime_type="audio/pcm"))
                ]
            ),
            output_transcription=types.Transcription(text="hello"),
        )
    )

    await _save({"type": "gemini_event", "raw": str(message)})

    (row,) = stored_items
    stored_raw = row.data["raw"]
    assert f"data={AUDIO_REDACTED}, mime_type='audio/pcm'" in stored_raw
    assert repr(audio_bytes) not in stored_raw
    assert "text='hello'" in stored_raw


async def test_unterminated_backslash_run_does_not_stall_the_redactor(stored_items):
    hostile = 'data=b"' + "\\" * 5000 + "x"

    started = time.perf_counter()
    await _save({"type": "gemini_event", "raw": hostile})
    await _save({"type": "conversation.item.create", "item": {"text": hostile}})

    assert time.perf_counter() - started < 1.0


async def test_text_that_looks_like_a_bytes_literal_is_kept_outside_gemini_events(stored_items):
    event = {"type": "conversation.item.create", "item": {"text": "data=b'hello' is a literal"}}

    await _save(event)

    (row,) = stored_items
    assert row.data == event


async def test_redaction_does_not_mutate_the_event_still_being_forwarded(stored_items):
    event = {"type": "conversation.item.create", "item": {"content": [{"audio": "QUJD"}]}}

    await _save(event)

    assert event["item"]["content"][0]["audio"] == "QUJD"


async def test_openai_client_handler_stores_no_microphone_audio(stored_items):
    from infrastructure.providers.openai.event_handlers.agent_client_event_handler import (
        ClientEventHandler,
    )

    client = MagicMock(connection_key="key", org_id=1, user_id=None)
    client.send_server = AsyncMock()
    handler = ClientEventHandler(client)

    await handler.handle_event({"type": "input_audio_buffer.append", "audio": "QUJD"})
    await handler.handle_event({"type": "input_audio_buffer.commit"})

    client.send_server.assert_any_await({"type": "input_audio_buffer.append", "audio": "QUJD"})
    assert [row.data["type"] for row in stored_items] == ["input_audio_buffer.commit"]
