"""Import refuses a flow holding a template or state path crew would refuse; partial import does not."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.models import Graph
from tables.models.graph_models import (
    AgentNode,
    AgentNodeTask,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    TaskNode,
)
from tests.helpers import UNRESTRICTED_EXPORT_POLICY, data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

REFUSED_UNDERSCORE_KEY = (
    "Placeholder '{a._b}' is not allowed: '_b' starts with '_'. Rename that variable or key."
)
REFUSED_CONVERSION = (
    "Placeholder '{topic!r}' is not allowed: conversions such as '!r' are not supported. "
    "Write '{topic}'."
)


def _task_with_refused_instructions(graph):
    TaskNode.objects.create(graph=graph, node_name="Writer", instructions="Use {a._b}")
    return f"Node 'Writer' of flow 'Source', field 'instructions': {REFUSED_UNDERSCORE_KEY}"


def _agent_task_with_refused_instructions(graph):
    agent = AgentNode.objects.create(graph=graph, node_name="Helper")
    AgentNodeTask.objects.create(agent_node=agent, name="only", order=0, instructions="{topic!r}")
    return f"Node 'Helper' of flow 'Source', field 'tasks[0].instructions': {REFUSED_CONVERSION}"


def _classification_prompt_with_refused_text(graph):
    classifier = ClassificationDecisionTableNode.objects.create(graph=graph, node_name="Classifier")
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=classifier, prompt_key="rate", prompt_text="Rate {a._b}"
    )
    return (
        "Node 'Classifier' of flow 'Source', field 'prompt_configs[0].prompt_text': "
        f"{REFUSED_UNDERSCORE_KEY}"
    )


def _task_with_refused_output_path(graph):
    TaskNode.objects.create(graph=graph, node_name="Writer", output_variable_path="variables._out")
    return (
        "Node 'Writer' of flow 'Source', field 'output_variable_path': Variable path "
        "'variables._out' is not allowed: path segments cannot start with '_'."
    )


def _export_file(graph):
    export_data = (
        ExportService(entity_registry)
        .export_entities(EntityType.GRAPH, [graph.id], policy=UNRESTRICTED_EXPORT_POLICY)
        .data
    )
    return data_to_json_file(data=export_data, filename="flow.json")


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def source(acme):
    return Graph.objects.create(name="Source", org=acme)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "seed_refused_node",
    [
        pytest.param(_task_with_refused_instructions, id="task-instructions"),
        pytest.param(_agent_task_with_refused_instructions, id="agent-task-instructions"),
        pytest.param(_classification_prompt_with_refused_text, id="classification-prompt"),
        pytest.param(_task_with_refused_output_path, id="state-path"),
    ],
)
def test_an_import_with_a_run_refusal_is_a_400_and_creates_no_flow(
    acme_client, source, seed_refused_node
):
    # Saved before this check existed, then exported.
    expected_message = seed_refused_node(source)
    file = _export_file(source)
    graph_count_before = Graph.objects.count()

    response = acme_client.post(reverse("graphs-import-entity"), {"file": file}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data["message"] == expected_message
    assert Graph.objects.count() == graph_count_before


@pytest.mark.django_db
def test_an_import_with_data_paths_crew_runs_creates_the_flow(acme_client, source):
    TaskNode.objects.create(
        graph=source,
        node_name="Writer",
        instructions="Answer {context[user_input]} for {_private}",
        input_map={"context": "variables.context|none", "_private": "variables.private"},
        output_variable_path="variables.answer",
    )
    file = _export_file(source)

    response = acme_client.post(reverse("graphs-import-entity"), {"file": file}, format="multipart")

    assert response.status_code == status.HTTP_200_OK, response.content
    imported = TaskNode.objects.exclude(graph=source).get(node_name="Writer")
    assert imported.instructions == "Answer {context[user_input]} for {_private}"


@pytest.mark.django_db
def test_an_import_with_a_system_one_prompt_text_crew_never_renders_creates_the_flow(
    acme_client, source
):
    classifier = ClassificationDecisionTableNode.objects.create(graph=source, node_name="Classifier")
    ClassificationDecisionTablePrompt.objects.create(
        cdt_node=classifier,
        prompt_key="fast",
        kind=ClassificationDecisionTablePrompt.Kind.SYSTEM_ONE,
        prompt_text="{x!r}",
    )
    file = _export_file(source)

    response = acme_client.post(reverse("graphs-import-entity"), {"file": file}, format="multipart")

    assert response.status_code == status.HTTP_200_OK, response.content
    imported = ClassificationDecisionTablePrompt.objects.exclude(cdt_node__graph=source).get()
    assert (imported.kind, imported.prompt_text) == ("system_one", "{x!r}")


@pytest.mark.django_db
def test_a_partial_import_with_a_refused_placeholder_is_returned_unsaved(
    acme_client, acme, source
):
    # Not refused here: the pasted node lands unsaved on the canvas, and the next bulk save
    # refuses it on the exact field.
    node = TaskNode.objects.create(graph=source, node_name="Writer", instructions="Use {a._b}")
    export_data = (
        GraphPartialExportService(entity_registry)
        .export(
            [NodeRef(entity_type=EntityType.TASK_NODE, node_id=node.id)],
            org_id=acme.id,
            policy=UNRESTRICTED_EXPORT_POLICY,
        )
        .data
    )
    target = Graph.objects.create(name="Target", org=acme)

    response = acme_client.post(
        reverse("graphs-partial-import", args=[target.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    [pasted] = response.data["content"]["task_node_list"]
    assert pasted["instructions"] == "Use {a._b}"
    assert not TaskNode.objects.filter(graph=target).exists()
