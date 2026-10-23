"""Partial import returns the file's nodes and edges unsaved and leaves the target graph alone."""

from datetime import UTC, datetime

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from rest_framework import serializers, status

from rbac.authorship import record_last_edit
from rbac.models import ResourceLastEdit
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import (
    Graph,
    LLMConfig,
    LLMModel,
    Provider,
    PythonCode,
    PythonNode,
    StartNode,
    WebhookTrigger,
)
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    ConditionGroup,
    DecisionTableNode,
    Edge,
    ScheduleTriggerNode,
    WebhookTriggerNode,
)
from tables.serializers.model_serializers.graph_serializers import GraphSerializer
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

PREVIOUS_EDIT_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
GRAPH_LIST_FIELDS = {
    list_key: field.source or list_key
    for list_key, field in GraphSerializer._declared_fields.items()
    if isinstance(field, serializers.ListSerializer)
}


def _python_node(graph, node_name):
    return PythonNode.objects.create(
        graph=graph,
        node_name=node_name,
        python_code=PythonCode.objects.create(code="def main(): ...", entrypoint="main"),
    )


IMPORTED_LLM_CONFIG_NAME = "pasted-node-llm-config"
# post_save handlers of trigger nodes that defer work to the commit; a pasted node is
# never committed, so none of their callbacks may outlive the import.
NODE_ON_COMMIT_HANDLERS = (
    "schedule_trigger_post_save_handler.",
    "webhook_trigger_node_post_save_handler.",
)


@pytest.fixture
def export_data(acme, beta):
    """A python node, a decision table routing to it and to a node left out of the file,
    the edge between the two, and a classification decision table whose LLM config
    belongs to another org, so the import creates that config in the active org."""
    source = Graph.objects.create(name="Source", org=acme)
    llm_config = LLMConfig.objects.create(
        custom_name=IMPORTED_LLM_CONFIG_NAME,
        model=LLMModel.objects.create(
            name="pasted-node-model",
            llm_provider=Provider.objects.get_or_create(name="openai")[0],
        ),
        org=beta,
    )
    classifier = ClassificationDecisionTableNode.objects.create(
        graph=source, node_name="Classifier", default_llm_config=llm_config
    )
    python_node = _python_node(source, "Pasted python")
    left_out = _python_node(source, "Left out")
    decision_table = DecisionTableNode.objects.create(
        graph=source,
        node_name="Router",
        default_next_node_id=python_node.id,
        next_error_node_id=left_out.id,
    )
    ConditionGroup.objects.create(
        decision_table_node=decision_table,
        group_name="to python",
        group_type="simple",
        next_node_id=python_node.id,
    )
    edge = Edge.objects.create(
        graph=source, start_node_id=decision_table.id, end_node_id=python_node.id
    )
    result = GraphPartialExportService(entity_registry).export(
        [
            NodeRef(entity_type=EntityType.PYTHON_NODE, node_id=python_node.id),
            NodeRef(entity_type=EntityType.DECISION_TABLE_NODE, node_id=decision_table.id),
            NodeRef(
                entity_type=EntityType.CLASSIFICATION_DECISION_TABLE_NODE, node_id=classifier.id
            ),
        ],
        org_id=acme.id,
        edge_ids=[edge.id],
    )
    assert not result.has_errors, result.errors
    return result.data


@pytest.fixture
def target(acme, member_only):
    graph = Graph.objects.create(name="Target", org=acme)
    start = StartNode.objects.create(graph=graph, variables={})
    existing = _python_node(graph, "Existing")
    Edge.objects.create(graph=graph, start_node_id=start.id, end_node_id=existing.id)
    record_last_edit(graph, member_only, edited_at=PREVIOUS_EDIT_AT)
    return graph


def _partial_import(client_as, user, org, graph, data):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client.post(
        reverse("graphs-partial-import", args=[graph.id]),
        {"file": data_to_json_file(data=data, filename="nodes.json")},
        format="multipart",
    )


def _graph_state(graph: Graph) -> dict:
    graph.refresh_from_db()
    last_edit = ResourceLastEdit.objects.get(
        content_type=ContentType.objects.get_for_model(Graph), object_id=graph.pk
    )
    return {
        **{
            list_key: sorted(getattr(graph, relation).values_list("id", flat=True))
            for list_key, relation in GRAPH_LIST_FIELDS.items()
        },
        "node_number_seq": graph.node_number_seq,
        "save_version": graph.save_version,
        "last_edit": (last_edit.edited_by_id, last_edit.edited_at),
    }


@pytest.mark.django_db
def test_partial_import_commits_dependencies_and_leaves_the_target_graph_unchanged(
    client_as, admin_acme, acme, target, export_data
):
    state_before = _graph_state(target)

    response = _partial_import(client_as, admin_acme, acme, target, export_data)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _graph_state(target) == state_before
    imported_config = LLMConfig.objects.get(org=acme, custom_name=IMPORTED_LLM_CONFIG_NAME)
    [classifier] = response.data["content"]["classification_decision_table_node_list"]
    assert classifier["default_llm_config"] == imported_config.id


@pytest.mark.django_db
def test_partial_import_of_trigger_nodes_leaves_no_node_commit_callback(
    acme, target, django_capture_on_commit_callbacks
):
    source = Graph.objects.create(name="Trigger source", org=acme)
    webhook_node = WebhookTriggerNode.objects.create(
        graph=source,
        node_name="Incoming",
        webhook_trigger=WebhookTrigger.objects.create(path="pasted-trigger-path", org=acme),
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )
    schedule_node = ScheduleTriggerNode.objects.create(graph=source, node_name="Hourly")
    bundle = GraphPartialExportService(entity_registry).export(
        [
            NodeRef(entity_type=EntityType.WEBHOOK_TRIGGER_NODE, node_id=webhook_node.id),
            NodeRef(entity_type=EntityType.SCHEDULE_TRIGGER_NODE, node_id=schedule_node.id),
        ],
        org_id=acme.id,
    )
    assert not bundle.has_errors, bundle.errors

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        result = PartialImportService(entity_registry).import_data(
            bundle.data, target, org_id=acme.id
        )

    assert len(result.content["webhook_trigger_node_list"]) == 1
    assert len(result.content["schedule_trigger_node_list"]) == 1
    node_callbacks = [
        callback.__qualname__
        for callback in callbacks
        if callback.__qualname__.startswith(NODE_ON_COMMIT_HANDLERS)
    ]
    assert node_callbacks == []


@pytest.mark.django_db
def test_partial_import_content_is_wired_only_to_nodes_inside_it(
    client_as, admin_acme, acme, target, export_data
):
    response = _partial_import(client_as, admin_acme, acme, target, export_data)

    assert response.status_code == status.HTTP_200_OK, response.content
    content = response.data["content"]
    assert set(content) == set(GRAPH_LIST_FIELDS)
    [python_node] = content["python_node_list"]
    [decision_table] = content["decision_table_node_list"]
    assert python_node["node_name"] == "Pasted python"
    assert content["edge_list"] == [
        {
            **content["edge_list"][0],
            "start_node_id": decision_table["id"],
            "end_node_id": python_node["id"],
        }
    ]
    assert decision_table["default_next_node_id"] == python_node["id"]
    assert decision_table["next_error_node_id"] is None
    assert [group["next_node_id"] for group in decision_table["condition_groups"]] == [
        python_node["id"]
    ]
    assert content["start_node_list"] == []
    assert content["graph_note_list"] == []
