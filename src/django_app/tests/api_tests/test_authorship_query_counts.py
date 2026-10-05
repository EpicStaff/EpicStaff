"""Rendering `created_by` / `last_edited_by` costs no query per row on any list endpoint.

Every row is authored and last-edited by a different user than its neighbours, so a
missing prefetch shows up as one `rbac_user` (or `rbac_resourcelastedit`) query per row.
"""

from collections.abc import Callable
from dataclasses import dataclass
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from agents.models import AgentDefinition, Surface
from rbac.authorship import record_last_edit
from rbac.models import OrganizationUser
from tables.models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    DecisionTableNode,
    ElevenLabsRealtimeConfig,
    EmbeddingConfig,
    EmbeddingModel,
    EndNode,
    FileExtractorNode,
    GeminiRealtimeConfig,
    Graph,
    GraphNote,
    KnowledgeNode,
    LLMConfig,
    LLMModel,
    McpTool,
    OpenAIRealtimeConfig,
    Provider,
    PythonCode,
    PythonCodeTool,
    PythonCodeToolConfig,
    PythonNode,
    RealtimeChannel,
    RealtimeConfig,
    RealtimeModel,
    RealtimeSessionItem,
    RealtimeTranscriptionConfig,
    RealtimeTranscriptionModel,
    ScheduleTriggerNode,
    Secret,
    SourceCollection,
    StartNode,
    StorageFile,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    TwilioChannel,
    WebhookTrigger,
    WebhookTriggerNode,
)
from tables.services.secrets import secret_encryption
from tables.services.storage_service.manager import StorageManager
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

USER_TABLE = 'FROM "rbac_user"'
LAST_EDIT_TABLE = 'FROM "rbac_resourcelastedit"'
# One query loads every author of one authored relation; editors arrive joined to
# their last edit.
MAX_USER_QUERIES = 1


@dataclass(frozen=True)
class RowFactory:
    """Creates row `index` of one list endpoint and the nested rows it renders."""

    org: object
    provider: Provider
    authors: list
    editors: list

    def author(self, index: int):
        return self.authors[index]

    def edit(self, row, index: int):
        record_last_edit(row, self.editors[index])
        return row

    def graph(self, index: int) -> Graph:
        return Graph.objects.create(name=f"query-count-flow-{index}", org=self.org)

    def edited_graph(self, index: int) -> Graph:
        return self.edit(
            Graph.objects.create(
                name=f"query-count-subflow-{index}", org=self.org, created_by=self.author(index)
            ),
            index,
        )

    def edited_webhook_trigger(self, index: int) -> WebhookTrigger:
        return self.edit(
            WebhookTrigger.objects.create(
                path=f"query-count-hook-{index}", org=self.org, created_by=self.author(index)
            ),
            index,
        )

    def node(self, model, index: int, **fields):
        return self.edit(
            model.objects.create(graph=self.graph(index), created_by=self.author(index), **fields),
            index,
        )

    def python_code(self) -> PythonCode:
        return PythonCode.objects.create(code="def main(): return 1", entrypoint="main")


def _python_code_tool(factory: RowFactory, index: int) -> PythonCodeTool:
    return PythonCodeTool.objects.create(
        name=f"query-count-tool-{index}",
        description="tool",
        python_code=factory.python_code(),
        org=factory.org,
        created_by=factory.author(index),
    )


def _secret(factory: RowFactory, index: int) -> Secret:
    secret = Secret(
        org=factory.org, name=f"query-count-secret-{index}", created_by=factory.author(index)
    )
    secret_encryption.encrypt(text="value").write_to(secret)
    secret.save()
    return secret


def _realtime_channel(factory: RowFactory, index: int) -> RealtimeChannel:
    channel = factory.edit(
        RealtimeChannel.objects.create(
            name=f"query-count-channel-{index}", org=factory.org, created_by=factory.author(index)
        ),
        index,
    )
    TwilioChannel.objects.create(
        channel=channel,
        account_sid=f"AC{index}",
        webhook_trigger=factory.edited_webhook_trigger(index),
    )
    return channel


def _owned(model, name_field: str, name: str, *, edited: bool = True, **fields):
    def make(factory: RowFactory, index: int):
        row = model.objects.create(
            org=factory.org,
            created_by=factory.author(index),
            **{name_field: f"{name}-{index}"},
            **fields,
        )
        return factory.edit(row, index) if edited else row

    return make


