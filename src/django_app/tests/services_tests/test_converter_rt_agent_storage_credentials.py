"""Temporary storage credentials for a realtime (voice) chat.

Converting a realtime chat for the realtime service mints one service account for
the whole chat when the agent's surface grants a storage tool, and none otherwise.
The surface is built for real; only the storage backend's admin API is faked.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agents.models import AgentDefinition, Surface
from agents.models.agent_models import AgentDefaultSurface, SurfacePlace
from agents.models.surface_models import SurfacePythonTool, SurfaceStorageItem, ToolMode
from rbac.models import Organization
from storage_credentials.models import TemporaryStorageAccount
from tables.models import OpenAIRealtimeConfig, PythonCode, PythonCodeTool, RealtimeAgentChat, RealtimeAgentDefinition, Secret
from tables.models.graph_models import StorageFile
from tables.services.converter_service import ConverterService

from .test_run_code_storage_credentials import GATEWAY_PATH, ORG_CREDENTIALS_PATH, FakeStorageGateway


@pytest.fixture
def gateway():
    fake = FakeStorageGateway()
    with (
        patch(GATEWAY_PATH, fake),
        patch(ORG_CREDENTIALS_PATH, return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret")),
    ):
        yield fake


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org RealtimeStorage")


@pytest.fixture
def surface(org):
    return Surface.objects.create(org=org, name="voice-surface", instructions="")


@pytest.fixture
def chat(org, surface):
    agent_definition = AgentDefinition.objects.create(
        name="Voice Agent", org_id=org.id,
        instruction_list=[{"name": "Instruction_1.md", "content": "You are a helpful assistant"}],
    )
    AgentDefaultSurface.objects.create(agent_definition=agent_definition, surface=surface, place=SurfacePlace.REALTIME)
    openai_config = OpenAIRealtimeConfig.objects.create(
        custom_name="openai_test", model_name="gpt-4-realtime-preview",
        api_key_secret=Secret.objects.create(name="openai_api_key", value="encrypted_key", org=org), org=org,
    )
    return RealtimeAgentChat.objects.create(
        rt_agent_definition=RealtimeAgentDefinition.objects.create(agent_definition=agent_definition),
        openai_config=openai_config,
        connection_key="conn-key-123",
    )


def _allow_tools(surface, *uses_storage: bool) -> None:
    for index, use_storage in enumerate(uses_storage):
        tool = PythonCodeTool.objects.create(
            name=f"tool-{index}", description="", use_storage=use_storage,
            python_code=PythonCode.objects.create(code="def main(**kw): return kw"),
        )
        SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("tools", "minted"),
    [((), False), ((False,), False), ((True,), True), ((True, True), True), ((True, False), True)],
    ids=["no-tools", "plain-tool", "storage-tool", "two-storage-tools", "storage-and-plain-tool"],
)
def test_one_account_per_chat_only_when_a_storage_tool_is_granted(gateway, org, surface, chat, tools, minted):
    _allow_tools(surface, *tools)
    grant = StorageFile.objects.create(org=org, name="report.txt", path="reports/report.txt")
    SurfaceStorageItem.objects.create(surface=surface, storage_file=grant, can_view="allow")

    chat_data = ConverterService().convert_rt_agent_definition_chat_to_pydantic(chat)

    accounts = TemporaryStorageAccount.objects.filter(realtime_agent_chat=chat)
    if not minted:
        assert chat_data.storage_credentials is None
        assert gateway.created == [] and not accounts.exists()
        return
    assert (chat_data.storage_credentials.access_key, chat_data.storage_credentials.secret_key) == (
        "temp-access-1", "temp-secret-1",
    )
    assert list(accounts.values_list("access_key", flat=True)) == ["temp-access-1"]
    (account,) = gateway.created
    # Scoped to what the surface grants, under the org's own prefix.
    assert f"/org_{org.id}/reports/report.txt" in json.dumps(account["policy"])
