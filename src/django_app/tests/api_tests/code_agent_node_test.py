import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import Graph, LLMConfig, LLMModel, Provider
from tables.models.graph_models import CodeAgentNode
from tests.fixtures import *


@pytest.fixture
def llm_config_for_code_agent(db):
    provider = Provider.objects.create(name="openai")
    model = LLMModel.objects.create(
        name="gpt-4o",
        llm_provider=provider,
    )
    return LLMConfig.objects.create(
        custom_name="test-code-agent-config",
        model=model,
        api_key="sk-test-key",
    )


@pytest.fixture
def code_agent_node(graph, llm_config_for_code_agent):
    return CodeAgentNode.objects.create(
        graph=graph,
        node_name="test_code_agent",
        llm_config=llm_config_for_code_agent,
        agent_mode="build",
        system_prompt="You are a helpful coding assistant.",
        stream_handler_code="def on_chunk(text, context): pass",
        libraries=["requests"],
        polling_interval_ms=500,
        silence_indicator_s=5,
        indicator_repeat_s=10,
        chunk_timeout_s=60,
        inactivity_timeout_s=180,
        max_wait_s=600,
        input_map={"prompt": "variables.user_message"},
        output_variable_path="code_reply",
    )


@pytest.mark.django_db
class TestCodeAgentNodeModel:
    def test_create_code_agent_node(self, code_agent_node):
        assert code_agent_node.pk is not None
        assert code_agent_node.node_name == "test_code_agent"
        assert code_agent_node.agent_mode == "build"
        assert code_agent_node.system_prompt == "You are a helpful coding assistant."
        assert code_agent_node.libraries == ["requests"]
        assert code_agent_node.polling_interval_ms == 500

    def test_auto_node_name(self, graph, llm_config_for_code_agent):
        node = CodeAgentNode.objects.create(
            graph=graph,
            llm_config=llm_config_for_code_agent,
        )
        assert node.node_name.startswith("codeagentnode_")

    def test_defaults(self, graph):
        node = CodeAgentNode.objects.create(
            graph=graph,
            node_name="defaults_test",
        )
        assert node.llm_config is None
        assert node.agent_mode == "build"
        assert node.system_prompt == ""
        assert node.stream_handler_code == ""
        assert node.libraries == []
        assert node.polling_interval_ms == 1000
        assert node.silence_indicator_s == 3
        assert node.indicator_repeat_s == 5
        assert node.chunk_timeout_s == 30
        assert node.inactivity_timeout_s == 120
        assert node.max_wait_s == 300
        assert node.input_map == {}
        assert node.output_variable_path is None

    def test_cascade_delete_graph(self, code_agent_node):
        graph_id = code_agent_node.graph.id
        Graph.objects.filter(id=graph_id).delete()
        assert CodeAgentNode.objects.filter(pk=code_agent_node.pk).count() == 0

    def test_set_null_on_llm_config_delete(self, code_agent_node):
        config_id = code_agent_node.llm_config.id
        LLMConfig.objects.filter(id=config_id).delete()
        code_agent_node.refresh_from_db()
        assert code_agent_node.llm_config is None

    def test_unique_constraint(self, graph, llm_config_for_code_agent):
        CodeAgentNode.objects.create(
            graph=graph,
            node_name="unique_test",
        )
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            CodeAgentNode.objects.create(
                graph=graph,
                node_name="unique_test",
            )


@pytest.mark.django_db
class TestCodeAgentNodeAPI:
    def test_list_empty(self, api_client):
        url = reverse("codeagentnode-list")
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK

    def test_create(self, api_client, graph, llm_config_for_code_agent):
        url = reverse("codeagentnode-list")
        data = {
            "graph": graph.id,
            "node_name": "api_create_test",
            "llm_config": llm_config_for_code_agent.id,
            "agent_mode": "plan",
            "system_prompt": "Be concise.",
            "stream_handler_code": "",
            "libraries": ["httpx"],
            "polling_interval_ms": 2000,
            "input_map": {"prompt": "vars.msg"},
            "output_variable_path": "result",
        }
        response = api_client.post(url, data, format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert response.data["node_name"] == "api_create_test"
        assert response.data["agent_mode"] == "plan"
        assert response.data["libraries"] == ["httpx"]

    def test_retrieve(self, api_client, code_agent_node):
        url = reverse("codeagentnode-detail", args=[code_agent_node.pk])
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["node_name"] == "test_code_agent"
        assert response.data["system_prompt"] == "You are a helpful coding assistant."

    def test_update(self, api_client, code_agent_node):
        url = reverse("codeagentnode-detail", args=[code_agent_node.pk])
        response = api_client.patch(
            url,
            {"agent_mode": "plan", "max_wait_s": 900},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK
        code_agent_node.refresh_from_db()
        assert code_agent_node.agent_mode == "plan"
        assert code_agent_node.max_wait_s == 900

    def test_delete(self, api_client, code_agent_node):
        url = reverse("codeagentnode-detail", args=[code_agent_node.pk])
        response = api_client.delete(url)
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert CodeAgentNode.objects.filter(pk=code_agent_node.pk).count() == 0

    def test_in_graph_serializer(self, api_client, code_agent_node):
        url = reverse("graphs-detail", args=[code_agent_node.graph.id])
        response = api_client.get(url)
        assert response.status_code == status.HTTP_200_OK
        ca_list = response.data.get("code_agent_node_list", [])
        assert len(ca_list) == 1
        assert ca_list[0]["node_name"] == "test_code_agent"


@pytest.mark.django_db
class TestCodeAgentNodeRequestModels:
    def test_django_request_model(self):
        from src.shared.models import CodeAgentNodeData, GraphData

        data = CodeAgentNodeData(
            node_name="test",
            llm_config_id=1,
            agent_mode="build",
            input_map={"prompt": "x"},
        )
        assert data.node_name == "test"
        assert data.polling_interval_ms == 1000

        graph_data = GraphData(
            name="g",
            entrypoint="test",
            end_node=None,
            code_agent_node_list=[data],
        )
        assert len(graph_data.code_agent_node_list) == 1

    def test_crew_request_model_parity(self):
        """Verify Django CodeAgentNodeData fields match expected crew contract."""
        from src.shared.models import CodeAgentNodeData

        data = CodeAgentNodeData(node_name="parity_test", llm_config_id=2)
        assert data.agent_mode == "build"
        assert data.max_wait_s == 300
        assert data.polling_interval_ms == 1000
        assert data.libraries == []
        assert data.stream_handler_code == ""
