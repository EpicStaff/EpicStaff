import pytest
from django.urls import reverse
from rest_framework import status

from agents.models import AgentDefinition
from tables.models import Session
from tables.models.graph_models import AgentNode, Edge
from tables.models.graph_models import StartNode
from tables.models.llm_models import LLMConfig, LLMModel
from tables.models.provider import Provider
from tests.fixtures import *


@pytest.mark.django_db
def test_run_session_with_deleted_llm_provider_returns_400_naming_the_config(
    auth_client, redis_client_mock, session_data, graph, default_org
):
    provider = Provider.objects.create(name="doomed-provider")
    model = LLMModel.objects.create(name="llm", org=default_org, llm_provider=provider)
    llm_config = LLMConfig.objects.create(
        custom_name="Agent main LLM", model=model, org=default_org
    )
    agent_definition = AgentDefinition.objects.create(
        org=default_org, name="doomed-agent", llm_config=llm_config
    )
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="agent-node", agent_definition=agent_definition
    )
    start_node = StartNode.objects.get(graph=graph)
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=agent_node.id)
    provider.delete()

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert "LLM config 'Agent main LLM' has no model or provider" in response.data["error"]
    assert not Session.objects.filter(graph=graph, status="running").exists()
