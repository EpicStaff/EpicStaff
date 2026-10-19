"""POST /api/classification-decision-table-node/{pk}/explain/ — the error codes the
frontend turns into messages. Only the LLM provider call (`litellm.acompletion`) is
mocked; the view, service, secret resolution and LiteLLMClient run for real."""

import json
from types import SimpleNamespace
from unittest import mock

import litellm
import pytest
from rest_framework import status

from tables.constants.cdt_explanation_limits import (
    MAX_EXPLANATION_TEXT_LENGTH,
    MAX_GENERATED_BY_LENGTH,
)
from tables.models import Graph
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.models.llm_models import LLMConfig, LLMModel
from tables.models.provider import Provider
from tables.services.secrets import secret_service

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

BLOCK_ID = "spine:pre-computation"
MODEL_NAME = "cdt-explain-test-model"


def _url(node_id) -> str:
    return f"/api/classification-decision-table-node/{node_id}/explain/"


def _body(llm_config_id) -> dict:
    return {
        "llm_config": llm_config_id,
        "table": {"node_name": "classify", "rules": []},
        "blocks": [
            {
                "id": BLOCK_ID,
                "block": "pre_computation",
                "code": "score = 1",
                "input_map": {},
                "output_variable_path": None,
                "libraries": [],
            }
        ],
    }


def _missing_credentials(**kwargs):
    # What litellm raises for an OpenAI model called with no key in params or environment.
    raise litellm.InternalServerError(
        message="OpenAIException - Missing credentials.",
        llm_provider="openai",
        model=kwargs["model"],
    )


def _chunk(content, finish_reason):
    delta = SimpleNamespace(content=content, tool_calls=None, reasoning_content=None)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def _answering(text="Sets the score."):
    """A stand-in for `litellm.acompletion` whose model explains the block as `text`."""

    async def answer(**kwargs):
        content = json.dumps({"explanations": [{"id": BLOCK_ID, "text": text}]})

        async def stream():
            yield _chunk(content, None)
            yield _chunk(None, "stop")

        return stream()

    return answer


@pytest.fixture
def graph_acme(acme):
    return Graph.objects.create(name="flow-acme-explain", metadata={}, org=acme)


@pytest.fixture
def cdt_node(graph_acme):
    return ClassificationDecisionTableNode.objects.create(graph=graph_acme, node_name="classify")


@pytest.fixture
def openai_model(db):
    provider, _ = Provider.objects.get_or_create(name="openai")
    return LLMModel.objects.create(name=MODEL_NAME, llm_provider=provider)


@pytest.fixture
def config_without_key(acme, openai_model):
    return LLMConfig.objects.create(custom_name="no-key", model=openai_model, org=acme)


@pytest.fixture
def config_with_key(acme, openai_model):
    secret = secret_service.create(text="sk-cdt-explain", org=acme, name="cdt-explain-key")
    return LLMConfig.objects.create(
        custom_name="with-key", model=openai_model, org=acme, api_key_secret=secret
    )


