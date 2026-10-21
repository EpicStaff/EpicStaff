"""
`RealtimeAgentChatData.rt_base_url` lets a realtime session point at
a local/self-hosted or proxy OpenAI-compatible endpoint instead of the
hardcoded `api.openai.com` host. It is populated from the active
`OpenAIRealtimeConfig.base_url` at conversion time.

`convert_rt_agent_chat_to_pydantic` (staff `RealtimeAgent`) was removed
along with the `RealtimeAgent` conversion path (`AgentDefinition` is used
instead) -- `convert_rt_agent_definition_chat_to_pydantic`
(`RealtimeAgentDefinition`) is the sole surviving build site, covered below
(mirroring `test_converter_rt_agent_chat_org_id.py`).
"""

import pytest

from agents.models import AgentDefinition, DefaultAgentDefinitionConfig
from tables.models.realtime_models import (
    OpenAIRealtimeConfig,
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
def test_convert_rt_agent_definition_chat_to_pydantic_populates_rt_base_url(
    converter, default_org, llm_config, regular_user
):
    agent_definition = AgentDefinition.objects.create(
        org=default_org,
        name="voice-agent",
        description="Helps with voice tasks",
        instruction_list=[{"name": "Instruction_1.md", "content": "Be concise and helpful"}],
        llm_config=llm_config,
    )
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg-def",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        base_url="https://my-proxy.internal",
        api_key_secret=_api_key_secret(default_org, "openai-cfg-def-api-key"),
        # A custom base_url receives the key only with an approver holding secrets:USE.
        secret_binding_approved_by=regular_user,
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
        org=default_org,
        name="voice-agent-no-override",
        description="Helps with voice tasks",
        instruction_list=[{"name": "Instruction_1.md", "content": "Be concise and helpful"}],
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


@pytest.mark.django_db
def test_convert_rt_agent_definition_chat_to_pydantic_carries_rt_agent_definition_id(
    converter, default_org, llm_config
):
    # The realtime service names the remote ElevenLabs agent after this id, so two
    # configurations must reach it with different ids.
    agent_definition = AgentDefinition.objects.create(
        org=default_org,
        name="voice-agent-id",
        description="Helps with voice tasks",
        instruction_list=[{"name": "Instruction_1.md", "content": "Be concise and helpful"}],
        llm_config=llm_config,
    )
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg-def-id",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        api_key_secret=_api_key_secret(default_org, "openai-cfg-def-id-api-key"),
    )
    rt_agent_definition = RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition, openai_config=config
    )
    chat = RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_agent_definition,
        connection_key="conn-def-id",
        openai_config=config,
    )

    data = converter.convert_rt_agent_definition_chat_to_pydantic(chat)

    assert data.rt_agent_definition_id == rt_agent_definition.pk


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("has_llm_config", "llm_config_temperature", "agent_temperature", "expected_temperature"),
    [
        (True, 0.3, 1.2, 0.3),
        (True, 0.0, 1.2, 0.0),
        (True, None, 1.2, 1.2),
        (False, None, 1.2, 1.2),
        (True, None, None, 0.4),
    ],
    ids=[
        "llm-config",
        "llm-config-zero",
        "llm-config-unset",
        "no-llm-config",
        "nothing-set-uses-system-default",
    ],
)
def test_convert_rt_agent_definition_chat_to_pydantic_takes_temperature_from_llm_config(
    converter,
    default_org,
    llm_config,
    has_llm_config,
    llm_config_temperature,
    agent_temperature,
    expected_temperature,
):
    DefaultAgentDefinitionConfig.objects.update_or_create(
        pk=1, defaults={"default_temperature": 0.4}
    )
    if has_llm_config:
        llm_config.temperature = llm_config_temperature
        llm_config.save()
    agent_definition = AgentDefinition.objects.create(
        org=default_org,
        name="voice-agent-temperature",
        instruction_list=[{"name": "Instruction_1.md", "content": "Be concise and helpful"}],
        llm_config=llm_config if has_llm_config else None,
        default_temperature=agent_temperature,
    )
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg-def-temperature",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        api_key_secret=_api_key_secret(default_org, "openai-cfg-def-temperature-api-key"),
    )
    chat = RealtimeAgentChat.objects.create(
        rt_agent_definition=RealtimeAgentDefinition.objects.create(
            agent_definition=agent_definition, openai_config=config
        ),
        connection_key="conn-def-temperature",
        openai_config=config,
    )

    data = converter.convert_rt_agent_definition_chat_to_pydantic(chat)

    assert data.temperature == expected_temperature
