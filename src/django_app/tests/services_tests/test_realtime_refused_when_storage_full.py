"""A realtime chat that needs storage is refused while its organization is over its quota.

POST /api/init-realtime/ answers 409 `organization_storage_full` when the agent's surface
grants a storage tool and the organization is over its storage quota. The chat row created
for the attempt is deleted and nothing is handed to the realtime service. A chat whose
surface grants no storage tool is not affected by the quota.

Real view, realtime service, converter and credential service; Redis (`redis_client_mock`)
and the storage backend's admin API (FakeStorageGateway) are the external boundaries.
"""

import pytest

from agents.models import AgentDefaultSurface, AgentDefinition, Surface, SurfacePlace
from agents.models.surface_models import SurfacePythonTool, SurfaceStorageItem, ToolMode
from tables.models import PythonCode, PythonCodeTool, RealtimeAgentChat, StorageFile
from tables.models.realtime_models import RealtimeAgentDefinition
from tests.services_tests.test_run_code_storage_credentials import gateway  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/init-realtime/"
QUOTA = 1000


@pytest.fixture(autouse=True)
def small_quota(settings):
    settings.ORG_STORAGE_QUOTA = QUOTA


@pytest.fixture
def surface(default_org):
    return Surface.objects.create(org=default_org, name="storage-full-voice-surface")


@pytest.fixture
def voice_agent(default_org, llm_config, openai_realtime_provider_config, surface):
    agent_definition = AgentDefinition.objects.create(
        org=default_org,
        name="storage-full-voice-agent",
        instruction_list=[{"name": "Instruction_1.md", "content": "Be brief"}],
        llm_config=llm_config,
    )
    RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition, openai_config=openai_realtime_provider_config
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent_definition, surface=surface, place=SurfacePlace.REALTIME
    )
    return agent_definition


def _grant_tool(surface, *, use_storage: bool) -> None:
    tool = PythonCodeTool.objects.create(
        name="voice-tool",
        description="",
        use_storage=use_storage,
        python_code=PythonCode.objects.create(code="def main(**kw): return kw"),
    )
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)


@pytest.fixture
def over_quota(default_org, surface):
    granted = StorageFile.objects.create(
        org=default_org, path="notes.txt", name="notes.txt", item_type="file", size=QUOTA + 1
    )
    SurfaceStorageItem.objects.create(surface=surface, storage_file=granted, can_view="allow")


def test_a_chat_with_a_storage_tool_over_quota_is_refused_and_its_row_deleted(
    gateway, voice_agent, surface, over_quota, auth_client, redis_client_mock  # noqa: F811
):
    _grant_tool(surface, use_storage=True)

    response = auth_client.post(URL, {"agent_definition_id": voice_agent.pk}, format="json")

    assert response.status_code == 409, response.content
    body = response.json()
    assert (body["status_code"], body["code"]) == (409, "organization_storage_full")
    assert not RealtimeAgentChat.objects.exists()
    redis_client_mock.publish.assert_not_called()
    assert gateway.created == []


def test_a_chat_with_a_storage_tool_at_the_quota_gets_its_credentials(
    gateway, voice_agent, surface, default_org, auth_client, redis_client_mock  # noqa: F811
):
    granted = StorageFile.objects.create(
        org=default_org, path="notes.txt", name="notes.txt", item_type="file", size=QUOTA
    )
    SurfaceStorageItem.objects.create(surface=surface, storage_file=granted, can_view="allow")
    _grant_tool(surface, use_storage=True)

    response = auth_client.post(URL, {"agent_definition_id": voice_agent.pk}, format="json")

    assert response.status_code == 201, response.content
    assert len(gateway.created) == 1
    redis_client_mock.publish.assert_called_once()


def test_a_chat_without_a_storage_tool_starts_over_quota(
    gateway, voice_agent, surface, over_quota, auth_client, redis_client_mock  # noqa: F811
):
    _grant_tool(surface, use_storage=False)

    response = auth_client.post(URL, {"agent_definition_id": voice_agent.pk}, format="json")

    assert response.status_code == 201, response.content
    assert RealtimeAgentChat.objects.filter(
        connection_key=response.json()["connection_key"]
    ).exists()
    redis_client_mock.publish.assert_called_once()
    assert gateway.created == []