@pytest.fixture
def acme_client(client_as, acme, admin_acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.mark.django_db
def test_failing_calls_with_no_api_key_return_the_missing_key_code(
    acme_client, cdt_node, config_without_key
):
    with mock.patch("litellm.acompletion", side_effect=_missing_credentials) as acompletion:
        response = acme_client.post(_url(cdt_node.id), _body(config_without_key.id), format="json")

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, response.content
    body = response.json()
    assert body["code"] == "cdt_explain_llm_config_missing_key"
    assert f"LLM config {config_without_key.id} has no API key" in body["message"]
    assert "api_key" not in acompletion.call_args.kwargs


@pytest.mark.django_db
def test_failing_calls_with_an_api_key_stay_upstream_failed(
    acme_client, cdt_node, config_with_key
):
    with mock.patch("litellm.acompletion", side_effect=_missing_credentials) as acompletion:
        response = acme_client.post(_url(cdt_node.id), _body(config_with_key.id), format="json")

    assert response.status_code == status.HTTP_502_BAD_GATEWAY, response.content
    assert response.json()["code"] == "cdt_explain_upstream_failed"
    assert acompletion.call_args.kwargs["api_key"] == "sk-cdt-explain"


@pytest.mark.django_db
def test_ollama_config_with_no_api_key_explains(acme_client, cdt_node, acme):
    provider, _ = Provider.objects.get_or_create(name="ollama")
    model = LLMModel.objects.create(
        name="llama3", llm_provider=provider, base_url="http://ollama:11434"
    )
    ollama_config = LLMConfig.objects.create(custom_name="local", model=model, org=acme)

    with mock.patch("litellm.acompletion", side_effect=_answering()) as acompletion:
        response = acme_client.post(_url(cdt_node.id), _body(ollama_config.id), format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {
        "explanations": [{"id": BLOCK_ID, "text": "Sets the score.", "generated_by": "llama3"}],
        "failures": [],
    }
    assert acompletion.call_args.kwargs["model"] == "ollama/llama3"
    assert "api_key" not in acompletion.call_args.kwargs


@pytest.mark.django_db
def test_generated_by_is_clamped_to_the_stored_explanation_limit(acme_client, cdt_node, acme):
    provider, _ = Provider.objects.get_or_create(name="openai")
    model = LLMModel.objects.create(name="m" * (MAX_GENERATED_BY_LENGTH + 45), llm_provider=provider)
    config = LLMConfig.objects.create(custom_name="long-name", model=model, org=acme)

    with mock.patch("litellm.acompletion", side_effect=_answering()):
        response = acme_client.post(_url(cdt_node.id), _body(config.id), format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["explanations"][0]["generated_by"] == "m" * MAX_GENERATED_BY_LENGTH


@pytest.mark.django_db
def test_llm_config_of_another_org_returns_404_without_calling_the_provider(
    acme_client, cdt_node, beta, openai_model
):
    beta_config = LLMConfig.objects.create(custom_name="beta-config", model=openai_model, org=beta)

    with mock.patch("litellm.acompletion", side_effect=_answering()) as acompletion:
        response = acme_client.post(_url(cdt_node.id), _body(beta_config.id), format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert response.json()["code"] == "cdt_explain_llm_config_not_found"
    acompletion.assert_not_called()


@pytest.mark.django_db
def test_nonexistent_llm_config_returns_404(acme_client, cdt_node):
    with mock.patch("litellm.acompletion", side_effect=_answering()) as acompletion:
        response = acme_client.post(_url(cdt_node.id), _body(999_999_999), format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert response.json()["code"] == "cdt_explain_llm_config_not_found"
    acompletion.assert_not_called()


@pytest.mark.django_db
def test_node_of_another_org_returns_404(acme_client, beta, config_without_key):
    beta_graph = Graph.objects.create(name="flow-beta-explain", metadata={}, org=beta)
    beta_node = ClassificationDecisionTableNode.objects.create(graph=beta_graph, node_name="b")

    with mock.patch("litellm.acompletion", side_effect=_answering()) as acompletion:
        response = acme_client.post(_url(beta_node.id), _body(config_without_key.id), format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert response.json()["code"] == "classification_decision_table_node_not_found"
    acompletion.assert_not_called()


@pytest.mark.django_db
def test_generated_text_is_clamped_to_the_stored_explanation_limit(
    acme_client, cdt_node, config_without_key
):
    long_text = "t" * (MAX_EXPLANATION_TEXT_LENGTH + 10)

    with mock.patch("litellm.acompletion", side_effect=_answering(long_text)):
        response = acme_client.post(_url(cdt_node.id), _body(config_without_key.id), format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json()["explanations"][0]["text"] == "t" * MAX_EXPLANATION_TEXT_LENGTH


@pytest.mark.django_db
def test_a_non_string_text_from_the_model_is_reported_as_a_failure(
    acme_client, cdt_node, config_without_key
):
    with mock.patch("litellm.acompletion", side_effect=_answering(12345)):
        response = acme_client.post(_url(cdt_node.id), _body(config_without_key.id), format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.json() == {
        "explanations": [],
        "failures": [{"id": BLOCK_ID, "detail": "No explanation was generated for this step."}],
    }
