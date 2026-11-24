"""Calls to a model outside a flow pass the plugin run guard like a run of the config they use:
indexing a knowledge source, explaining a decision table, and the flow assistant's reply.

Only the model itself is replaced (`litellm.acompletion`, the knowledge_new client, the
assistant's LLM client); the views, services, admission and guard run for real.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from ai_models.models import EmbeddingConfig, LLMConfig, LLMModel, Provider
from django.test import Client
from django.urls import reverse
from plugins.models import GrantState
from rbac.identity.tickets import sse_ticket_service
from rbac.models import OrganizationUser
from tables.models.flow_assistant_models import (
    FlowAssistant,
    FlowAssistantConversation,
    FlowAssistantMessage,
)
from tables.models.graph_models import ClassificationDecisionTableNode
from tables.models.knowledge_models.collection_models import BaseRagType, DocumentMetadata, SourceCollection
from tables.models.knowledge_models.graphrag_models import GraphRag, GraphRagIndexConfig
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.services.llm_clients.base import DoneEvent, TokenEvent

from tests.plugins_tests.suspension_helpers import flow, own, secret_row, set_state

pytestmark = [pytest.mark.django_db]

BLOCK_ID = "spine:pre-computation"


@pytest.fixture
def grant(running_plugin, grant_to, acme):
    """Weather in Acme, suspended."""
    return set_state(grant_to(running_plugin(), acme), GrantState.SUSPENDED)


@pytest.fixture
def olga(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))
    return client


@pytest.fixture
def beta_grant(grant, grant_to, beta):
    """Weather in Beta too, suspended there."""
    return set_state(grant_to(grant.plugin, beta), GrantState.SUSPENDED)


def _assert_refused(status_code, body, acme):
    assert status_code == 409, body
    assert body["code"] == "plugin_suspended"
    assert (body["plugin"], body["organization"]) == ({"identifier": "weather", "name": "Weather"}, {"id": acme.pk})


def _llm_config(organization, name: str, **fields) -> LLMConfig:
    provider, _ = Provider.objects.get_or_create(name="openai")
    model = LLMModel.objects.create(name=f"{name} model", llm_provider=provider)
    return LLMConfig.objects.create(org=organization, custom_name=name, model=model, **fields)


# ---- indexing ----


@pytest.fixture
def knowledge_client(monkeypatch):
    """The HTTP client to knowledge_new, which would call the embedder and the LLM."""
    client = MagicMock()
    client.__enter__.return_value = client
    monkeypatch.setattr("tables.views.views.KnowledgeClient", lambda: client)
    return client


def _naive_rag(organization, embedder) -> NaiveRag:
    collection = SourceCollection.objects.create(org=organization, collection_name=f"Forecasts {embedder.pk}")
    DocumentMetadata.objects.create(source_collection=collection, file_name="forecast.txt")
    return NaiveRag.objects.create(
        base_rag_type=BaseRagType.objects.create(rag_type=BaseRagType.RagType.NAIVE, source_collection=collection),
        embedder=embedder,
    )


def _graph_rag(organization, embedder, llm) -> GraphRag:
    collection = SourceCollection.objects.create(org=organization, collection_name="Forecast graph")
    DocumentMetadata.objects.create(source_collection=collection, file_name="forecast.txt")
    return GraphRag.objects.create(
        base_rag_type=BaseRagType.objects.create(rag_type=BaseRagType.RagType.GRAPH, source_collection=collection),
        embedder=embedder,
        llm=llm,
        index_config=GraphRagIndexConfig.objects.create(),
    )


def _index(client, rag_type: str, rag_id: int):
    return client.post(
        "/api/process-rag-indexing/",
        {"rag_id": rag_id, "rag_type": rag_type, "document_config_ids": [1]},
        format="json",
    )


def test_indexing_with_the_plugin_s_embedder_is_refused(grant, acme, olga, knowledge_client):
    embedder = EmbeddingConfig.objects.create(org=acme, custom_name="Weather embeddings")
    own(embedder, grant)
    rag = _naive_rag(acme, embedder)

    response = _index(olga, "naive", rag.naive_rag_id)

    _assert_refused(response.status_code, response.json(), acme)
    knowledge_client.index.assert_not_called()


def test_indexing_with_an_embedder_using_the_plugin_s_secret_is_refused(grant, acme, olga, knowledge_client):
    key = secret_row(acme, "Weather · embeddings key")
    own(key, grant)
    embedder = EmbeddingConfig.objects.create(org=acme, custom_name="Acme embeddings", api_key_secret=key)

    response = _index(olga, "naive", _naive_rag(acme, embedder).naive_rag_id)

    _assert_refused(response.status_code, response.json(), acme)
    knowledge_client.index.assert_not_called()


def test_graph_indexing_with_the_plugin_s_llm_is_refused(grant, acme, olga, knowledge_client):
    llm = _llm_config(acme, "Weather extraction")
    own(llm, grant)
    embedder = EmbeddingConfig.objects.create(org=acme, custom_name="Acme embeddings")

    response = _index(olga, "graph", _graph_rag(acme, embedder, llm).graph_rag_id)

    _assert_refused(response.status_code, response.json(), acme)
    knowledge_client.index.assert_not_called()


def test_indexing_with_the_organization_s_own_configs_is_accepted(grant, acme, olga, knowledge_client):
    # The suspended plugin owns a config of the organization that this indexing does not use.
    own(EmbeddingConfig.objects.create(org=acme, custom_name="Weather embeddings"), grant)
    embedder = EmbeddingConfig.objects.create(org=acme, custom_name="Acme embeddings")
    llm = _llm_config(acme, "Acme extraction")

    naive = _index(olga, "naive", _naive_rag(acme, embedder).naive_rag_id)
    graph = _index(olga, "graph", _graph_rag(acme, embedder, llm).graph_rag_id)

    assert (naive.status_code, graph.status_code) == (202, 202), (naive.content, graph.content)
    assert knowledge_client.index.call_count == 2


def test_indexing_another_organization_s_rag_with_its_suspended_plugin_s_configs_is_not_found(
    beta_grant, beta, olga, knowledge_client
):
    # A 409 would tell Acme that Beta's RAG exists and which plugin it uses.
    embedder = EmbeddingConfig.objects.create(org=beta, custom_name="Weather embeddings")
    llm = _llm_config(beta, "Weather extraction")
    own(embedder, beta_grant)
    own(llm, beta_grant)

    naive = _index(olga, "naive", _naive_rag(beta, embedder).naive_rag_id)
    graph = _index(olga, "graph", _graph_rag(beta, embedder, llm).graph_rag_id)

    assert (naive.status_code, graph.status_code) == (404, 404), (naive.content, graph.content)
    knowledge_client.index.assert_not_called()


# ---- decision table explanations ----


def _explained(**kwargs):
    """A stand-in for `litellm.acompletion` whose model explains the block."""

    async def stream():
        content = json.dumps({"explanations": [{"id": BLOCK_ID, "text": "Sets the score."}]})
        for content_part, finish_reason in ((content, None), (None, "stop")):
            delta = SimpleNamespace(content=content_part, tool_calls=None, reasoning_content=None)
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])

    return stream()


async def _explain_model(**kwargs):
    return _explained(**kwargs)


def _explain(client, organization, llm_config):
    node = ClassificationDecisionTableNode.objects.create(graph=flow(organization, "Classify"), node_name="classify")
    body = {
        "llm_config": llm_config.pk,
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
    with patch("litellm.acompletion", side_effect=_explain_model) as model:
        response = client.post(f"/api/classification-decision-table-node/{node.pk}/explain/", body, format="json")
    return response, model


def test_explaining_with_the_plugin_s_llm_config_is_refused(grant, acme, olga):
    classifier = _llm_config(acme, "Weather classifier")
    own(classifier, grant)

    response, model = _explain(olga, acme, classifier)

    _assert_refused(response.status_code, response.json(), acme)
    model.assert_not_called()


def test_explaining_with_the_organization_s_own_llm_config_works(grant, acme, olga):
    own(_llm_config(acme, "Weather classifier"), grant)

    response, model = _explain(olga, acme, _llm_config(acme, "Acme classifier", api_key_secret=secret_row(acme, "Acme key")))

    assert response.status_code == 200, response.content
    assert [explanation["text"] for explanation in response.json()["explanations"]] == ["Sets the score."]


def test_explaining_with_another_organization_s_suspended_plugin_s_llm_config_is_not_found(
    beta_grant, acme, beta, olga
):
    classifier = _llm_config(beta, "Weather classifier")
    own(classifier, beta_grant)

    response, model = _explain(olga, acme, classifier)

    assert response.status_code == 404, response.content
    assert response.json()["code"] == "cdt_explain_llm_config_not_found"
    model.assert_not_called()


# ---- the flow assistant ----


@pytest.fixture
def llm_client():
    """The assistant's LLM client; streams one short plain-text reply."""

    async def reply(messages, tools):
        yield TokenEvent(content="hi")
        yield DoneEvent()

    client = MagicMock()
    client.stream_completion = reply
    with patch("tables.services.flow_assistant.service.get_llm_client", return_value=client) as get_llm_client:
        yield get_llm_client


