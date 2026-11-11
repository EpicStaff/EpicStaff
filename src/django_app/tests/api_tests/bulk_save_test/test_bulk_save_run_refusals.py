"""Bulk save refuses a template or state path crew would refuse at run time, writing nothing."""

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import Graph
from tables.models.graph_models import ClassificationDecisionTablePrompt, TaskNode
from tables.services.graph_bulk_save_service.registry import NODE_TYPE_REGISTRY
from tests.fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

REFUSED_UNDERSCORE_KEY = (
    "Placeholder '{a._b}' is not allowed: '_b' starts with '_'. Rename that variable or key."
)
REFUSED_CONVERSION = (
    "Placeholder '{topic!r}' is not allowed: conversions such as '!r' are not supported. "
    "Write '{topic}'."
)
_PYTHON_CODE = {"code": "def main(): return 1", "entrypoint": "main", "libraries": []}


def _refused_path(path: str) -> str:
    return f"Variable path '{path}' is not allowed: path segments cannot start with '_'."


def _save(client, graph: Graph, **node_lists):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, **node_lists},
        format="json",
    )


def _stored_state(graph: Graph) -> tuple:
    graph.refresh_from_db()
    node_counts = {
        config.list_key: config.model_class.objects.filter(graph=graph).count()
        for config in NODE_TYPE_REGISTRY
    }
    return graph.save_version, node_counts


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("list_key", "item", "expected_errors"),
    [
        pytest.param(
            "task_node_list",
            {"node_name": "Writer", "instructions": "Use {a._b}"},
            {"instructions": [REFUSED_UNDERSCORE_KEY]},
            id="task-instructions",
        ),
        pytest.param(
            "task_node_list",
            {"node_name": "Writer", "input_map": {"user": "variables._user|guest"}},
            {"input_map": [_refused_path("variables._user")]},
            id="input-map",
        ),
        pytest.param(
            "python_node_list",
            {
                "node_name": "Code",
                "python_code": _PYTHON_CODE,
                "output_variable_path": "variables._out",
            },
            {"output_variable_path": [_refused_path("variables._out")]},
            id="output-variable-path",
        ),
        pytest.param(
            "knowledge_node_list",
            {"node_name": "Search", "query": "Find {topic!r}"},
            {"query": [REFUSED_CONVERSION]},
            id="knowledge-query",
        ),
        pytest.param(
            "end_node_list",
            {"output_map": {"context": "variables.__class__"}},
            {"output_map": [_refused_path("variables.__class__")]},
            id="end-node-output-map",
        ),
        pytest.param(
            "subgraph_node_list",
            {"node_name": "Child", "output_variable_path": "variables._child"},
            {"output_variable_path": [_refused_path("variables._child")]},
            id="subflow-output-path",
        ),
        pytest.param(
            "classification_decision_table_node_list",
            {"node_name": "Classifier", "pre_output_variable_path": "variables._pre"},
            {"pre_output_variable_path": [_refused_path("variables._pre")]},
            id="classification-table-output-path",
        ),
        pytest.param(
            "classification_decision_table_node_list",
            {
                "node_name": "Classifier",
                "prompt_configs": [
                    {"prompt_key": "fine", "prompt_text": "Rate {topic}"},
                    {"prompt_key": "bad", "prompt_text": "Rate {a._b}"},
                ],
            },
            {"prompt_configs": [{}, {"prompt_text": [REFUSED_UNDERSCORE_KEY]}]},
            id="classification-prompt-text",
        ),
        pytest.param(
            "agent_node_list",
            {
                "node_name": "Helper",
                "tasks": [
                    {"name": "first", "order": 0, "instructions": "Say {topic!r}"},
                    {"name": "second", "order": 1, "instructions": "Fine {topic}"},
                ],
            },
            {"tasks": [{"instructions": [REFUSED_CONVERSION]}, {}]},
            id="agent-task-instructions",
        ),
        pytest.param(
            "telegram_trigger_node_list",
            {
                "node_name": "Bot",
                "metadata": {},
                "fields": [
                    {"parent": "message", "field_name": "text", "variable_path": "variables._text"}
                ],
            },
            {"fields": [{"variable_path": [_refused_path("variables._text")]}]},
            id="telegram-field-variable-path",
        ),
    ],
)
def test_a_refused_field_is_a_400_on_its_item_and_nothing_is_written(
    auth_client, graph, list_key, item, expected_errors
):
    state_before = _stored_state(graph)

    response = _save(auth_client, graph, **{list_key: [{"graph": graph.id, **item}]})

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {"errors": {list_key: [{"index": 0, "errors": expected_errors}]}}
    assert _stored_state(graph) == state_before


