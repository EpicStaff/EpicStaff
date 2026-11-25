"""A node file goes through the same version conversions as a full export.

Node files written before they carried a version can come from any earlier release, so
one without a version is converted from version 1, and every conversion must leave
entries already in a newer shape as they are. A node file now carries the version it
was written in.
"""

import copy
import json
from pathlib import Path

import pytest
from agents.models import SurfaceMcpTool, ToolMode
from ai_models.models import LLMConfig, LLMModel, Provider
from django.urls import reverse
from rest_framework import status
from rest_framework.exceptions import ValidationError

from tables.import_export.constants import IMPORT_VERSION
from tables.import_export.enums import EntityType
from tables.import_export.preparation import convert_to_current_version
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import (
    Graph,
    KnowledgeNode,
    McpTool,
    PythonCode,
    PythonCodeTool,
    PythonNode,
    StartNode,
    WebhookTrigger,
    WebhookTriggerNode,
)
from tables.models.graph_models import ClassificationDecisionTableNode
from tests.helpers import UNRESTRICTED_EXPORT_POLICY, data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

pytestmark = pytest.mark.django_db

# A classification decision table copied out of a flow on release 1.5.2, as that
# release wrote it: no version, and its LLM config and model still carry the setting
# and endpoint columns that later moved into `parameters` and `connection`.
RELEASE_1_5_2_NODE_FILE = (
    Path(__file__).parent / "fixtures" / "classification_decision_table_node_release_1_5_2.json"
)

CURRENT_PARAMETERS = {"temperature": 0.7, "max_tokens": 512}
CURRENT_CONNECTION = {"base_url": "https://gateway.example/v1"}


def _release_1_5_2_node_file() -> dict:
    return json.loads(RELEASE_1_5_2_NODE_FILE.read_text(encoding="utf-8"))


@pytest.fixture
def built_in_model():
    """The built-in model the release 1.5.2 file names, as every instance's catalog has it."""
    return LLMModel.objects.create(
        name="gpt-4o-mini",
        llm_provider=Provider.objects.get_or_create(name="openai")[0],
        predefined=True,
        is_custom=False,
        org=None,
    )


@pytest.fixture
def target(acme):
    graph = Graph.objects.create(name="Target", org=acme)
    StartNode.objects.create(graph=graph, variables={})
    return graph


def _partial_import(client_as, user, org, graph, data):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client.post(
        reverse("graphs-partial-import", args=[graph.id]),
        {"file": data_to_json_file(data=data, filename="nodes.json")},
        format="multipart",
    )


@pytest.fixture
def current_node_file(acme):
    """A node file of this release: a decision table whose LLM config holds settings
    and an endpoint, and a python node, as the node export writes them."""
    source = Graph.objects.create(name="Source", org=acme)
    model = LLMModel.objects.create(
        name="current-shape-model",
        llm_provider=Provider.objects.get_or_create(name="openai")[0],
        is_custom=True,
        org=acme,
    )
    llm_config = LLMConfig.objects.create(
        custom_name="current-shape-config",
        model=model,
        parameters=CURRENT_PARAMETERS,
        connection=CURRENT_CONNECTION,
        org=acme,
    )
    classifier = ClassificationDecisionTableNode.objects.create(
        graph=source, node_name="Classifier", default_llm_config=llm_config
    )
    python_node = PythonNode.objects.create(
        graph=source,
        node_name="Order #20240101",
        python_code=PythonCode.objects.create(code="def main(): ...", entrypoint="main"),
    )
    result = GraphPartialExportService(entity_registry).export(
        [
            NodeRef(
                entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE, node_id=classifier.id
            ),
            NodeRef(entity_type=EntityType.PYTHON_NODE, node_id=python_node.id),
        ],
        org_id=acme.id,
        policy=UNRESTRICTED_EXPORT_POLICY,
    )
    assert not result.has_errors, result.errors
    return result.data


def test_node_export_writes_the_current_version(current_node_file):
    assert current_node_file["version"] == IMPORT_VERSION


def test_a_release_1_5_2_node_file_imports_with_its_llm_settings(
    client_as, admin_acme, acme, target, built_in_model
):
    response = _partial_import(client_as, admin_acme, acme, target, _release_1_5_2_node_file())

    assert response.status_code == status.HTTP_200_OK, response.content
    [classifier] = response.data["content"]["classification_decision_table_node_list"]
    assert classifier["node_name"] == "normalize_and_route"
    config = LLMConfig.objects.get(pk=classifier["default_llm_config"])
    assert config.org_id == acme.id
    assert config.model_id == built_in_model.id
    assert config.parameters["temperature"] == 0.3
    assert config.parameters["max_tokens"] == 2000


