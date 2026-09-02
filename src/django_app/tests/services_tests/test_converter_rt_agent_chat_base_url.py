"""
`RealtimeAgentChatData.rt_base_url` lets a realtime session point at
a local/self-hosted or proxy OpenAI-compatible endpoint instead of the
hardcoded `api.openai.com` host. It is populated from the active
`OpenAIRealtimeConfig.base_url` at conversion time.

There are two independent build sites for `RealtimeAgentChatData` —
`convert_rt_agent_chat_to_pydantic` (staff `RealtimeAgent`) and
`convert_rt_agent_definition_chat_to_pydantic` (`RealtimeAgentDefinition`).
Missing either one silently breaks one agent kind while leaving the other
working, so both are covered here (mirroring
`test_converter_rt_agent_chat_org_id.py`).
"""

import pytest

from agents.models import AgentDefinition
from tables.models.realtime_models import (
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
)
from tables.models.secret_models import Secret
from tables.services.converter_service import ConverterService
from tables.services.secrets import secret_encryption
from tests.fixtures import *  # noqa: F401,F403 — wikipedia_agent, default_org, etc.


@pytest.fixture
def converter() -> ConverterService:
    return ConverterService()


def _api_key_secret(org, name: str, text: str = "sk-test-key") -> Secret:
    secret = Secret(org=org, name=name)
    secret_encryption.encrypt(text=text).write_to(secret)
    secret.save()
    return secret


@pytest.mark.django_db
def test_convert_rt_agent_chat_to_pydantic_populates_rt_base_url(
    converter, wikipedia_agent, default_org
):
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        base_url="https://my-proxy.internal",
        api_key_secret=_api_key_secret(default_org, "openai-cfg-api-key"),
    )
    rt_agent = RealtimeAgent.objects.create(agent=wikipedia_agent, openai_config=config)
    chat = RealtimeAgentChat.objects.create(
        rt_agent=rt_agent, connection_key="conn-base-url", openai_config=config
    )

    data = converter.convert_rt_agent_chat_to_pydantic(chat)

    assert data.rt_base_url == "https://my-proxy.internal"


@pytest.mark.django_db
def test_convert_rt_agent_chat_to_pydantic_defaults_rt_base_url_to_none(
    converter, wikipedia_agent, default_org
):
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg-no-override",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        api_key_secret=_api_key_secret(default_org, "openai-cfg-no-override-key"),
    )
    rt_agent = RealtimeAgent.objects.create(agent=wikipedia_agent, openai_config=config)
    chat = RealtimeAgentChat.objects.create(
        rt_agent=rt_agent, connection_key="conn-base-url-default", openai_config=config
    )

    data = converter.convert_rt_agent_chat_to_pydantic(chat)

    assert data.rt_base_url is None


@pytest.mark.django_db
def test_convert_rt_agent_definition_chat_to_pydantic_populates_rt_base_url(
    converter, default_org, llm_config
):
    agent_definition = AgentDefinition.objects.create(
        organization=default_org,
        name="voice-agent",
        description="Helps with voice tasks",
        instructions="Be concise and helpful",
        llm_config=llm_config,
    )
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg-def",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        base_url="https://my-proxy.internal",
        api_key_secret=_api_key_secret(default_org, "openai-cfg-def-api-key"),
    )
    rt_agent_definition = RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition, openai_config=config
    )
    chat = RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_agent_definition,
        connection_key="conn-base-url-def",
        openai_config=config,
    )

    data = converter.convert_rt_agent_definition_chat_to_pydantic(chat)

    assert data.rt_base_url == "https://my-proxy.internal"


@pytest.mark.django_db
def test_convert_rt_agent_definition_chat_to_pydantic_defaults_rt_base_url_to_none(
    converter, default_org, llm_config
):
    agent_definition = AgentDefinition.objects.create(
        organization=default_org,
        name="voice-agent-no-override",
        description="Helps with voice tasks",
        instructions="Be concise and helpful",
        llm_config=llm_config,
    )
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg-def-no-override",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        api_key_secret=_api_key_secret(default_org, "openai-cfg-def-no-override-key"),
    )
    rt_agent_definition = RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition, openai_config=config
    )
    chat = RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_agent_definition,
        connection_key="conn-base-url-def-default",
        openai_config=config,
    )

    data = converter.convert_rt_agent_definition_chat_to_pydantic(chat)

    assert data.rt_base_url is None
