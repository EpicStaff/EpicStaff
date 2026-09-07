"""
API tests for initializing a realtime session from a RealtimeAgentDefinition
(the AgentDefinition-based counterpart to the legacy RealtimeAgent flow).

Covers:
- Happy path: agent_definition_id -> 201 + connection_key, redis publish with
  role/goal/backstory/memory mapped from the AgentDefinition.
- Surface resolution: default surface (place=ALL/REALTIME) tools + naive
  knowledge reach the published payload.
- Place filtering: place=CHAT-only surfaces are excluded; owned surfaces with
  no explicit AgentDefaultSurface row are included (implicit ALL).
- Graph-rag tie-break: basic search config wins over local when both are set.
- Validation: missing agent_definition_id -> 400; unknown agent_definition_id
  -> 400.
"""

import json

import pytest
from django.urls import reverse
from rest_framework import status

from agents.models import AgentDefaultSurface, AgentDefinition, Surface, SurfacePlace
from tables.models.rbac_models import Organization
from agents.models.surface_models import (
    SurfaceGraphBasicSearchConfig,
    SurfaceGraphLocalSearchConfig,
    SurfaceKnowledge,
    SurfaceNaiveSearchConfig,
    SurfacePythonTool,
    ToolMode,
)
from tables.models.knowledge_models.collection_models import (
    BaseRagType,
    SourceCollection,
)
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.realtime_models import OpenAIRealtimeConfig, RealtimeAgentDefinition
from tests.fixtures import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


@pytest.fixture
def agent_definition(default_org, llm_config):
    return AgentDefinition.objects.create(
        organization=default_org,
        name="voice-agent",
        description="Helps with voice tasks",
        instructions="Be concise and helpful",
        llm_config=llm_config,
    )


@pytest.fixture
def rt_agent_definition(agent_definition, openai_realtime_provider_config):
    return RealtimeAgentDefinition.objects.create(
        agent_definition=agent_definition,
        openai_config=openai_realtime_provider_config,
    )


@pytest.fixture
def py_tool_a(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="voice-py-tool-a", description="test", python_code=code
    )


@pytest.fixture
def py_tool_b(db):
    code = PythonCode.objects.create(code="def main(): pass")
    return PythonCodeTool.objects.create(
        name="voice-py-tool-b", description="test", python_code=code
    )


@pytest.fixture
def naive_collection(db):
    collection = SourceCollection.objects.create(collection_name="voice-naive-coll")
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.NAIVE, source_collection=collection
    )
    return collection


@pytest.fixture
def completed_naive_rag(naive_collection):
    base_rag_type = BaseRagType.objects.get(source_collection=naive_collection)
    return NaiveRag.objects.create(
        base_rag_type=base_rag_type,
        rag_status=NaiveRag.NaiveRagStatus.COMPLETED,
    )


@pytest.fixture
def graph_collection(db):
    collection = SourceCollection.objects.create(collection_name="voice-graph-coll")
    BaseRagType.objects.create(
        rag_type=BaseRagType.RagType.GRAPH, source_collection=collection
    )
    return collection


@pytest.fixture
def completed_graph_rag(graph_collection):
    base_rag_type = BaseRagType.objects.get(source_collection=graph_collection)
    return GraphRag.objects.create(
        base_rag_type=base_rag_type,
        rag_status=GraphRag.GraphRagStatus.COMPLETED,
    )


def _published_payload(redis_client_mock) -> dict:
    channel, body = redis_client_mock.publish.call_args[0]
    assert channel == "realtime_agents:schema"
    return json.loads(body)


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_init_realtime_agent_definition_happy_path(
    rt_agent_definition, auth_client, redis_client_mock
):
    url = reverse("init-realtime")

    response = auth_client.post(
        url,
        data={"agent_definition_id": rt_agent_definition.pk},
        format="json",
    )
    response_data = response.json()

    assert response.status_code == status.HTTP_201_CREATED, response_data
    assert "connection_key" in response_data
    assert isinstance(response_data["connection_key"], str)

    redis_client_mock.publish.assert_called_once()

    payload = _published_payload(redis_client_mock)
    agent_definition = rt_agent_definition.agent_definition
    assert payload["role"] == agent_definition.name
    assert payload["goal"] == agent_definition.description
    assert payload["backstory"] == agent_definition.instructions
    assert payload["memory"] is False


