"""Two realtime configurations must never share one remote ElevenLabs agent.

`FakeElevenLabs` is a stateful stand-in for the ElevenLabs convai API (list / create /
patch for agents and tools), so each test provisions through the real provisioner and
then reads the remote agents back.
"""

import asyncio
import functools
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

from domain.models.realtime_tool import RealtimeTool, ToolParameters
from infrastructure.providers.elevenlabs import elevenlabs_agent_provisioner as provisioner_module
from infrastructure.providers.elevenlabs.elevenlabs_agent_provisioner import (
    ElevenLabsAgentProvisioner,
    remote_agent_name,
)
from infrastructure.providers.elevenlabs.elevenlabs_realtime_agent_client import (
    ElevenLabsRealtimeAgentClient,
)
from utils.singleton_meta import SingletonMeta

pytestmark = pytest.mark.asyncio


class FakeElevenLabs:
    def __init__(self) -> None:
        self.agents: dict[str, dict] = {}
        self.tools: dict[str, dict] = {}
        self.page_size = 2
        self.fail_agent_patch = False
        self.repeat_cursor = False

    async def handle(self, request: httpx.Request) -> httpx.Response:
        # Yield to the loop so concurrent provisioning calls really interleave.
        await asyncio.sleep(0)
        path = request.url.path.removeprefix("/v1/convai")
        body = json.loads(request.content) if request.content else None
        if path == "/agents" and request.method == "GET":
            if self.repeat_cursor:
                return httpx.Response(
                    200, json={"agents": [], "has_more": True, "next_cursor": "same"}
                )
            # Paginated like the real API; `search` is deliberately ignored so the
            # provisioner has to follow the cursor to find an agent on a later page.
            listing = [{"agent_id": i, "name": a["name"]} for i, a in self.agents.items()]
            start = int(request.url.params.get("cursor", 0))
            page = listing[start : start + self.page_size]
            has_more = start + self.page_size < len(listing)
            return httpx.Response(
                200,
                json={
                    "agents": page,
                    "has_more": has_more,
                    "next_cursor": str(start + self.page_size) if has_more else None,
                },
            )
        if path == "/agents/create":
            agent_id = f"agent_{len(self.agents) + 1}"
            self.agents[agent_id] = body
            return httpx.Response(200, json={"agent_id": agent_id})
        if path.startswith("/agents/") and request.method == "PATCH":
            if self.fail_agent_patch:
                return httpx.Response(422, json={"detail": "invalid"})
            self.agents[path.removeprefix("/agents/")] = body
            return httpx.Response(200, json={})
        if path == "/tools" and request.method == "GET":
            listing = [{"id": i, **t} for i, t in self.tools.items()]
            return httpx.Response(200, json={"tools": listing})
        if path == "/tools" and request.method == "POST":
            tool_id = f"tool_{len(self.tools) + 1}"
            self.tools[tool_id] = body
            return httpx.Response(200, json={"id": tool_id})
        if path.startswith("/tools/") and request.method == "PATCH":
            self.tools[path.removeprefix("/tools/")] = body
            return httpx.Response(200, json={})
        return httpx.Response(404)

    def prompt_of(self, agent_id: str) -> str:
        return self.agents[agent_id]["conversation_config"]["agent"]["prompt"]["prompt"]

    def tool_names_of(self, agent_id: str) -> list[str]:
        tools = self.agents[agent_id]["conversation_config"]["agent"]["prompt"]["tools"]
        return [tool["name"] for tool in tools]


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key):
        return self.values.get(key)

    async def set(self, key, value, ex=None):
        self.values[key] = value

    async def delete(self, key):
        self.values.pop(key, None)


@pytest.fixture
def fake_api(monkeypatch) -> FakeElevenLabs:
    api = FakeElevenLabs()
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(
        provisioner_module.httpx,
        "AsyncClient",
        functools.partial(real_async_client, transport=httpx.MockTransport(api.handle)),
    )
    return api


