"""Unit tests for RealtimeService's config-override whitelist.

Follow-up to the org_id fail-closed guard investigation: the
`config` dict (from `InitRealtimeSerializer.config`, a bare `DictField`) used
to be `setattr`'d onto the already pydantic-validated `RealtimeAgentChatData`
for ANY key matching a field name via `hasattr` -- with zero type/value
checking, bypassing pydantic entirely. These tests pin down the fixed
`_apply_config_overrides` behavior: only the whitelisted audio-format keys
are applied; anything else (including sensitive fields like `org_id` or
`rt_api_key`) is ignored rather than silently overwritten.
"""

from src.shared.models import RealtimeAgentChatData
from tables.services.realtime_service import (
    _ALLOWED_CONFIG_OVERRIDE_KEYS,
    _apply_config_overrides,
)


def _make_chat_data(**overrides) -> RealtimeAgentChatData:
    """Minimal valid RealtimeAgentChatData for override testing."""
    defaults = dict(
        role="assistant",
        goal="assist user",
        backstory="helpful assistant",
        org_id=1,
        knowledge_collection_id=None,
        llm=None,
        rt_model_name="test-model",
        temperature=0.5,
        memory=True,
        connection_key="conn-key-1",
        wake_word="wake",
        stop_prompt="stop",
        language="en",
        voice_recognition_prompt="say something",
        voice="voice1",
        input_audio_format="pcm16",
        output_audio_format="pcm16",
    )
    defaults.update(overrides)
    return RealtimeAgentChatData(**defaults)


def test_whitelist_contains_exactly_the_known_legitimate_keys():
    """Pin the exact whitelist to the keys real callers actually send --
    changing this set should be a deliberate, reviewed decision.

    - `input_audio_format` / `output_audio_format`: the Twilio bridge's
      `_voice_stream_handler` (`src/realtime/api/main.py`).
    - `rt_api_key_secret_id`: browser/JWT override of the realtime API key's
      Secret row, org-scoped by `SecretResolver` at publish time (see
      test_init_realtime_cross_org_secret.py) -- not a plain overwrite.
    """
    assert _ALLOWED_CONFIG_OVERRIDE_KEYS == {
        "input_audio_format",
        "output_audio_format",
        "rt_api_key_secret_id",
    }


def test_whitelisted_audio_format_keys_are_applied():
    data = _make_chat_data(input_audio_format="pcm16", output_audio_format="pcm16")

    _apply_config_overrides(
        data, {"input_audio_format": "g711_ulaw", "output_audio_format": "g711_ulaw"}
    )

    assert data.input_audio_format == "g711_ulaw"
    assert data.output_audio_format == "g711_ulaw"


def test_non_whitelisted_key_is_ignored_not_applied():
    """The exact regression this closes: a client-controlled config key
    matching a sensitive field name must not silently overwrite it."""
    data = _make_chat_data(org_id=1)

    _apply_config_overrides(data, {"org_id": 999})

    assert data.org_id == 1


def test_non_whitelisted_secret_field_is_ignored():
    data = _make_chat_data()
    original_api_key = data.rt_api_key

    _apply_config_overrides(data, {"rt_api_key": "attacker-supplied-key"})

    assert data.rt_api_key == original_api_key


def test_empty_config_is_a_no_op():
    data = _make_chat_data()
    before = data.model_copy(deep=True)

    _apply_config_overrides(data, {})

    assert data == before


def test_mixed_whitelisted_and_non_whitelisted_keys():
    """A payload combining a legitimate override with a non-whitelisted key
    must apply only the legitimate one."""
    data = _make_chat_data(input_audio_format="pcm16")

    _apply_config_overrides(
        data, {"input_audio_format": "g711_ulaw", "org_id": 999, "tools": ["x"]}
    )

    assert data.input_audio_format == "g711_ulaw"
    assert data.org_id == 1
    assert data.tools == []
