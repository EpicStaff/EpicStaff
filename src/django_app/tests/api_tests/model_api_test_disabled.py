import pytest
from django.urls import reverse

from tables.models import (
    Session,
    Agent,
    Task,
    TemplateAgent,
    LLMConfig,
    EmbeddingModel,
    LLMModel,
    Provider,
    Crew,
)
from tables.services.converter_service import ConverterService
from rest_framework import status

from tests.fixtures import *


converter_service = ConverterService()


@pytest.mark.django_db
def test_create_llm_config(api_client, gpt_4o_llm):
    url = reverse("llmconfig-list")
    data = {
        "custom_name": "MyConfig",
        "model": gpt_4o_llm.pk,
        "temperature": 0.9,
        "num_ctx": 30,
        "is_visible": True,
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert LLMConfig.objects.count() == 1
    assert LLMConfig.objects.first().temperature == data["temperature"]
    assert LLMConfig.objects.first().custom_name == data["custom_name"]


@pytest.mark.django_db
def test_create_provider(api_client):
    url = reverse("provider-list")
    data = {"name": "new_provider"}

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert Provider.objects.count() == 1
    assert Provider.objects.first().name == "new_provider"


@pytest.mark.django_db
def test_create_llm_model(api_client, openai_provider):
    url = reverse("llmmodel-list")
    data = {
        "name": "model_x",
        "description": "Test model",
        "llm_provider": openai_provider.pk,
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert LLMModel.objects.count() == 1
    assert LLMModel.objects.first().name == "model_x"


@pytest.mark.django_db
def test_create_embedding_model(api_client, openai_provider):
    url = reverse("embeddingmodel-list")
    data = {
        "name": "embedding_model_y",
        "embedding_provider": openai_provider.pk,
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert EmbeddingModel.objects.count() == 1
    assert EmbeddingModel.objects.first().name == "embedding_model_y"


@pytest.mark.django_db
def test_create_agent(
    api_client, llm_config, wikipedia_tool_config, default_agent_config
):
    url = reverse("agent-list")
    data = {
        "role": "test_agent",
        "goal": "test_goal",
        "backstory": "test_backstory",
        "allow_delegation": True,
        "memory": True,
        "max_iter": 10,
        "llm_config": llm_config.pk,
        "configured_tools": [wikipedia_tool_config.pk],
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert Agent.objects.count() == 1
    assert Agent.objects.first().role == "test_agent"


@pytest.mark.django_db
def test_create_template_agent(api_client, llm_config, wikipedia_tool_config):
    url = reverse("templateagent-list")
    data = {
        "role": "template_agent",
        "goal": "test_goal",
        "backstory": "test_backstory",
        "allow_delegation": True,
        "memory": True,
        "max_iter": 10,
        "llm_config": llm_config.pk,
        "fcm_llm_config": llm_config.pk,
        "configured_tools": [wikipedia_tool_config.pk],
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert TemplateAgent.objects.count() == 1
    assert TemplateAgent.objects.first().role == "template_agent"


@pytest.mark.django_db
def test_create_crew(
    api_client,
    wikipedia_agent,
    embedding_model,
    gpt_4o_llm,
    llm_config,
    default_crew_config,
):
    url = reverse("crew-list")
    data = {
        "name": "Test Crew",
        "description": "A test crew",
        "assignment": "Test assignment",
        "process": "sequential",
        "memory": True,
        "embedding_model": embedding_model.pk,
        "manager_llm_model": gpt_4o_llm.pk,
        "manager_llm_config": llm_config.pk,
        "agents": [wikipedia_agent.pk],
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert Crew.objects.count() == 1
    assert Crew.objects.first().name == "Test Crew"


@pytest.mark.django_db
def test_create_task(api_client, crew, wikipedia_agent):
    url = reverse("task-list")
    data = {
        "name": "task_x",
        "crew": crew.pk,
        "agent": wikipedia_agent.pk,
        "instructions": "Complete this task",
        "expected_output": "Expected result",
        "order": 1,
    }

    response = api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert Task.objects.filter(name="task_x").count() == 1


@pytest.mark.django_db
def test_get_agents_empty(api_client):
    url = reverse("agent-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
def test_get_agents_with_data(api_client, wikipedia_agent):
    url = reverse("agent-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 1

    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["role"] == wikipedia_agent.role


@pytest.mark.django_db
def test_get_llm_configs_empty(api_client):
    url = reverse("llmconfig-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
def test_get_llm_configs_with_data(api_client, llm_config):
    url = reverse("llmconfig-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 1

    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["temperature"] == llm_config.temperature


@pytest.mark.django_db
def test_get_providers_empty(api_client):
    url = reverse("provider-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
def test_get_providers_with_data(api_client, openai_provider):
    url = reverse("provider-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 1

    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["name"] == openai_provider.name


@pytest.mark.django_db
def test_get_llm_models_empty(api_client):
    url = reverse("llmmodel-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
def test_get_llm_models_with_data(api_client, gpt_4o_llm):
    url = reverse("llmmodel-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 1

    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["name"] == gpt_4o_llm.name


@pytest.mark.django_db
def test_get_llm_default_agent_config(api_client, default_agent_config):
    url = reverse("default-agent-config")
    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    data = response.json()
    assert data["allow_delegation"] == default_agent_config.allow_delegation
    assert data["memory"] == default_agent_config.memory
    assert data["max_iter"] == default_agent_config.max_iter
    assert data["llm_config"] == default_agent_config.llm_config.pk


@pytest.mark.django_db
def test_get_llm_default_crew_config(
    api_client, gpt_4o_llm, llm_config, default_crew_config
):
    url = reverse("default-crew-config")
    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    data = response.json()
    assert data["process"] == default_crew_config.process
    assert data["memory"] == default_crew_config.memory
    assert data["embedding_config"] == default_crew_config.embedding_config
    assert data["manager_llm_config"] == default_crew_config.manager_llm_config.pk


@pytest.mark.django_db
def test_get_embedding_models_empty(api_client):
    url = reverse("embeddingmodel-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
def test_get_embedding_models_with_data(api_client, embedding_model):
    url = reverse("embeddingmodel-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 1

    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["name"] == embedding_model.name


@pytest.mark.django_db
def test_get_tools_empty(api_client):
    url = reverse("tool-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
def test_get_tools_with_data(api_client, wikipedia_tool):
    url = reverse("tool-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 1

    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["name"] == wikipedia_tool.name


@pytest.mark.django_db
def test_get_crews_empty(api_client):
    url = reverse("crew-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
def test_get_crews_with_data(api_client, crew):
    url = reverse("crew-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 1

    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["name"] == crew.name


@pytest.mark.django_db
def test_get_tasks_empty(api_client):
    url = reverse("task-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
def test_get_tasks_with_data(api_client, crew, wikipedia_agent):
    # First create a task
    task_url = reverse("task-list")
    task_data = {
        "name": "test_task",
        "crew": crew.pk,
        "agent": wikipedia_agent.pk,
        "instructions": "Complete the test task",
        "expected_output": "Expected output",
        "order": 1,
    }
    api_client.post(task_url, task_data, format="json")

    # Now retrieve all tasks
    url = reverse("task-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content

    for task in response.data["results"]:
        if task["name"] == task_data["name"]:
            break
    else:
        assert False, "Task not found"


# =====================================


@pytest.mark.django_db
def test_get_agent_by_id(api_client, wikipedia_agent):
    url = reverse("agent-detail", args=[wikipedia_agent.pk])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["role"] == wikipedia_agent.role


@pytest.mark.django_db
def test_get_agent_by_invalid_id(api_client):
    url = reverse("agent-detail", args=[999])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_get_llm_config_by_id(api_client, llm_config):
    url = reverse("llmconfig-detail", args=[llm_config.pk])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["temperature"] == llm_config.temperature


@pytest.mark.django_db
def test_get_llm_config_by_invalid_id(api_client):
    url = reverse("llmconfig-detail", args=[999])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_get_provider_by_id(api_client, openai_provider):
    url = reverse("provider-detail", args=[openai_provider.pk])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["name"] == openai_provider.name


@pytest.mark.django_db
def test_get_provider_by_invalid_id(api_client):
    url = reverse("provider-detail", args=[999])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_get_llm_model_by_id(api_client, gpt_4o_llm):
    url = reverse("llmmodel-detail", args=[gpt_4o_llm.pk])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["name"] == gpt_4o_llm.name


@pytest.mark.django_db
def test_get_llm_model_by_invalid_id(api_client):
    url = reverse("llmmodel-detail", args=[999])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_get_embedding_model_by_id(api_client, embedding_model):
    url = reverse("embeddingmodel-detail", args=[embedding_model.pk])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["name"] == embedding_model.name


@pytest.mark.django_db
def test_get_embedding_model_by_invalid_id(api_client):
    url = reverse("embeddingmodel-detail", args=[999])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_get_tool_by_id(api_client, wikipedia_tool):
    url = reverse("tool-detail", args=[wikipedia_tool.pk])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["name"] == wikipedia_tool.name


@pytest.mark.django_db
def test_get_tool_by_invalid_id(api_client):
    url = reverse("tool-detail", args=[999])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_get_crew_by_id(api_client, crew):
    url = reverse("crew-detail", args=[crew.pk])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["name"] == crew.name


@pytest.mark.django_db
def test_get_crew_by_invalid_id(api_client):
    url = reverse("crew-detail", args=[999])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_get_task_by_id(api_client, crew, wikipedia_agent):
    # First create a task to retrieve
    task_url = reverse("task-list")
    task_data = {
        "name": "test_task",
        "crew": crew.pk,
        "agent": wikipedia_agent.pk,
        "instructions": "Complete the test task",
        "expected_output": "Expected output",
        "order": 1,
    }
    task_response = api_client.post(task_url, task_data, format="json")
    task_id = task_response.data["id"]

    # Now retrieve the task by ID
    url = reverse("task-detail", args=[task_id])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["name"] == "test_task"


@pytest.mark.django_db
def test_get_task_by_invalid_id(api_client):
    url = reverse("task-detail", args=[999])

    response = api_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


# =====================================


@pytest.mark.django_db
def test_update_agent(api_client, wikipedia_agent, default_agent_config):
    url = reverse("agent-detail", args=[wikipedia_agent.pk])
    updated_data = {
        "role": "Updated Role",
        "goal": "Updated goal",
        "backstory": "Updated backstory",
        "allow_delegation": False,
        "memory": False,
        "max_iter": 1,
        "llm_config": None,
        "fcm_llm_config": None,
    }

    response = api_client.put(url, updated_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    wikipedia_agent.refresh_from_db()

    # Dynamically assert each field to match updated_data
    for field, value in updated_data.items():
        if field == "llm_config":
            assert default_agent_config.llm_config == getattr(wikipedia_agent, field)
            continue
        assert getattr(wikipedia_agent, field) == value


@pytest.mark.django_db
def test_update_agent_invalid_id(api_client):
    url = reverse("agent-detail", args=[999])
    updated_data = {
        "role": "Updated Role",
        "goal": "Updated goal",
        "backstory": "Updated backstory",
        "allow_delegation": False,
        "memory": False,
        "max_iter": 1,
        "llm_model": None,
        "fcm_llm_model": None,
        "llm_config": None,
        "fcm_llm_config": None,
    }
    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_update_llm_config(api_client, llm_config, gpt_4o_llm):
    url = reverse("llmconfig-detail", args=[llm_config.pk])
    updated_data = {
        "custom_name": "MyConfig",
        "model": gpt_4o_llm.pk,
        "temperature": 0.9,
        "num_ctx": 50,
    }

    response = api_client.put(url, updated_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    llm_config.refresh_from_db()

    assert llm_config.model.pk == updated_data["model"]
    assert llm_config.temperature == updated_data["temperature"]
    assert llm_config.num_ctx == updated_data["num_ctx"]
    assert llm_config.custom_name == updated_data["custom_name"]


@pytest.mark.django_db
def test_update_llm_config_invalid_id(api_client):
    url = reverse("llmconfig-detail", args=[999])
    updated_data = {
        "temperature": 0.9,
        "num_ctx": 50,
    }

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_update_provider(api_client, openai_provider):
    url = reverse("provider-detail", args=[openai_provider.pk])
    updated_data = {"name": "Updated Provider"}

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    openai_provider.refresh_from_db()
    assert openai_provider.name == updated_data["name"]


@pytest.mark.django_db
def test_update_provider_invalid_id(api_client):
    url = reverse("provider-detail", args=[999])
    updated_data = {"name": "Updated Provider"}

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_update_llm_model(api_client, gpt_4o_llm):
    url = reverse("llmmodel-detail", args=[gpt_4o_llm.pk])
    updated_data = {
        "name": "Updated LLM Name",
        "llm_provider": gpt_4o_llm.llm_provider.pk,
    }

    response = api_client.put(url, updated_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    gpt_4o_llm.refresh_from_db()

    assert gpt_4o_llm.name == updated_data["name"]
    assert gpt_4o_llm.llm_provider.pk == updated_data["llm_provider"]


@pytest.mark.django_db
def test_update_llm_model_invalid_id(api_client, gpt_4o_llm):
    url = reverse("llmmodel-detail", args=[999])
    updated_data = {
        "name": "Updated LLM Name",
        "llm_provider": gpt_4o_llm.llm_provider.pk,
    }

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_update_embedding_model(api_client, embedding_model):
    url = reverse("embeddingmodel-detail", args=[embedding_model.pk])

    test_provider = Provider.objects.create(name="test embedding provider")

    updated_data = {
        "name": "Updated Embedding Model",
        "embedding_provider": test_provider.pk,
        "deployment": "some test",
        "base_url": "https://some.url",
    }

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    embedding_model.refresh_from_db()
    assert embedding_model.name == updated_data["name"]
    assert embedding_model.embedding_provider.pk == updated_data["embedding_provider"]
    assert embedding_model.deployment == updated_data["deployment"]
    assert embedding_model.base_url == updated_data["base_url"]


@pytest.mark.django_db
def test_update_embedding_model_invalid_id(api_client):
    url = reverse("embeddingmodel-detail", args=[999])
    updated_data = {"name": "Updated Embedding Model"}

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_update_tool(api_client, wikipedia_tool):
    initial_data = {
        "name": wikipedia_tool.name,
        "name_alias": wikipedia_tool.name_alias,
        "description": wikipedia_tool.description,
        "enabled": wikipedia_tool.enabled,
    }

    url = reverse("tool-detail", args=[wikipedia_tool.pk])

    updated_data = {
        "name": "Updated Tool Name",
        "name_alias": "some alias",
        "description": "Updated tool description",
        "enabled": False,
    }

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    wikipedia_tool.refresh_from_db()
    assert wikipedia_tool.name == initial_data["name"]  # assert not updated
    assert wikipedia_tool.name_alias == initial_data["name_alias"]  # assert not updated
    assert (
        wikipedia_tool.description == initial_data["description"]
    )  # assert not updated
    assert wikipedia_tool.enabled == updated_data["enabled"]  # assert updated


@pytest.mark.django_db
def test_update_tool_invalid_id(api_client):
    url = reverse("tool-detail", args=[999])
    updated_data = {
        "name": "Updated Tool Name",
        "name_alias": "some alias",
        "description": "Updated tool description",
        "requires_model": True,
    }

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_update_crew(
    api_client,
    crew,
    wikipedia_agent,
    embedding_config,
    gpt_4o_llm,
    llm_config,
    default_crew_config,
):
    url = reverse("crew-detail", args=[crew.pk])

    updated_data = {
        "description": "Updated Crew Description",
        "name": "Updated Crew Name",
        "assignment": "Updated Assignment",
        "agents": [wikipedia_agent.pk],
        "process": "hierarchical",
        "memory": True,
        "embedding_config": embedding_config.pk,
        "manager_llm_config": llm_config.pk,
    }

    response = api_client.put(url, updated_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    crew.refresh_from_db()
    assert crew.description == updated_data["description"]
    assert crew.name == updated_data["name"]
    assert crew.assignment == updated_data["assignment"]
    assert list(crew.agents.values_list("pk", flat=True)) == updated_data["agents"]
    assert crew.process == updated_data["process"]
    assert crew.memory == updated_data["memory"]
    assert crew.embedding_config.pk == updated_data["embedding_config"]
    assert crew.manager_llm_config.pk == updated_data["manager_llm_config"]


@pytest.mark.django_db
def test_update_crew_invalid_id(
    api_client, wikipedia_agent, embedding_model, gpt_4o_llm, llm_config
):
    url = reverse("crew-detail", args=[999])
    updated_data = {
        "description": "Updated Crew Description",
        "name": "Updated Crew Name",
        "assignment": "Updated Assignment",
        "agents": [wikipedia_agent.pk],
        "process": "hierarchical",
        "memory": True,
        "embedding_model": embedding_model.pk,
        "manager_llm_model": gpt_4o_llm.pk,
        "manager_llm_config": llm_config.pk,
    }

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_update_task(api_client, test_task, wikipedia_agent, crew):
    task = test_task
    url = reverse("task-detail", args=[task.pk])

    updated_data = {
        "crew": crew.pk,
        "name": "Updated Task Name",
        "agent": wikipedia_agent.pk,
        "instructions": "Updated Instructions",
        "expected_output": "Updated Expected Output",
        "order": 2,
    }

    response = api_client.put(url, updated_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    task.refresh_from_db()
    assert task.crew.pk == updated_data["crew"]
    assert task.name == updated_data["name"]
    assert task.agent.pk == updated_data["agent"]
    assert task.instructions == updated_data["instructions"]
    assert task.expected_output == updated_data["expected_output"]
    assert task.order == updated_data["order"]


@pytest.mark.django_db
def test_update_task_invalid_id(api_client, test_task, wikipedia_agent, crew):
    url = reverse("task-detail", args=[999])
    updated_data = {
        "crew": crew.pk,
        "name": "Updated Task Name",
        "agent": wikipedia_agent.pk,
        "instructions": "Updated Instructions",
        "expected_output": "Updated Expected Output",
        "order": 2,
    }

    response = api_client.put(url, updated_data, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


# PATCH Tests ==========================


@pytest.mark.django_db
def test_patch_agent(api_client, wikipedia_agent, default_agent_config):
    url = reverse("agent-detail", args=[wikipedia_agent.pk])
    partial_data = {
        "role": "Partially Updated Role",
        "max_iter": 2,
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    wikipedia_agent.refresh_from_db()
    assert wikipedia_agent.role == partial_data["role"]
    assert wikipedia_agent.max_iter == partial_data["max_iter"]


@pytest.mark.django_db
def test_patch_agent_invalid_id(api_client):
    url = reverse("agent-detail", args=[999])
    partial_data = {
        "role": "Partially Updated Role",
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_patch_llm_config(api_client, llm_config):
    url = reverse("llmconfig-detail", args=[llm_config.pk])
    partial_data = {
        "temperature": 0.75,
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    llm_config.refresh_from_db()
    assert llm_config.temperature == partial_data["temperature"]


@pytest.mark.django_db
def test_patch_llm_config_invalid_id(api_client):
    url = reverse("llmconfig-detail", args=[999])
    partial_data = {
        "temperature": 0.75,
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_patch_provider(api_client, openai_provider):
    url = reverse("provider-detail", args=[openai_provider.pk])
    partial_data = {"name": "Partially Updated Provider"}

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    openai_provider.refresh_from_db()
    assert openai_provider.name == partial_data["name"]


@pytest.mark.django_db
def test_patch_provider_invalid_id(api_client):
    url = reverse("provider-detail", args=[999])
    partial_data = {"name": "Partially Updated Provider"}

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_patch_llm_model(api_client, gpt_4o_llm):
    url = reverse("llmmodel-detail", args=[gpt_4o_llm.pk])
    partial_data = {
        "name": "Partially Updated LLM Name",
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    gpt_4o_llm.refresh_from_db()
    assert gpt_4o_llm.name == partial_data["name"]


@pytest.mark.django_db
def test_patch_llm_model_invalid_id(api_client):
    url = reverse("llmmodel-detail", args=[999])
    partial_data = {
        "name": "Partially Updated LLM Name",
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_patch_embedding_model(api_client, embedding_model):
    url = reverse("embeddingmodel-detail", args=[embedding_model.pk])
    partial_data = {
        "deployment": "Updated Deployment",
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    embedding_model.refresh_from_db()
    assert embedding_model.deployment == partial_data["deployment"]


@pytest.mark.django_db
def test_patch_embedding_model_invalid_id(api_client):
    url = reverse("embeddingmodel-detail", args=[999])
    partial_data = {"deployment": "Updated Deployment"}

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_patch_tool(api_client, wikipedia_tool):
    url = reverse("tool-detail", args=[wikipedia_tool.pk])
    partial_data = {
        "enabled": False,
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    wikipedia_tool.refresh_from_db()
    assert wikipedia_tool.enabled == partial_data["enabled"]


@pytest.mark.django_db
def test_patch_tool_invalid_id(api_client):
    url = reverse("tool-detail", args=[999])
    partial_data = {
        "enabled": False,
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_patch_crew(api_client, crew, default_crew_config):
    url = reverse("crew-detail", args=[crew.pk])
    partial_data = {
        "description": "Partially Updated Crew Description",
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    crew.refresh_from_db()
    assert crew.description == partial_data["description"]


@pytest.mark.django_db
def test_patch_crew_invalid_id(api_client):
    url = reverse("crew-detail", args=[999])
    partial_data = {
        "description": "Partially Updated Crew Description",
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_patch_task(api_client, test_task):
    url = reverse("task-detail", args=[test_task.pk])
    partial_data = {
        "name": "Partially Updated Task Name",
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_200_OK, response.content

    test_task.refresh_from_db()
    assert test_task.name == partial_data["name"]


@pytest.mark.django_db
def test_patch_task_invalid_id(api_client):
    url = reverse("task-detail", args=[999])
    partial_data = {
        "name": "Partially Updated Task Name",
    }

    response = api_client.patch(url, partial_data, format="json")
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


# DELETE Tests ================================


@pytest.mark.django_db
def test_delete_agent(api_client, wikipedia_agent):
    url = reverse("agent-detail", args=[wikipedia_agent.pk])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content


@pytest.mark.django_db
def test_delete_agent_invalid_id(api_client):
    url = reverse("agent-detail", args=[999])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_delete_llm_config(api_client, llm_config):
    url = reverse("llmconfig-detail", args=[llm_config.pk])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content


@pytest.mark.django_db
def test_delete_llm_config_invalid_id(api_client):
    url = reverse("llmconfig-detail", args=[999])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_delete_provider(api_client, openai_provider):
    url = reverse("provider-detail", args=[openai_provider.pk])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content


@pytest.mark.django_db
def test_delete_provider_invalid_id(api_client):
    url = reverse("provider-detail", args=[999])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_delete_llm_model(api_client, gpt_4o_llm):
    url = reverse("llmmodel-detail", args=[gpt_4o_llm.pk])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content


@pytest.mark.django_db
def test_delete_llm_model_invalid_id(api_client):
    url = reverse("llmmodel-detail", args=[999])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_delete_embedding_model(api_client, embedding_model):
    url = reverse("embeddingmodel-detail", args=[embedding_model.pk])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content


@pytest.mark.django_db
def test_delete_embedding_model_invalid_id(api_client):
    url = reverse("embeddingmodel-detail", args=[999])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_delete_crew(api_client, crew):
    url = reverse("crew-detail", args=[crew.pk])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content


@pytest.mark.django_db
def test_delete_crew_invalid_id(api_client):
    url = reverse("crew-detail", args=[999])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_delete_task(api_client, test_task):
    url = reverse("task-detail", args=[test_task.pk])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content


@pytest.mark.django_db
def test_delete_task_invalid_id(api_client):
    url = reverse("task-detail", args=[999])
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