def _custom_model(model, provider_field: str, name: str):
    def make(factory: RowFactory, index: int):
        return model.objects.create(
            name=f"{name}-{index}",
            org=factory.org,
            is_custom=True,
            created_by=factory.author(index),
            **{provider_field: factory.provider},
        )

    return make


def _with_model(config_model, model_field: str, model, name: str):
    def make(factory: RowFactory, index: int):
        return config_model.objects.create(
            custom_name=f"{name}-{index}",
            org=factory.org,
            created_by=factory.author(index),
            **{
                model_field: model.objects.create(
                    name=f"{name}-model-{index}", provider=factory.provider
                )
            },
        )

    return make


def _node(model, **fields):
    def make(factory: RowFactory, index: int):
        return factory.node(model, index, **fields)

    return make


@dataclass(frozen=True)
class ListCase:
    basename: str
    make_row: Callable[[RowFactory, int], object]
    # What the list already loads per row besides authorship. When set, only the
    # rbac_user and rbac_resourcelastedit counts are compared, not the total.
    unrelated_per_row: str = ""
    id_field: str = "id"
    # Authored relations each row renders (the row itself, plus a nested trigger or
    # subflow); each loads its authors in one query.
    authored_relations: int = 1


NODE_GRAPH = "the node's graph"


LIST_CASES = [
    ListCase("llmmodel", _custom_model(LLMModel, "llm_provider", "query-count-llm")),
    ListCase(
        "llmconfig",
        _owned(LLMConfig, "custom_name", "query-count-llm-config"),
        unrelated_per_row="tags",
    ),
    ListCase(
        "embeddingmodel",
        _custom_model(EmbeddingModel, "embedding_provider", "query-count-embedding"),
    ),
    ListCase(
        "embeddingconfig",
        _owned(EmbeddingConfig, "custom_name", "query-count-embedding-config"),
        unrelated_per_row="tags",
    ),
    ListCase(
        "pythoncodetool",
        lambda factory, index: factory.edit(_python_code_tool(factory, index), index),
        unrelated_per_row="labels",
    ),
    ListCase(
        "pythoncodetoolconfig",
        lambda factory, index: PythonCodeToolConfig.objects.create(
            name=f"query-count-tool-config-{index}",
            tool=_python_code_tool(factory, index),
            org=factory.org,
            created_by=factory.author(index),
        ),
    ),
    ListCase(
        "graphs",
        _owned(Graph, "name", "query-count-graph"),
        unrelated_per_row="labels and the deferred metadata column",
    ),
    ListCase(
        "graphs-light",
        _owned(Graph, "name", "query-count-light-graph"),
        unrelated_per_row="labels and the columns outside only()",
    ),
    ListCase(
        "pythonnode",
        lambda factory, index: factory.node(
            PythonNode, index, node_name=f"py-{index}", python_code=factory.python_code()
        ),
        unrelated_per_row="the node's graph, python code and its secrets",
    ),
    ListCase(
        "fileextractornode",
        _node(FileExtractorNode, node_name="extract"),
        unrelated_per_row=NODE_GRAPH,
    ),
    ListCase(
        "knowledgenode", _node(KnowledgeNode, node_name="knowledge"), unrelated_per_row=NODE_GRAPH
    ),
    ListCase(
        "audiotranscriptionnode",
        _node(AudioTranscriptionNode, node_name="transcribe"),
        unrelated_per_row=NODE_GRAPH,
    ),
    ListCase("tasknode", _node(TaskNode, node_name="task"), unrelated_per_row=NODE_GRAPH),
    ListCase("agentnode", _node(AgentNode, node_name="agent"), unrelated_per_row=NODE_GRAPH),
    ListCase("startnode", _node(StartNode, variables={}), unrelated_per_row=NODE_GRAPH),
    ListCase("endnode", _node(EndNode, output_map={}), unrelated_per_row=NODE_GRAPH),
    ListCase(
        "subgraphnode",
        lambda factory, index: factory.node(
            SubGraphNode, index, node_name="sub", subgraph=factory.edited_graph(index)
        ),
        unrelated_per_row="the node's graph and the subflow's tags and labels",
        authored_relations=2,
    ),
    ListCase(
        "decisiontablenode",
        _node(DecisionTableNode, node_name="decide"),
        unrelated_per_row="the node's graph and condition groups",
    ),
    ListCase(
        "classificationdecisiontablenode",
        _node(ClassificationDecisionTableNode, node_name="classify"),
        unrelated_per_row="condition groups and prompts",
    ),
    ListCase(
        "webhooktriggernode",
        lambda factory, index: factory.node(
            WebhookTriggerNode,
            index,
            node_name="hook",
            python_code=factory.python_code(),
            webhook_trigger=factory.edited_webhook_trigger(index),
        ),
        unrelated_per_row="python code, its secrets and the trigger's auth",
        authored_relations=2,
    ),
    ListCase(
        "telegramtriggernode",
        lambda factory, index: factory.node(
            TelegramTriggerNode,
            index,
            node_name="telegram",
            webhook_trigger=factory.edited_webhook_trigger(index),
        ),
        unrelated_per_row="the trigger's auth",
        authored_relations=2,
    ),
    ListCase("scheduletriggernode", _node(ScheduleTriggerNode, node_name="nightly")),
    ListCase("graphnote", _node(GraphNote, content="note"), unrelated_per_row=NODE_GRAPH),
    ListCase("realtimemodel", _custom_model(RealtimeModel, "provider", "query-count-realtime")),
    ListCase(
        "realtimeconfig",
        _with_model(RealtimeConfig, "realtime_model", RealtimeModel, "query-count-rt-config"),
        unrelated_per_row="the realtime model, its provider and tags",
    ),
    ListCase(
        "realtimetranscriptionmodel",
        _custom_model(RealtimeTranscriptionModel, "provider", "query-count-transcription"),
    ),
    ListCase(
        "realtimetranscriptionconfig",
        _with_model(
            RealtimeTranscriptionConfig,
            "realtime_transcription_model",
            RealtimeTranscriptionModel,
            "query-count-transcription-config",
        ),
        unrelated_per_row="tags",
    ),
    ListCase(
        "realtimesessionitem",
        _owned(
            RealtimeSessionItem, "connection_key", "query-count-connection", edited=False, data={}
        ),
    ),
    ListCase(
        "openairealtimeconfig",
        _owned(OpenAIRealtimeConfig, "custom_name", "query-count-openai", edited=False),
    ),
    ListCase(
        "elevenlabsrealtimeconfig",
        _owned(ElevenLabsRealtimeConfig, "custom_name", "query-count-elevenlabs", edited=False),
    ),
    ListCase(
        "geminirealtimeconfig",
        _owned(GeminiRealtimeConfig, "custom_name", "query-count-gemini", edited=False),
    ),
    ListCase(
        "realtimechannel",
        _realtime_channel,
        unrelated_per_row="the webhook trigger's auth",
        authored_relations=2,
    ),
    ListCase(
        "mcptool",
        _owned(
            McpTool,
            "name",
            "query-count-mcp",
            transport="http://mcp.example.com/sse",
            tool_name="search",
        ),
        unrelated_per_row="labels",
    ),
    ListCase("webhooktrigger", _owned(WebhookTrigger, "path", "query-count-trigger")),
    ListCase("secret", _secret),
    ListCase("agentdefinition", _owned(AgentDefinition, "name", "query-count-agent")),
    ListCase("surface", _owned(Surface, "name", "query-count-surface")),
    ListCase(
        "sourcecollection",
        _owned(SourceCollection, "collection_name", "query-count-collection"),
        unrelated_per_row="RAG configurations",
        id_field="collection_id",
    ),
]