@pytest.mark.django_db
def test_the_error_carries_the_index_of_the_refused_item(auth_client, graph):
    response = _save(
        auth_client,
        graph,
        task_node_list=[
            {"graph": graph.id, "node_name": "Clean", "instructions": "{topic}"},
            {"graph": graph.id, "node_name": "Refused", "instructions": "{a._b}"},
        ],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "errors": {
            "task_node_list": [{"index": 1, "errors": {"instructions": [REFUSED_UNDERSCORE_KEY]}}]
        }
    }
    assert not TaskNode.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_a_refusal_comes_back_once_the_other_errors_of_its_item_are_fixed(auth_client, graph):
    refused_task = {"name": "second", "order": 1, "instructions": "{a._b}"}

    with_other_error = _save(
        auth_client,
        graph,
        agent_node_list=[
            {
                "graph": graph.id,
                "node_name": "Helper",
                "tasks": [{"order": 0, "instructions": "Fine"}, refused_task],
            }
        ],
    )
    fixed = _save(
        auth_client,
        graph,
        agent_node_list=[
            {
                "graph": graph.id,
                "node_name": "Helper",
                "tasks": [{"name": "first", "order": 0, "instructions": "Fine"}, refused_task],
            }
        ],
    )

    assert with_other_error.status_code == status.HTTP_400_BAD_REQUEST, with_other_error.content
    assert with_other_error.data == {
        "errors": {
            "agent_node_list": [
                {"index": 0, "errors": {"tasks": [{"name": ["This field is required."]}, {}]}}
            ]
        }
    }
    assert fixed.status_code == status.HTTP_400_BAD_REQUEST, fixed.content
    assert fixed.data == {
        "errors": {
            "agent_node_list": [
                {"index": 0, "errors": {"tasks": [{}, {"instructions": [REFUSED_UNDERSCORE_KEY]}]}}
            ]
        }
    }


@pytest.mark.django_db
def test_a_system_one_prompt_text_is_not_checked(auth_client, graph):
    # Crew receives a System One prompt with an empty prompt_text, and the editor locks it.
    response = _save(
        auth_client,
        graph,
        classification_decision_table_node_list=[
            {
                "graph": graph.id,
                "node_name": "Classifier",
                "prompt_configs": [
                    {"prompt_key": "fast", "kind": "system_one", "prompt_text": "{x!r}"}
                ],
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    prompt = ClassificationDecisionTablePrompt.objects.get(cdt_node__graph=graph)
    assert (prompt.kind, prompt.prompt_text) == ("system_one", "{x!r}")


@pytest.mark.django_db
def test_an_item_path_placeholder_saves(auth_client, graph):
    response = _save(
        auth_client,
        graph,
        task_node_list=[
            {
                "graph": graph.id,
                "node_name": "Writer",
                "instructions": "Answer {context[user_input]}",
                "input_map": {"context": "variables.context|none"},
                "output_variable_path": "variables.answer",
            }
        ],
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert TaskNode.objects.get(graph=graph).instructions == "Answer {context[user_input]}"


@pytest.mark.django_db
def test_a_stored_refused_instruction_sent_back_unchanged_is_refused(auth_client, graph):
    # Saved before this check existed; the editor sends it back untouched on the next save.
    node = TaskNode.objects.create(graph=graph, node_name="Old", instructions="Use {a._b}")
    state_before = _stored_state(graph)

    response = _save(
        auth_client,
        graph,
        task_node_list=[
            {"id": node.id, "graph": graph.id, "node_name": "Renamed", "instructions": "Use {a._b}"}
        ],
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "errors": {
            "task_node_list": [{"index": 0, "errors": {"instructions": [REFUSED_UNDERSCORE_KEY]}}]
        }
    }
    assert _stored_state(graph) == state_before
    node.refresh_from_db()
    assert node.node_name == "Old"


@pytest.mark.django_db
def test_a_refused_payload_to_another_orgs_flow_is_a_404(client_as, admin_acme, acme, beta):
    foreign_graph = Graph.objects.create(name="Beta flow", org=beta)
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    state_before = _stored_state(foreign_graph)

    response = _save(
        client,
        foreign_graph,
        task_node_list=[{"graph": foreign_graph.id, "node_name": "T", "instructions": "{a._b}"}],
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert _stored_state(foreign_graph) == state_before