@pytest.fixture
def provisioner() -> ElevenLabsAgentProvisioner:
    # The provisioner is a process-wide singleton; drop it so each test gets an empty cache.
    SingletonMeta._instances.pop(ElevenLabsAgentProvisioner, None)
    redis_service = SimpleNamespace(aioredis_client=FakeRedis())
    yield ElevenLabsAgentProvisioner(redis_service)
    SingletonMeta._instances.pop(ElevenLabsAgentProvisioner, None)


def _tool(name: str) -> RealtimeTool:
    return RealtimeTool(name=name, parameters=ToolParameters(properties={}))


async def _provision(provisioner, *, org_id, config_id, instructions, tools) -> str:
    return await provisioner.get_or_create_agent(
        api_key="key",
        agent_name=remote_agent_name(org_id, config_id),
        instructions=instructions,
        voice="21m00Tcm4TlvDq8ikWAM",
        rt_tools=tools,
        llm_model="gemini-2.5-flash",
    )


async def test_two_configurations_get_separate_remote_agents_with_their_own_prompt_and_tools(
    provisioner, fake_api
):
    restricted = await _provision(
        provisioner, org_id=1, config_id=10, instructions="restricted", tools=[_tool("read_docs")]
    )
    permissive = await _provision(
        provisioner,
        org_id=1,
        config_id=11,
        instructions="permissive",
        tools=[_tool("read_docs"), _tool("delete_everything")],
    )

    assert restricted != permissive
    assert fake_api.prompt_of(restricted) == "restricted"
    assert fake_api.tool_names_of(restricted) == ["read_docs"]
    assert fake_api.prompt_of(permissive) == "permissive"
    assert fake_api.tool_names_of(permissive) == ["read_docs", "delete_everything"]


async def test_configurations_in_different_organizations_get_separate_agents(
    provisioner, fake_api
):
    first = await _provision(provisioner, org_id=1, config_id=5, instructions="org one", tools=[])
    second = await _provision(provisioner, org_id=2, config_id=5, instructions="org two", tools=[])

    assert first != second
    assert fake_api.prompt_of(first) == "org one"
    assert fake_api.prompt_of(second) == "org two"


async def test_cache_hit_returns_the_configurations_own_agent_even_for_identical_content(
    provisioner, fake_api
):
    first = await _provision(provisioner, org_id=1, config_id=10, instructions="same", tools=[])
    second = await _provision(provisioner, org_id=1, config_id=11, instructions="same", tools=[])
    first_again = await _provision(
        provisioner, org_id=1, config_id=10, instructions="same", tools=[]
    )

    assert first != second
    assert first_again == first
    assert len(fake_api.agents) == 2


async def test_reprovisioning_one_configuration_leaves_the_other_untouched(provisioner, fake_api):
    keep = await _provision(provisioner, org_id=1, config_id=10, instructions="keep", tools=[])
    changed = await _provision(provisioner, org_id=1, config_id=11, instructions="v1", tools=[])

    await _provision(provisioner, org_id=1, config_id=11, instructions="v2", tools=[])

    assert fake_api.prompt_of(keep) == "keep"
    assert fake_api.prompt_of(changed) == "v2"


async def test_reverting_a_configuration_reprovisions_instead_of_serving_the_edited_agent(
    provisioner, fake_api
):
    agent_id = await _provision(provisioner, org_id=1, config_id=10, instructions="v1", tools=[])
    await _provision(provisioner, org_id=1, config_id=10, instructions="v2", tools=[])

    reverted = await _provision(provisioner, org_id=1, config_id=10, instructions="v1", tools=[])

    assert reverted == agent_id
    assert fake_api.prompt_of(agent_id) == "v1"