def _conversation(user, organization, llm_config) -> FlowAssistantConversation:
    assistant = FlowAssistant.objects.create(graph=flow(organization, "Digest"), llm_config=llm_config)
    return FlowAssistantConversation.objects.create(
        flow_assistant=assistant, organization_user=OrganizationUser.objects.get(user=user, org=organization)
    )


def _send(client, conversation, message="what does this flow do?"):
    url = reverse(
        "flow-assistant-send-message",
        kwargs={"graph_id": conversation.flow_assistant.graph_id, "conversation_id": conversation.pk},
    )
    return client.post(url, {"message": message}, format="json")


def _stream(user, conversation):
    ticket, _ = sse_ticket_service.issue(user)
    url = reverse("flow-assistant-stream", args=[conversation.flow_assistant.graph_id, conversation.pk])
    return Client().get(url, {"ticket": ticket})


def test_asking_the_assistant_with_the_plugin_s_llm_config_is_refused_and_stores_nothing(
    grant, acme, admin_acme, olga, llm_client
):
    assistant_config = _llm_config(acme, "Weather assistant")
    own(assistant_config, grant)
    conversation = _conversation(admin_acme, acme, assistant_config)

    response = _send(olga, conversation)

    _assert_refused(response.status_code, response.json(), acme)
    assert not FlowAssistantMessage.objects.filter(conversation=conversation).exists()
    llm_client.assert_not_called()


