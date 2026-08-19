"""
Code review fix (branch feature/EST-1869-voice-settings): `rt_provider` /
`rt_model_name` / `rt_api_key` are nullable on `RealtimeAgentChat` (the
`openai_config` / `elevenlabs_config` / `gemini_config` FKs are all
`on_delete=SET_NULL`), but `RealtimeAgentChatData` (src/shared/models/agents.py)
requires `rt_model_name`/`rt_api_key` as non-optional `str`. If the referenced
provider config row is deleted after a `RealtimeAgentChat` snapshot was
created (SET_NULL fires), `convert_rt_agent_chat_to_pydantic` used to let an
opaque pydantic `ValidationError` surface. It now raises a clear
`django.core.exceptions.ValidationError` before constructing the pydantic
object, so the caller (`RealtimeService.init_realtime` -> `InitRealtimeAPIView`)
gets a predictable, readable 400 instead.
"""

import pytest
from django.core.exceptions import ValidationError

from tables.models.realtime_models import (
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
)
from tables.services.converter_service import ConverterService
from tests.fixtures import *  # noqa: F401,F403 — wikipedia_agent, default_org, etc.


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


@pytest.mark.django_db
def test_convert_rt_agent_chat_to_pydantic_succeeds_on_fresh_data(
    converter, wikipedia_agent, default_org
):
    """Baseline: a normal, freshly created chat with its provider config
    intact converts without raising and carries the real model/key through."""
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        api_key="sk-test-key",
    )
    rt_agent = RealtimeAgent.objects.create(agent=wikipedia_agent, openai_config=config)
    chat = RealtimeAgentChat.objects.create(
        rt_agent=rt_agent, connection_key="conn-fresh", openai_config=config
    )

    data = converter.convert_rt_agent_chat_to_pydantic(chat)

    assert data.rt_provider == "openai"
    assert data.rt_model_name == "gpt-4o-realtime-preview"
    assert data.rt_api_key == "sk-test-key"


@pytest.mark.django_db
def test_convert_rt_agent_chat_to_pydantic_raises_clear_error_when_config_set_null(
    converter, wikipedia_agent, default_org
):
    """Regression guard for the fix: when the provider config referenced by
    the chat snapshot is deleted, Django's SET_NULL nulls out
    openai_config_id on the RealtimeAgentChat row. Converting that chat must
    raise a clear, predictable ValidationError instead of an opaque pydantic
    ValidationError bubbling up from RealtimeAgentChatData construction."""
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg-to-delete",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        api_key="sk-test-key",
    )
    rt_agent = RealtimeAgent.objects.create(agent=wikipedia_agent, openai_config=config)
    chat = RealtimeAgentChat.objects.create(
        rt_agent=rt_agent, connection_key="conn-set-null", openai_config=config
    )

    # Simulate the referenced provider config being deleted after the chat
    # snapshot was created — SET_NULL fires on the chat's FK.
    config.delete()
    chat.refresh_from_db()
    assert chat.openai_config_id is None

    with pytest.raises(ValidationError):
        converter.convert_rt_agent_chat_to_pydantic(chat)