def test_a_release_1_5_2_node_file_imported_twice_reuses_its_llm_config(
    acme, target, built_in_model
):
    service = PartialImportService(entity_registry)

    first = service.import_data(_release_1_5_2_node_file(), target, org_id=acme.id)
    second = service.import_data(_release_1_5_2_node_file(), target, org_id=acme.id)

    [first_node] = first.content["classification_decision_table_node_list"]
    [second_node] = second.content["classification_decision_table_node_list"]
    assert first_node["default_llm_config"] == second_node["default_llm_config"]


def test_the_whole_conversion_chain_leaves_a_current_node_file_unchanged(current_node_file):
    unversioned = {key: value for key, value in current_node_file.items() if key != "version"}

    converted = convert_to_current_version(copy.deepcopy(unversioned))

    assert converted == {**unversioned, "version": IMPORT_VERSION}


def test_the_whole_conversion_chain_leaves_a_current_agent_node_file_unchanged(
    exportable_graph_with_agent_node, default_org
):
    """An agent node brings its agent definition, LLM config, surface and its python
    and MCP tools; a webhook trigger node its python code and trigger. A knowledge
    node is in the file too, without its collection and embedder: a node file never
    carries a source collection, so no node file holds an EmbeddingConfig, and no node
    reaches a realtime config."""
    graph = exportable_graph_with_agent_node
    agent_node = graph.agent_node_list.get()
    surface = agent_node.agent_definition.owned_surfaces.get()
    mcp_tool = McpTool.objects.create(
        org=default_org, name="search-mcp", transport="https://example.com/mcp", tool_name="search"
    )
    SurfaceMcpTool.objects.create(surface=surface, mcp_tool=mcp_tool, mode=ToolMode.ALLOW)
    webhook_node = WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="On order #7",
        webhook_trigger=WebhookTrigger.objects.create(path="orders", org=default_org),
        python_code=PythonCode.objects.create(code="def main(body): ...", entrypoint="main"),
    )
    knowledge_node = KnowledgeNode.objects.create(graph=graph, node_name="Docs", query="q")
    result = GraphPartialExportService(entity_registry).export(
        [
            NodeRef(entity_type=EntityType.AGENT_NODE, node_id=agent_node.id),
            NodeRef(entity_type=EntityType.WEBHOOK_TRIGGER_NODE, node_id=webhook_node.id),
            NodeRef(entity_type=EntityType.KNOWLEDGE_NODE, node_id=knowledge_node.id),
        ],
        org_id=default_org.id,
        policy=UNRESTRICTED_EXPORT_POLICY,
    )
    assert not result.has_errors, result.errors
    unversioned = {key: value for key, value in result.data.items() if key != "version"}
    assert {
        EntityType.PYTHON_CODE_TOOL,
        EntityType.MCP_TOOL,
        EntityType.LLM_CONFIG,
        EntityType.WEBHOOK_TRIGGER,
        EntityType.WEBHOOK_TRIGGER_NODE,
        EntityType.KNOWLEDGE_NODE,
    } <= unversioned.keys()
    [exported_webhook_node] = unversioned[EntityType.WEBHOOK_TRIGGER_NODE]
    assert exported_webhook_node["python_code"]["code"] == "def main(body): ..."

    converted = convert_to_current_version(copy.deepcopy(unversioned))

    assert converted == {**unversioned, "version": IMPORT_VERSION}


def test_an_unversioned_current_node_file_keeps_its_llm_settings(current_node_file, beta):
    unversioned = {key: value for key, value in current_node_file.items() if key != "version"}
    target = Graph.objects.create(name="Other org target", org=beta)

    result = PartialImportService(entity_registry).import_data(
        unversioned, target, org_id=beta.id
    )

    [classifier] = result.content["classification_decision_table_node_list"]
    config = LLMConfig.objects.get(pk=classifier["default_llm_config"])
    assert config.org_id == beta.id
    assert config.parameters == CURRENT_PARAMETERS
    assert config.connection == CURRENT_CONNECTION
    [python_node] = result.content["python_node_list"]
    # The "#N" badge move of old files must not take a number off a current name.
    assert python_node["node_name"] == "Order #20240101"


def test_a_node_file_with_a_version_is_converted_from_that_version(
    acme, target, built_in_model
):
    node_file = _release_1_5_2_node_file()
    node_file["version"] = 5

    result = PartialImportService(entity_registry).import_data(node_file, target, org_id=acme.id)

    [classifier] = result.content["classification_decision_table_node_list"]
    config = LLMConfig.objects.get(pk=classifier["default_llm_config"])
    assert config.parameters["temperature"] == 0.3