def test_the_assistant_s_reply_is_refused_once_the_plugin_is_suspended(
    running_plugin, grant_to, acme, admin_acme, olga, llm_client
):
    grant = grant_to(running_plugin(), acme)
    assistant_config = _llm_config(acme, "Weather assistant")
    own(assistant_config, grant)
    conversation = _conversation(admin_acme, acme, assistant_config)
    assert _send(olga, conversation).status_code == 200
    # Suspended between the message and its reply.
    set_state(grant, GrantState.SUSPENDED)

    response = _stream(admin_acme, conversation)

    assert not response.streaming
    _assert_refused(response.status_code, response.json(), acme)
    llm_client.assert_not_called()


def test_the_assistant_answers_with_the_organization_s_own_llm_config(grant, acme, admin_acme, olga, llm_client):
    own(_llm_config(acme, "Weather assistant"), grant)
    conversation = _conversation(admin_acme, acme, _llm_config(acme, "Acme assistant"))

    sent = _send(olga, conversation)
    response = _stream(admin_acme, conversation)

    assert (sent.status_code, response.status_code) == (200, 200), sent.content
    assert response.streaming
    assert "hi" in b"".join(response.streaming_content).decode()
    llm_client.assert_called_once()


def test_another_organization_s_conversation_with_its_suspended_plugin_s_config_is_not_found(
    beta_grant, beta, admin_acme, olga, make_member, role_org_admin, llm_client
):
    # The assistant takes no config id when asked: its config comes with the conversation, so
    # Acme can reach Beta's suspended config only through Beta's conversation.
    beta_admin = make_member(beta, role_org_admin, "admin-beta-guard@example.com")
    assistant_config = _llm_config(beta, "Weather assistant")
    own(assistant_config, beta_grant)
    conversation = _conversation(beta_admin, beta, assistant_config)

    sent = _send(olga, conversation)
    streamed = _stream(admin_acme, conversation)

    assert (sent.status_code, streamed.status_code) == (404, 404), (sent.content, streamed.content)
    assert not streamed.streaming
    assert not FlowAssistantMessage.objects.filter(conversation=conversation).exists()
    llm_client.assert_not_called()