@pytest.fixture
def org_users(db, default_org, org_admin_role, regular_user):
    users = [regular_user]
    for index in (1, 2):
        user = get_user_model().objects.create_user(
            email=f"query-count-user-{index}@example.com", password="QueryCountStrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=default_org, role=org_admin_role)
        users.append(user)
    return users


@pytest.fixture
def row_factory(default_org, org_users) -> RowFactory:
    provider, _ = Provider.objects.get_or_create(name="query-count-provider")
    # Row i is authored by users[i] and last edited by users[i + 1], so no two rows
    # share an author or an editor.
    return RowFactory(
        org=default_org,
        provider=provider,
        authors=org_users,
        editors=org_users[1:] + org_users[:1],
    )


@pytest.fixture
def member_client(regular_user, default_org) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=regular_user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@dataclass(frozen=True)
class QueryCounts:
    total: int
    user: int
    last_edit: int


def _list_query_counts(client, case: ListCase, expected_ids: set[int]) -> QueryCounts:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(reverse(f"{case.basename}-list"), {"limit": 1000})
    assert response.status_code == status.HTTP_200_OK, response.content
    rows = response.data["results"] if isinstance(response.data, dict) else response.data
    assert expected_ids <= {row[case.id_field] for row in rows}
    sql = [query["sql"] for query in captured.captured_queries]
    return QueryCounts(
        total=len(sql),
        user=sum(USER_TABLE in statement for statement in sql),
        last_edit=sum(LAST_EDIT_TABLE in statement for statement in sql),
    )


@pytest.mark.django_db
@pytest.mark.parametrize("case", LIST_CASES, ids=lambda case: case.basename)
def test_list_renders_authorship_without_a_query_per_row(
    case, row_factory, member_client, record_property
):
    created_ids = {case.make_row(row_factory, 0).pk}
    one_row = _list_query_counts(member_client, case, created_ids)

    created_ids |= {case.make_row(row_factory, index).pk for index in (1, 2)}
    three_rows = _list_query_counts(member_client, case, created_ids)

    record_property("query_counts", {"one_row": one_row, "three_rows": three_rows})
    assert three_rows.user == one_row.user <= MAX_USER_QUERIES * case.authored_relations
    assert three_rows.last_edit == one_row.last_edit
    if not case.unrelated_per_row:
        assert three_rows.total == one_row.total


@dataclass(frozen=True)
class StorageCase:
    url: str
    # Query parameters for the endpoint, given the ids of the files it should render.
    params: Callable[[list[int]], dict]


STORAGE_CASES = {
    "list": StorageCase("/api/storage/list/", lambda ids: {"path": "docs"}),
    "tree": StorageCase("/api/storage/tree/", lambda ids: {"path": ""}),
    "search": StorageCase("/api/storage/search/", lambda ids: {"q": "query-count"}),
    "info": StorageCase("/api/storage/info/", lambda ids: {"path": "docs/query-count-0.txt"}),
    "files-by-ids": StorageCase(
        "/api/storage/files/", lambda ids: {"ids": ",".join(str(file_id) for file_id in ids)}
    ),
}


def _storage_file(factory: RowFactory, index: int) -> StorageFile:
    name = f"query-count-{index}.txt"
    return factory.edit(
        StorageFile.objects.create(
            org=factory.org,
            path=f"docs/{name}",
            name=name,
            parent_path="docs/",
            size=1,
            created_by=factory.author(index),
        ),
        index,
    )


def _storage_query_counts(client, case: StorageCase, file_ids: list[int]) -> QueryCounts:
    with CaptureQueriesContext(connection) as captured:
        response = client.get(case.url, case.params(file_ids))
    assert response.status_code == status.HTTP_200_OK, response.content
    sql = [query["sql"] for query in captured.captured_queries]
    return QueryCounts(
        total=len(sql),
        user=sum(USER_TABLE in statement for statement in sql),
        last_edit=sum(LAST_EDIT_TABLE in statement for statement in sql),
    )


@pytest.fixture
def in_memory_storage():
    manager = StorageManager(InMemoryStorageBackend(organization_prefix=""))
    with patch("tables.views.storage_views.get_storage_manager", return_value=manager):
        yield manager


@pytest.mark.django_db
@pytest.mark.parametrize("endpoint", sorted(STORAGE_CASES))
def test_storage_renders_authors_and_editors_in_one_user_query(
    endpoint, row_factory, member_client, in_memory_storage, record_property
):
    case = STORAGE_CASES[endpoint]
    StorageFile.objects.create(
        org=row_factory.org, path="docs/", name="docs", item_type="folder", parent_path=""
    )
    file_ids = [_storage_file(row_factory, 0).pk]
    one_file = _storage_query_counts(member_client, case, file_ids)

    file_ids += [_storage_file(row_factory, index).pk for index in (1, 2)]
    three_files = _storage_query_counts(member_client, case, file_ids)

    record_property("query_counts", {"one_file": one_file, "three_files": three_files})
    assert three_files.user == one_file.user == MAX_USER_QUERIES
    assert three_files.total == one_file.total