def test_an_unversioned_node_file_from_before_node_numbers_gets_its_badge_moved(acme, target):
    node_file = {
        EntityType.PYTHON_NODE: [
            {
                "id": 1,
                "node_name": "Fetch #4",
                "metadata": {"nodeNumber": 4, "position": {"x": 0, "y": 0}},
                "python_code": {"code": "def main(): ...", "entrypoint": "main"},
                "input_map": {},
                "output_variable_path": None,
            }
        ]
    }

    result = PartialImportService(entity_registry).import_data(node_file, target, org_id=acme.id)

    [python_node] = result.content["python_node_list"]
    assert python_node["node_name"] == "Fetch"
    assert "nodeNumber" not in python_node["metadata"]


@pytest.mark.parametrize(
    ("version", "message"),
    [
        (IMPORT_VERSION + 1, f"newer than supported {IMPORT_VERSION}"),
        ("5", 'whole number, got "5"'),
        (True, "whole number, got true"),
        (0, "File version 0 is older than the first export version 1"),
        (-1, "File version -1 is older than the first export version 1"),
    ],
)
def test_a_node_file_with_an_unsupported_version_is_refused_cleanly(
    client_as, admin_acme, acme, target, version, message
):
    node_file = _release_1_5_2_node_file()
    node_file["version"] = version

    response = _partial_import(client_as, admin_acme, acme, target, node_file)

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert message in response.json()["message"]
    assert not LLMConfig.objects.filter(org=acme).exists()


def _with_python_node(node_file: dict, **node_fields) -> dict:
    node = {"id": 1, "node_name": "fetch", "metadata": {}, "input_map": {}, **node_fields}
    return {**node_file, EntityType.PYTHON_NODE: [node]}


def _with_llm_config_fields(node_file: dict, **fields) -> dict:
    [config] = node_file[EntityType.LLM_CONFIG]
    return {**node_file, EntityType.LLM_CONFIG: [{**config, **fields}]}


def _with_classifier_fields(node_file: dict, **fields) -> dict:
    [classifier] = node_file[EntityType.CLASSIFICATION_DECISION_TABLE_NODE]
    return {**node_file, EntityType.CLASSIFICATION_DECISION_TABLE_NODE: [{**classifier, **fields}]}


def _with_version_1_tool(node_file: dict, args_schema: dict) -> dict:
    tool = {
        "id": 1,
        "name": "search",
        "args_schema": args_schema,
        "python_code": {"code": "def main(q): ...", "entrypoint": "main", "libraries": ""},
    }
    return {**node_file, EntityType.PYTHON_CODE_TOOL: [tool]}


# Each case crashed a version conversion before the file's shape was checked.
MALFORMED_NODE_FILES = {
    "tool entry not an object": (
        lambda node_file: {**node_file, EntityType.PYTHON_CODE_TOOL: [1]},
        "PythonCodeTool must be a list of objects",
    ),
    "python_code not an object": (
        lambda node_file: _with_python_node(node_file, python_code="def main(): pass"),
        "PythonNode 1: python_code must be an object or null",
    ),
    "parameters not an object": (
        lambda node_file: _with_llm_config_fields(node_file, parameters=["temperature"]),
        "parameters must be an object or null",
    ),
    "node entry not an object": (
        lambda node_file: {**node_file, EntityType.PYTHON_NODE: ["fetch"]},
        "PythonNode must be a list of objects",
    ),
    "node_name not text": (
        lambda node_file: _with_python_node(node_file, node_name=5),
        "PythonNode 1: node_name must be a string or null",
    ),
    "llm config model a list": (
        lambda node_file: _with_llm_config_fields(node_file, model=[]),
        "LLMConfig 2: model must not be an object or a list",
    ),
    "prompt_configs not a list": (
        lambda node_file: _with_classifier_fields(node_file, prompt_configs="x"),
        "ClassificationDecisionTableNode 139 prompt_configs must be a list of objects",
    ),
    "args_schema properties a list": (
        lambda node_file: _with_version_1_tool(node_file, {"properties": []}),
        "PythonCodeTool 1: args_schema properties must be an object of objects",
    ),
    "args_schema property not an object": (
        lambda node_file: _with_version_1_tool(node_file, {"properties": {"q": "x"}}),
        "PythonCodeTool 1: args_schema properties must be an object of objects",
    ),
    "args_schema required not a list": (
        lambda node_file: _with_version_1_tool(node_file, {"required": 5}),
        "PythonCodeTool 1: args_schema required must be a list of strings",
    ),
    "args_schema nested properties a list": (
        lambda node_file: _with_version_1_tool(
            node_file, {"properties": {"q": {"type": "object", "properties": []}}}
        ),
        "PythonCodeTool 1: args_schema properties must be an object of objects",
    ),
    "args_schema items not an object": (
        lambda node_file: _with_version_1_tool(
            node_file, {"properties": {"q": {"type": ["array", "null"], "items": "x"}}}
        ),
        "PythonCodeTool 1: args_schema property items must be an object",
    ),
    "args_schema type an object": (
        lambda node_file: _with_version_1_tool(
            node_file, {"properties": {"q": {"type": {"name": "string"}}}}
        ),
        "PythonCodeTool 1: args_schema property type must be a string or a list of strings",
    ),
    "args_schema input_type not text": (
        lambda node_file: _with_version_1_tool(
            node_file, {"properties": {"q": {"type": "string", "input_type": {}}}}
        ),
        "PythonCodeTool 1: args_schema property input_type must be a string",
    ),
    "config field data_type a list": (
        lambda node_file: {
            **_with_version_1_tool(node_file, {}),
            EntityType.PYTHON_CODE_TOOL: [
                {
                    **_with_version_1_tool(node_file, {})[EntityType.PYTHON_CODE_TOOL][0],
                    "python_code_tool_config_fields": [{"name": "key", "data_type": []}],
                }
            ],
        },
        "PythonCodeTool 1 python_code_tool_config_fields: data_type must not be an object or a list",
    ),
    "args_schema input_type unknown": (
        lambda node_file: _with_version_1_tool(
            node_file, {"properties": {"q": {"type": "string", "input_type": "secret"}}}
        ),
        "Invalid input_type 'secret' for property 'q'",
    ),
}


