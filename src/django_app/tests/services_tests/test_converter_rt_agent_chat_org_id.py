"""
EST-1869 security fix: `RealtimeAgentChatData.org_id` binds a realtime session
to the org that owns it, so the `realtime` service can reject a WS connect
attempt made with a valid user token that does not belong to that org (see
`src/realtime/api/main.py`'s `root()` handler). Before this fix, the payload
carried no ownership data at all — a leaked/guessed `connection_key` let
anyone drive another org's live realtime session.

These tests confirm `org_id` is populated correctly from the *authoritative*
source for each conversion path:
- `convert_rt_agent_chat_to_pydantic` -> `Agent.org_id` (via `RealtimeAgent.agent`)
- `convert_rt_agent_definition_chat_to_pydantic` -> `AgentDefinition.organization_id`
  (via `RealtimeAgentDefinition.agent_definition`)
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
def test_convert_rt_agent_chat_to_pydantic_populates_org_id_from_agent(
    converter, wikipedia_agent, default_org
):
    config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai-cfg",
        org=default_org,
        model_name="gpt-4o-realtime-preview",
        api_key_secret=_api_key_secret(default_org, "openai-cfg-api-key"),
    )
    rt_agent = RealtimeAgent.objects.create(agent=wikipedia_agent, openai_config=config)
    chat = RealtimeAgentChat.objects.create(
        rt_agent=rt_agent, connection_key="conn-org-id", openai_config=config
    )

    data = converter.convert_rt_agent_chat_to_pydantic(chat)

    assert data.org_id == default_org.pk
    assert data.org_id == wikipedia_agent.org_id


@pytest.mark.django_db
def test_convert_rt_agent_definition_chat_to_pydantic_populates_org_id_from_definition(
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
        api_key_secret=_api_key_secret(default_org, "openai-cfg-def-api-key"),
    )
    rt_agent_definition = RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition, openai_config=config
    )
    chat = RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_agent_definition,
        connection_key="conn-org-id-def",
        openai_config=config,
    )

    data = converter.convert_rt_agent_definition_chat_to_pydantic(chat)

    assert data.org_id == default_org.pk
    assert data.org_id == agent_definition.organization_id