@pytest.mark.django_db
def test_init_realtime_agent_definition_populates_created_by_for_browser_session(
    rt_agent_definition, auth_client, regular_user, redis_client_mock
):
    """Same finding-#33 follow-up as the legacy agent_id path: a browser
    `/chats` session on an AgentDefinition-backed voice agent still has a
    real authenticated user, so `user_id` must be populated."""
    url = reverse("init-realtime")

    response = auth_client.post(
        url,
        data={"agent_definition_id": rt_agent_definition.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert _published_payload(redis_client_mock)["user_id"] == regular_user.id


# ---------------------------------------------------------------------------
# 2. Surface resolution through the API
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_init_realtime_agent_definition_resolves_surface_tools_and_knowledge(
    rt_agent_definition,
    auth_client,
    redis_client_mock,
    py_tool_a,
    naive_collection,
    completed_naive_rag,
):
    agent_definition = rt_agent_definition.agent_definition
    surface = Surface.objects.create(
        organization=agent_definition.organization, name="voice-surface"
    )
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=py_tool_a, mode=ToolMode.ALLOW
    )
    knowledge = SurfaceKnowledge.objects.create(
        surface=surface, collection=naive_collection
    )
    SurfaceNaiveSearchConfig.objects.create(
        surface_knowledge=knowledge, search_limit=5, similarity_threshold="0.35"
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent_definition, surface=surface, place=SurfacePlace.REALTIME
    )

    url = reverse("init-realtime")
    response = auth_client.post(
        url, data={"agent_definition_id": rt_agent_definition.pk}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()

    payload = _published_payload(redis_client_mock)
    tool_names = {tool["unique_name"] for tool in payload["tools"]}
    assert f"python-code-tool:{py_tool_a.pk}" in tool_names

    assert payload["knowledge_collection_id"] == naive_collection.pk
    assert payload["rag_type_id"] == f"naive:{completed_naive_rag.naive_rag_id}"
    assert payload["rag_search_config"] is not None
    assert payload["rag_search_config"]["rag_type"] == "naive"


# ---------------------------------------------------------------------------
# 3. Place filtering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_init_realtime_agent_definition_place_filtering(
    rt_agent_definition, auth_client, redis_client_mock, py_tool_a, py_tool_b
):
    agent_definition = rt_agent_definition.agent_definition

    chat_only_surface = Surface.objects.create(
        organization=agent_definition.organization, name="chat-only-surface"
    )
    SurfacePythonTool.objects.create(
        surface=chat_only_surface, python_tool=py_tool_a, mode=ToolMode.ALLOW
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent_definition,
        surface=chat_only_surface,
        place=SurfacePlace.CHAT,
    )

    owned_surface_implicit_all = Surface.objects.create(
        organization=agent_definition.organization,
        name="owned-implicit-all-surface",
        owner_agent=agent_definition,
    )
    SurfacePythonTool.objects.create(
        surface=owned_surface_implicit_all, python_tool=py_tool_b, mode=ToolMode.ALLOW
    )

    url = reverse("init-realtime")
    response = auth_client.post(
        url, data={"agent_definition_id": rt_agent_definition.pk}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()

    payload = _published_payload(redis_client_mock)
    tool_names = {tool["unique_name"] for tool in payload["tools"]}
    assert f"python-code-tool:{py_tool_a.pk}" not in tool_names
    assert f"python-code-tool:{py_tool_b.pk}" in tool_names


# ---------------------------------------------------------------------------
# 4. Graph-rag tie-break: basic wins over local
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_init_realtime_agent_definition_graph_rag_basic_wins_over_local(
    rt_agent_definition,
    auth_client,
    redis_client_mock,
    graph_collection,
    completed_graph_rag,
):
    agent_definition = rt_agent_definition.agent_definition
    surface = Surface.objects.create(
        organization=agent_definition.organization, name="graph-tie-break-surface"
    )
    knowledge = SurfaceKnowledge.objects.create(
        surface=surface, collection=graph_collection
    )
    SurfaceGraphBasicSearchConfig.objects.create(
        surface_knowledge=knowledge, k=15, max_context_tokens=8000
    )
    SurfaceGraphLocalSearchConfig.objects.create(
        surface_knowledge=knowledge, top_k_entities=20, top_k_relationships=20
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent_definition, surface=surface, place=SurfacePlace.ALL
    )

    url = reverse("init-realtime")
    response = auth_client.post(
        url, data={"agent_definition_id": rt_agent_definition.pk}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()

    payload = _published_payload(redis_client_mock)
    assert payload["rag_type_id"] == f"graph:{completed_graph_rag.graph_rag_id}"
    search_params = payload["rag_search_config"]["search_params"]
    assert search_params["search_method"] == "basic"
    assert search_params["k"] == 15


# ---------------------------------------------------------------------------
# 5. Validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_init_realtime_missing_agent_definition_id_returns_400(auth_client):
    url = reverse("init-realtime")

    response = auth_client.post(url, data={}, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_init_realtime_unknown_agent_definition_id_returns_400(auth_client):
    """Missing-agent Http404 collapses into 400 (broad except in
    InitRealtimeAPIView.post)."""
    url = reverse("init-realtime")

    response = auth_client.post(
        url, data={"agent_definition_id": 999999}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_init_realtime_cross_org_agent_definition_rejected(auth_client, org_b):
    """An org_a caller must not be able to init a realtime session for another
    org's AgentDefinition by guessing/reusing its RealtimeAgentDefinition pk."""
    other_agent_definition = AgentDefinition.objects.create(
        organization=org_b, name="other-org-agent"
    )
    other_config = OpenAIRealtimeConfig.objects.create(
        custom_name="other-org-openai-config", org=org_b
    )
    other_rt_agent_definition = RealtimeAgentDefinition.objects.create(
        agent_definition=other_agent_definition,
        openai_config=other_config,
    )

    url = reverse("init-realtime")
    response = auth_client.post(
        url,
        data={"agent_definition_id": other_rt_agent_definition.pk},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "agent_definition_id" in str(response.data)