@pytest.mark.parametrize(
    ("malform", "message"), MALFORMED_NODE_FILES.values(), ids=MALFORMED_NODE_FILES.keys()
)
def test_a_malformed_unversioned_node_file_is_refused_and_writes_nothing(
    client_as, admin_acme, acme, target, built_in_model, malform, message
):
    response = _partial_import(
        client_as, admin_acme, acme, target, malform(_release_1_5_2_node_file())
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert message in response.json()["message"]
    assert not LLMConfig.objects.filter(org=acme).exists()
    assert not PythonCodeTool.objects.filter(org=acme).exists()
    assert not target.python_node_list.exists()


def test_a_version_below_1_is_refused_before_the_file_shape_is_checked():
    with pytest.raises(ValidationError) as error:
        convert_to_current_version({"version": 0, EntityType.PYTHON_CODE_TOOL: [1]})

    assert "File version 0 is older than the first export version 1" in str(error.value.detail)
    assert "must be a list of objects" not in str(error.value.detail)


def _nodes_nested_in_nodes(depth: int) -> dict:
    node = {"id": depth, "node_name": 5}
    for node_id in range(depth - 1, 0, -1):
        node = {"id": node_id, "node_name": 5, "nodes": [node]}
    return node


@pytest.mark.parametrize(
    ("export_data", "first_errors", "last_error"),
    [
        (
            {EntityType.PYTHON_NODE: [{"id": node_id, "node_name": 5} for node_id in range(50)]},
            [f"PythonNode {node_id}: node_name must be a string or null." for node_id in (0, 1)],
            "...and 30 more.",
        ),
        (
            {
                "version": IMPORT_VERSION,
                EntityType.GRAPH: [{"id": 1, "nodes": [_nodes_nested_in_nodes(2000)]}],
            },
            ["Flow 1 nodes 1: node_name must be a string or null."],
            None,
        ),
    ],
    ids=["many errors", "nodes nested in nodes"],
)
def test_a_file_with_many_shape_errors_gets_a_bounded_message(
    export_data, first_errors, last_error
):
    with pytest.raises(ValidationError) as error:
        convert_to_current_version(export_data)

    errors = [str(message) for message in error.value.detail["detail"]]
    assert errors[: len(first_errors)] == first_errors
    assert len(errors) <= 21
    if last_error is None:
        assert errors == first_errors
    else:
        assert errors[-1] == last_error


def test_a_version_4_tool_named_with_a_number_gets_a_venv_named_after_it():
    converted = convert_to_current_version(
        {
            "version": 4,
            EntityType.PYTHON_CODE_TOOL: [
                {
                    "id": 1,
                    "name": 5,
                    "python_code": {"code": "def main(): ...", "libraries": "requests"},
                }
            ],
        }
    )

    assert [venv["name"] for venv in converted[EntityType.VENV]] == ["5-venv"]
    assert converted[EntityType.PYTHON_CODE_TOOL][0]["python_code"]["venv"] == 1