async def test_existing_agent_beyond_the_first_page_is_updated_not_duplicated(
    provisioner, fake_api
):
    for config_id in range(1, 6):
        await _provision(
            provisioner, org_id=1, config_id=config_id, instructions=f"c{config_id}", tools=[]
        )
    agent_count = len(fake_api.agents)
    # A changed prompt forces a cache miss, so the provisioner must search again.
    await _provision(provisioner, org_id=1, config_id=5, instructions="c5 edited", tools=[])

    assert len(fake_api.agents) == agent_count
    assert any(
        agent["name"] == remote_agent_name(1, 5)
        and agent["conversation_config"]["agent"]["prompt"]["prompt"] == "c5 edited"
        for agent in fake_api.agents.values()
    )


async def test_failed_update_is_not_cached_as_if_the_agent_held_the_new_content(
    provisioner, fake_api
):
    agent_id = await _provision(provisioner, org_id=1, config_id=10, instructions="v1", tools=[])
    fake_api.fail_agent_patch = True

    served = await _provision(provisioner, org_id=1, config_id=10, instructions="v2", tools=[])
    fake_api.fail_agent_patch = False
    retried = await _provision(provisioner, org_id=1, config_id=10, instructions="v2", tools=[])

    assert served == agent_id
    assert retried == agent_id
    assert fake_api.prompt_of(agent_id) == "v2"


async def test_concurrent_first_sessions_of_one_configuration_create_one_agent(
    provisioner, fake_api
):
    agent_ids = await asyncio.gather(
        *(
            _provision(provisioner, org_id=1, config_id=10, instructions="same", tools=[])
            for _ in range(3)
        )
    )

    assert len(set(agent_ids)) == 1
    assert len(fake_api.agents) == 1


async def test_a_listing_whose_cursor_never_advances_raises_instead_of_looping(
    provisioner, fake_api
):
    fake_api.repeat_cursor = True

    with pytest.raises(RuntimeError, match="pagination is not advancing"):
        await _provision(provisioner, org_id=1, config_id=10, instructions="x", tools=[])


async def test_editing_only_a_tool_description_reprovisions_the_agent(provisioner, fake_api):
    tool = _tool("read_docs")
    tool.description = "old description"
    agent_id = await _provision(
        provisioner, org_id=1, config_id=10, instructions="same", tools=[tool]
    )
    edited = _tool("read_docs")
    edited.description = "new description"

    await _provision(provisioner, org_id=1, config_id=10, instructions="same", tools=[edited])

    sent_tools = fake_api.agents[agent_id]["conversation_config"]["agent"]["prompt"]["tools"]
    assert sent_tools[0]["description"] == "new description"


async def test_invalidate_cache_removes_the_entry_get_or_create_wrote(provisioner, fake_api):
    name = remote_agent_name(1, 10)
    await _provision(provisioner, org_id=1, config_id=10, instructions="v1", tools=[])
    redis = provisioner.redis_service.aioredis_client
    assert redis.values

    await provisioner.invalidate_cache(api_key="key", agent_name=name)

    assert redis.values == {}


async def test_the_remote_agent_is_named_after_organization_and_configuration(
    provisioner, fake_api
):
    agent_id = await _provision(provisioner, org_id=7, config_id=42, instructions="x", tools=[])

    assert fake_api.agents[agent_id]["name"] == "EpicStaff-org7-rtdef42"


async def test_client_without_a_configuration_id_refuses_to_provision():
    client = ElevenLabsRealtimeAgentClient(
        api_key="key",
        connection_key="conn",
        agent_provisioner=MagicMock(),
        org_id=1,
        rt_agent_definition_id=None,
    )

    with pytest.raises(ValueError, match="rt_agent_definition_id"):
        client.agent_name


async def test_client_name_comes_from_its_organization_and_configuration():
    client = ElevenLabsRealtimeAgentClient(
        api_key="key",
        connection_key="conn",
        agent_provisioner=MagicMock(),
        org_id=3,
        rt_agent_definition_id=9,
    )

    assert client.agent_name == remote_agent_name(3, 9)
