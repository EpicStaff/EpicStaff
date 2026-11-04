"""What a user is told when POST run-session can't start their flow."""

import pytest
from agents.models import AgentDefinition
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from storage_credentials.exceptions import TemporaryCredentialIssueError
from storage_credentials.services.session_credential_service import session_credential_service

from tables.models import (
    AudioTranscriptionNode,
    FileExtractorNode,
    Graph,
    KeyValueNode,
    KeyValueTable,
    PythonCode,
    PythonNode,
    Session,
    SessionWarningMessage,
)
from tables.models.graph_models import (
    AgentNode,
    AgentNodeTask,
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    ClassificationDecisionTablePrompt,
    ConditionGroup,
    DecisionTableNode,
    Edge,
    EndNode,
    KnowledgeNode,
    StartNode,
    SubGraphNode,
    TaskNode,
)
from tables.services.session_manager_service import SessionManagerService
from tests.fixtures import *
from utils.logger import logger

FLOW_START_FAILED_MESSAGE = (
    "Something went wrong on the server. Try again or contact your administrator."
)


def _connect_start_to_end(graph: Graph) -> None:
    start_node = StartNode.objects.get(graph=graph)
    end_node = EndNode.objects.create(graph=graph, output_map={})
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=end_node.id)


def _run_subflow(graph: Graph, child_flow: Graph) -> None:
    subflow_node = SubGraphNode.objects.create(
        graph=graph, node_name="Parse invoice", node_number=2, subgraph=child_flow
    )
    start_node = StartNode.objects.get(graph=graph)
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=subflow_node.id)


@pytest.fixture
def captured_log_records():
    """Collect every loguru record emitted while the test runs, at every level."""
    records: list[dict] = []
    sink_id = logger.add(lambda message: records.append(message.record), level="TRACE")
    yield records
    logger.remove(sink_id)


def _tracebacks(records: list[dict]) -> list[dict]:
    return [record for record in records if record["exception"] is not None]


@pytest.fixture
def child_flow(default_org) -> Graph:
    child_flow = Graph.objects.create(name="Invoice parser", org=default_org)
    StartNode.objects.create(graph=child_flow, variables={})
    return child_flow


@pytest.mark.django_db
def test_flow_with_nothing_connected_to_start_is_refused_with_its_fix(
    auth_client, redis_client_mock, session_data, graph
):
    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {"error": "Connect a node to Start."}
    redis_client_mock.publish.assert_not_called()
    session = Session.objects.get(graph=graph)
    assert session.status_data["reason"] == "Connect a node to Start."


@pytest.mark.django_db
def test_subflow_with_nothing_connected_to_start_is_named(
    auth_client, redis_client_mock, session_data, graph, child_flow
):
    _run_subflow(graph, child_flow)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "error": 'Connect a node to Start in flow "Invoice parser".'
    }


@pytest.mark.django_db
def test_node_inside_a_subflow_is_named_with_its_flow(
    auth_client, redis_client_mock, session_data, graph, child_flow
):
    _run_subflow(graph, child_flow)
    file_node = FileExtractorNode.objects.create(
        graph=child_flow, node_name="Extract PDF", node_number=1, input_map={}
    )
    _chain_from_start(child_flow, file_node)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "error": 'File Extractor node "Extract PDF #1" in flow "Invoice parser" has no input '
        "file."
    }


def _chain_from_start(graph: Graph, *nodes) -> None:
    previous_id = StartNode.objects.get(graph=graph).id
    for node in nodes:
        Edge.objects.create(graph=graph, start_node_id=previous_id, end_node_id=node.id)
        previous_id = node.id


@pytest.mark.django_db
def test_missing_agent_is_reported_before_a_key_value_node_without_a_table(
    auth_client, redis_client_mock, session_data, graph
):
    key_value_node = KeyValueNode.objects.create(
        graph=graph, node_name="Save lead", node_number=3
    )
    agent_node = AgentNode.objects.create(graph=graph, node_name="Writer", node_number=2)
    AgentNodeTask.objects.create(agent_node=agent_node, name="Draft", order=0)
    _chain_from_start(graph, key_value_node, agent_node)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {"error": 'Agent node "Writer #2" has no agent chosen.'}
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_agent_node_whose_only_task_is_in_the_recycle_bin_has_no_tasks(
    auth_client, redis_client_mock, session_data, graph, default_org, llm_config
):
    agent = AgentDefinition.objects.create(
        org=default_org, name="Copywriter", llm_config=llm_config
    )
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="Writer", node_number=2, agent_definition=agent
    )
    AgentNodeTask.objects.create(
        agent_node=agent_node,
        name="Draft",
        order=0,
        active=False,
        soft_deleted_at=timezone.now(),
    )
    _chain_from_start(graph, agent_node)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "error": 'Agent node "Writer #2" has no tasks. Add at least one task.'
    }


@pytest.mark.django_db
def test_agent_node_whose_agent_is_in_the_recycle_bin_has_no_agent_chosen(
    auth_client, redis_client_mock, session_data, graph, default_org, llm_config
):
    agent = AgentDefinition.objects.create(
        org=default_org, name="Copywriter", llm_config=llm_config
    )
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="Writer", node_number=2, agent_definition=agent
    )
    AgentNodeTask.objects.create(agent_node=agent_node, name="Draft", order=0)
    _chain_from_start(graph, agent_node)
    delete_response = auth_client.delete(reverse("agentdefinition-detail", args=[agent.pk]))
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT, delete_response.content

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {"error": 'Agent node "Writer #2" has no agent chosen.'}


@pytest.mark.django_db
def test_key_value_node_whose_table_is_in_the_recycle_bin_has_no_table_selected(
    auth_client, redis_client_mock, session_data, graph, default_org
):
    table = KeyValueTable.objects.create(org=default_org, name="Leads")
    key_value_node = KeyValueNode.objects.create(
        graph=graph, node_name="Save lead", node_number=3, key_value_table=table
    )
    _chain_from_start(graph, key_value_node)
    delete_response = auth_client.delete(reverse("key-value-tables-detail", args=[table.pk]))
    assert delete_response.status_code == status.HTTP_204_NO_CONTENT, delete_response.content

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {"error": 'Key-Value node "Save lead #3" has no table selected.'}


@pytest.mark.django_db
def test_key_value_node_inside_a_subflow_is_named_with_its_flow(
    auth_client, redis_client_mock, session_data, graph, child_flow
):
    _run_subflow(graph, child_flow)
    key_value_node = KeyValueNode.objects.create(
        graph=child_flow, node_name="Save lead", node_number=3
    )
    _chain_from_start(child_flow, key_value_node)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "error": 'Key-Value node "Save lead #3" in flow "Invoice parser" has no table selected.'
    }


@pytest.mark.django_db
def test_set_up_agent_task_and_key_value_nodes_run(
    auth_client, redis_client_mock, session_data, graph, default_org, llm_config
):
    agent = AgentDefinition.objects.create(
        org=default_org, name="Copywriter", llm_config=llm_config
    )
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="Writer", node_number=1, agent_definition=agent
    )
    AgentNodeTask.objects.create(agent_node=agent_node, name="Draft", order=0)
    task_node = TaskNode.objects.create(
        graph=graph, node_name="Summarize", node_number=2, agent_definition=agent
    )
    key_value_node = KeyValueNode.objects.create(
        graph=graph,
        node_name="Save lead",
        node_number=3,
        key_value_table=KeyValueTable.objects.create(org=default_org, name="Leads"),
    )
    _chain_from_start(graph, agent_node, task_node, key_value_node)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    redis_client_mock.publish.assert_called()


@pytest.mark.django_db
def test_subflow_loop_names_the_subflow_node_not_the_parent_flow(
    auth_client, redis_client_mock, session_data, graph
):
    _connect_start_to_end(graph)
    subflow_node = SubGraphNode.objects.create(
        graph=graph, node_name="Run again", node_number=5, subgraph=graph
    )
    _chain_from_start(graph, subflow_node)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "error": 'Subflow node "Run again #5" runs its own flow. Choose another flow.'
    }


@pytest.mark.django_db
def test_error_with_its_own_status_keeps_that_status_and_text(
    auth_client, redis_client_mock, session_data, graph, monkeypatch
):
    # The storage backend is external; failing to mint a credential there is a 500.
    def storage_unavailable(**kwargs):
        raise TemporaryCredentialIssueError()

    _connect_start_to_end(graph)
    monkeypatch.setattr(session_credential_service, "issue_for_session", storage_unavailable)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    expected = "We couldn't grant access to file storage for this run. Please try again shortly."
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, response.content
    assert response.json() == {
        "status_code": 500,
        "code": "temporary_credential_issue_error",
        "message": expected,
    }
    assert Session.objects.get(graph=graph).status_data["reason"] == expected


@pytest.mark.django_db
def test_unexpected_failure_returns_a_generic_message_without_internals(
    auth_client, redis_client_mock, session_data, graph, monkeypatch
):
    # With DEBUG on the handler leaves the exception to Django instead of rendering the 500.
    monkeypatch.setattr("utils.exception_handler.DEBUG", False)
    _connect_start_to_end(graph)
    redis_client_mock.publish.side_effect = ConnectionError(
        "Error 111 connecting to redis-internal.svc:6379. Connection refused."
    )

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    # Left to the global handler, so callers can retry a 5xx under load.
    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, response.content
    assert response.json() == {
        "status_code": 500,
        "code": "ConnectionError",
        "message": "Unpredictable error",
    }
    assert b"redis-internal" not in response.content
    session = Session.objects.get(graph=graph)
    assert session.status == Session.SessionStatus.ERROR
    assert session.status_data["reason"] == FLOW_START_FAILED_MESSAGE


@pytest.mark.django_db
def test_failure_after_crew_got_the_session_still_reports_it_started(
    auth_client, redis_client_mock, session_data, graph, monkeypatch
):
    def warnings_unavailable(graph, **kwargs):
        raise RuntimeError("warnings lookup failed")

    _connect_start_to_end(graph)
    monkeypatch.setattr(
        SessionManagerService().surface_knowledge_warning_service,
        "build_warnings",
        warnings_unavailable,
    )

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    session = Session.objects.get(pk=response.data["session_id"])
    assert session.status == Session.SessionStatus.PENDING
    redis_client_mock.publish.assert_called()
    assert not SessionWarningMessage.objects.filter(session=session).exists()


@pytest.mark.django_db
def test_refusal_is_logged_as_a_warning_without_a_traceback(
    auth_client, redis_client_mock, session_data, captured_log_records
):
    auth_client.post(reverse("run-session"), session_data, format="json")

    assert _tracebacks(captured_log_records) == []
    assert any(
        record["level"].name == "WARNING"
        and "Connect a node to Start." in record["message"]
        for record in captured_log_records
    )


@pytest.mark.django_db
@pytest.mark.parametrize("fails", ["before_the_session_exists", "after_the_session_exists"])
def test_unexpected_failure_logs_its_traceback_once(
    auth_client, redis_client_mock, session_data, graph, monkeypatch, captured_log_records, fails
):
    monkeypatch.setattr("utils.exception_handler.DEBUG", False)
    _connect_start_to_end(graph)
    if fails == "before_the_session_exists":

        def variables_unavailable(**kwargs):
            raise RuntimeError("persistent variables table is locked")

        monkeypatch.setattr(
            SessionManagerService().persistent_variables_service,
            "build_run_variables",
            variables_unavailable,
        )
    else:
        redis_client_mock.publish.side_effect = ConnectionError("redis is down")

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, response.content
    assert len(_tracebacks(captured_log_records)) == 1


def _decision_table_routing_to_end(graph: Graph, *, next_node_id: int | None = None):
    """A Decision Table node "Route #4" after Start, with one condition "High score"."""
    end_node = EndNode.objects.create(graph=graph, output_map={})
    table = DecisionTableNode.objects.create(
        graph=graph, node_name="Route", node_number=4, default_next_node_id=end_node.id
    )
    ConditionGroup.objects.create(
        decision_table_node=table,
        group_name="High score",
        group_type="complex",
        expression="variables.score > 5",
        next_node_id=next_node_id,
    )
    _chain_from_start(graph, table)
    return table, end_node


@pytest.mark.django_db
def test_decision_tables_crew_runs_without_failing_run(
    auth_client, redis_client_mock, session_data, graph
):
    # Crew takes the default route for a table without conditions, goes on past a
    # condition without a next node or a complex one without an expression, and
    # matches an empty simple group.
    triage = DecisionTableNode.objects.create(graph=graph, node_name="Triage", node_number=6)
    empty = DecisionTableNode.objects.create(
        graph=graph, node_name="Empty", node_number=5, default_next_node_id=triage.id
    )
    table, _ = _decision_table_routing_to_end(graph)
    ConditionGroup.objects.create(
        decision_table_node=table,
        group_name="Anything else",
        group_type="complex",
        expression="True",
        order=1,
        next_node_id=empty.id,
    )
    ConditionGroup.objects.create(
        decision_table_node=triage, group_name="Unwritten", group_type="complex", order=1
    )
    ConditionGroup.objects.create(
        decision_table_node=triage, group_name="Anything", group_type="simple", order=2
    )

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    redis_client_mock.publish.assert_called()


@pytest.mark.django_db
def test_decision_table_condition_with_a_blank_expression_inside_a_subflow_names_the_flow(
    auth_client, redis_client_mock, session_data, graph, child_flow
):
    _run_subflow(graph, child_flow)
    table, _ = _decision_table_routing_to_end(child_flow)
    ConditionGroup.objects.filter(decision_table_node=table).update(expression="  ")

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "error": 'Condition "High score" in Decision Table node "Route #4" in flow '
        '"Invoice parser" has no expression.'
    }


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("has_error_route", "expected_status"),
    [
        pytest.param(True, status.HTTP_201_CREATED, id="with-error-route-runs"),
        pytest.param(False, status.HTTP_400_BAD_REQUEST, id="without-error-route-is-refused"),
    ],
)
def test_decision_table_blank_expression_is_refused_only_without_an_error_route(
    auth_client, redis_client_mock, session_data, graph, has_error_route, expected_status
):
    table, end_node = _decision_table_routing_to_end(graph)
    ConditionGroup.objects.filter(decision_table_node=table).update(expression="  ")
    if has_error_route:
        DecisionTableNode.objects.filter(pk=table.pk).update(next_error_node_id=end_node.id)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == expected_status, response.content
    if not has_error_route:
        assert response.data == {
            "error": 'Condition "High score" in Decision Table node "Route #4" has no expression.'
        }


def _classification_table_after_start(graph: Graph, *, default_llm_config=None):
    """A Classification Table node "Route #4" after Start, with one prompt "classify"
    used by its row "High score"."""
    table = ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="Route", node_number=4, default_llm_config=default_llm_config
    )
    prompt = ClassificationDecisionTablePrompt.objects.create(
        cdt_node=table, prompt_key="classify", prompt_text="Classify {text}"
    )
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=table, group_name="High score", prompt=prompt
    )
    _chain_from_start(graph, table)
    return prompt


@pytest.mark.django_db
def test_classification_table_prompt_without_an_llm_is_named_with_its_fix(
    auth_client, redis_client_mock, session_data, graph
):
    _classification_table_after_start(graph)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "error": 'Prompt "classify" in Classification Table node "Route #4" has no LLM. '
        "Choose one for it, or set a default LLM for the node."
    }
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_classification_table_prompt_without_an_llm_runs_with_an_error_route(
    auth_client, redis_client_mock, session_data, graph
):
    prompt = _classification_table_after_start(graph)
    end_node = EndNode.objects.create(graph=graph, output_map={})
    ClassificationDecisionTableNode.objects.filter(pk=prompt.cdt_node_id).update(
        next_error_node_id=end_node.id
    )

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    redis_client_mock.publish.assert_called()


@pytest.mark.django_db
def test_classification_table_row_using_a_prompt_in_the_recycle_bin_runs(
    auth_client, redis_client_mock, session_data, graph
):
    # Crew skips a prompt it wasn't sent, so the binned prompt's missing LLM never matters.
    prompt = _classification_table_after_start(graph)
    ClassificationDecisionTablePrompt.objects.filter(pk=prompt.pk).update(
        active=False, soft_deleted_at=timezone.now()
    )

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    redis_client_mock.publish.assert_called()


@pytest.mark.django_db
def test_set_up_decision_and_classification_tables_run(
    auth_client, redis_client_mock, session_data, graph, llm_config
):
    _, end_node = _decision_table_routing_to_end(graph)
    ConditionGroup.objects.filter(decision_table_node__graph=graph).update(
        next_node_id=end_node.id
    )
    _classification_table_after_start(graph, default_llm_config=llm_config)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    redis_client_mock.publish.assert_called()


@pytest.mark.django_db
def test_subflow_input_that_is_not_a_flow_variable_is_named_with_its_fix(
    auth_client, redis_client_mock, session_data, graph, child_flow
):
    _connect_start_to_end(child_flow)
    subflow_node = SubGraphNode.objects.create(
        graph=graph,
        node_name="Run B",
        node_number=1,
        subgraph=child_flow,
        input_map={"customer": "customer"},
    )
    start_node = StartNode.objects.get(graph=graph)
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=subflow_node.id)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "error": 'Input "customer" of Subflow node "Run B #1" must be a flow variable, '
        "like variables.customer."
    }
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_subflow_input_inside_a_subflow_names_that_subflow(
    auth_client, redis_client_mock, session_data, graph, child_flow, default_org
):
    _run_subflow(graph, child_flow)
    inner_flow = Graph.objects.create(name="Customer lookup", org=default_org)
    StartNode.objects.create(graph=inner_flow, variables={})
    _connect_start_to_end(inner_flow)
    subflow_node = SubGraphNode.objects.create(
        graph=child_flow,
        node_name="Run B",
        node_number=1,
        subgraph=inner_flow,
        input_map={"customer": "customer"},
    )
    _chain_from_start(child_flow, subflow_node)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {
        "error": 'Input "customer" of Subflow node "Run B #1" in flow "Invoice parser" must '
        "be a flow variable, like variables.customer."
    }


@pytest.mark.django_db
def test_subflow_with_inputs_crew_reads_and_any_output_path_runs(
    auth_client, redis_client_mock, session_data, graph, child_flow
):
    _connect_start_to_end(child_flow)
    subflow_node = SubGraphNode.objects.create(
        graph=graph,
        node_name="Run B",
        node_number=1,
        subgraph=child_flow,
        input_map={"customer": "variables.customer|nobody", "everything": "variables"},
        output_variable_path="result",
    )
    start_node = StartNode.objects.get(graph=graph)
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=subflow_node.id)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    redis_client_mock.publish.assert_called()


# Only the nodes a run reaches are checked: a half set up node the run never gets to
# must not block it.


def _python_node(graph: Graph, node_number: int = 9) -> PythonNode:
    return PythonNode.objects.create(
        graph=graph,
        node_name="Prepare",
        node_number=node_number,
        python_code=PythonCode.objects.create(code="def main(): return 1"),
    )


def _agent_node_without_agent(graph: Graph, child_flow: Graph):
    agent_node = AgentNode.objects.create(graph=graph, node_name="Writer", node_number=2)
    AgentNodeTask.objects.create(agent_node=agent_node, name="Draft", order=0)
    return agent_node


def _key_value_node_without_table(graph: Graph, child_flow: Graph):
    return KeyValueNode.objects.create(graph=graph, node_name="Save lead", node_number=3)


def _file_extractor_node_without_input(graph: Graph, child_flow: Graph):
    return FileExtractorNode.objects.create(
        graph=graph, node_name="Extract PDF", node_number=1, input_map={}
    )


def _audio_node_without_input(graph: Graph, child_flow: Graph):
    return AudioTranscriptionNode.objects.create(
        graph=graph, node_name="Transcribe call", node_number=1, input_map={}
    )


def _knowledge_node_without_settings(graph: Graph, child_flow: Graph):
    return KnowledgeNode.objects.create(graph=graph, node_name="Search docs", node_number=5)


def _decision_table_with_blank_condition(graph: Graph, child_flow: Graph):
    table = DecisionTableNode.objects.create(graph=graph, node_name="Route", node_number=4)
    ConditionGroup.objects.create(
        decision_table_node=table, group_name="High score", group_type="complex", expression=" "
    )
    return table


def _classification_table_with_prompt_without_llm(graph: Graph, child_flow: Graph):
    table = ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="Route", node_number=4
    )
    prompt = ClassificationDecisionTablePrompt.objects.create(
        cdt_node=table, prompt_key="classify", prompt_text="Classify {text}"
    )
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=table, group_name="High score", prompt=prompt
    )
    return table


def _subflow_node_without_flow(graph: Graph, child_flow: Graph):
    return SubGraphNode.objects.create(graph=graph, node_name="Parse invoice", node_number=2)


def _subflow_node_with_input_crew_fails_on(graph: Graph, child_flow: Graph):
    _connect_start_to_end(child_flow)
    return SubGraphNode.objects.create(
        graph=graph,
        node_name="Run B",
        node_number=1,
        subgraph=child_flow,
        input_map={"customer": "customer"},
    )


def _end_node_with_output_not_a_flow_variable(graph: Graph, child_flow: Graph):
    return EndNode.objects.create(graph=graph, output_map={"summary": "result"})


HALF_SET_UP_NODES = [
    pytest.param(
        _agent_node_without_agent, 'Agent node "Writer #2" has no agent chosen.', id="agent"
    ),
    pytest.param(
        _key_value_node_without_table,
        'Key-Value node "Save lead #3" has no table selected.',
        id="key-value",
    ),
    pytest.param(
        _file_extractor_node_without_input,
        'File Extractor node "Extract PDF #1" has no input file.',
        id="file-extractor",
    ),
    pytest.param(
        _audio_node_without_input,
        'Audio to text node "Transcribe call #1" has no input file.',
        id="audio-to-text",
    ),
    pytest.param(
        _knowledge_node_without_settings,
        'Knowledge Retriever node "Search docs #5" needs a collection, a RAG and a query.',
        id="knowledge-retriever",
    ),
    pytest.param(
        _decision_table_with_blank_condition,
        'Condition "High score" in Decision Table node "Route #4" has no expression.',
        id="decision-table",
    ),
    pytest.param(
        _classification_table_with_prompt_without_llm,
        'Prompt "classify" in Classification Table node "Route #4" has no LLM. '
        "Choose one for it, or set a default LLM for the node.",
        id="classification-table",
    ),
    pytest.param(
        _subflow_node_without_flow,
        'Subflow node "Parse invoice #2" has no flow selected.',
        id="subflow-without-flow",
    ),
    pytest.param(
        _subflow_node_with_input_crew_fails_on,
        'Input "customer" of Subflow node "Run B #1" must be a flow variable, '
        "like variables.customer.",
        id="subflow-input",
    ),
    pytest.param(
        _end_node_with_output_not_a_flow_variable,
        'Output "summary" of the End node must be a flow variable, like variables.summary.',
        id="end",
    ),
]


@pytest.mark.django_db
@pytest.mark.parametrize(("make_node", "message"), HALF_SET_UP_NODES)
def test_half_set_up_node_the_run_does_not_reach_does_not_block_it(
    auth_client, redis_client_mock, session_data, graph, child_flow, make_node, message
):
    _chain_from_start(graph, _python_node(graph))
    make_node(graph, child_flow)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    redis_client_mock.publish.assert_called()


@pytest.mark.django_db
@pytest.mark.parametrize(("make_node", "message"), HALF_SET_UP_NODES)
def test_half_set_up_node_the_run_reaches_is_refused_with_its_message(
    auth_client, redis_client_mock, session_data, graph, child_flow, make_node, message
):
    _chain_from_start(graph, _python_node(graph), make_node(graph, child_flow))

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {"error": message}
    redis_client_mock.publish.assert_not_called()


def _decision_table_routing_to(graph: Graph, target, route: str) -> None:
    table = DecisionTableNode.objects.create(
        graph=graph,
        node_name="Route",
        node_number=4,
        default_next_node_id=target.id if route == "default" else None,
        next_error_node_id=target.id if route == "error" else None,
    )
    ConditionGroup.objects.create(
        decision_table_node=table,
        group_name="High score",
        group_type="complex",
        expression="variables.score > 5",
        next_node_id=target.id if route == "condition" else None,
    )
    _chain_from_start(graph, table)


def _classification_table_routing_to(graph: Graph, target, route: str) -> None:
    table = ClassificationDecisionTableNode.objects.create(
        graph=graph,
        node_name="Route",
        node_number=4,
        default_next_node_id=target.id if route == "default" else None,
        next_error_node_id=target.id if route == "error" else None,
    )
    ClassificationConditionGroup.objects.create(
        classification_decision_table_node=table,
        group_name="High score",
        next_node_id=target.id if route == "row" else None,
    )
    _chain_from_start(graph, table)


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("route_to", "route"),
    [
        pytest.param(_decision_table_routing_to, "condition", id="decision-table-condition"),
        pytest.param(_decision_table_routing_to, "default", id="decision-table-default"),
        pytest.param(_decision_table_routing_to, "error", id="decision-table-error"),
        pytest.param(_classification_table_routing_to, "row", id="classification-table-row"),
        pytest.param(
            _classification_table_routing_to, "default", id="classification-table-default"
        ),
        pytest.param(_classification_table_routing_to, "error", id="classification-table-error"),
    ],
)
def test_node_reached_only_through_a_table_route_is_checked(
    auth_client, redis_client_mock, session_data, graph, child_flow, route_to, route
):
    route_to(graph, _agent_node_without_agent(graph, child_flow), route)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {"error": 'Agent node "Writer #2" has no agent chosen.'}


@pytest.mark.django_db
def test_node_behind_a_disabled_classification_row_is_not_checked(
    auth_client, redis_client_mock, session_data, graph, child_flow
):
    # Crew skips a disabled row, so the node it would route to never runs.
    _classification_table_routing_to(graph, _agent_node_without_agent(graph, child_flow), "row")
    ClassificationConditionGroup.objects.filter(group_name="High score").update(
        dock_visible=False
    )

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content


@pytest.mark.django_db
def test_subflow_reached_only_through_an_unconnected_subflow_node_is_not_checked(
    auth_client, redis_client_mock, session_data, graph, child_flow
):
    _chain_from_start(graph, _python_node(graph))
    SubGraphNode.objects.create(
        graph=graph, node_name="Parse invoice", node_number=2, subgraph=child_flow
    )
    _chain_from_start(child_flow, _agent_node_without_agent(child_flow, child_flow))
    # A loop behind the unconnected node is not followed either.
    SubGraphNode.objects.create(graph=child_flow, node_name="Back", node_number=3, subgraph=graph)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    redis_client_mock.publish.assert_called()


@pytest.mark.django_db
def test_inside_a_subflow_only_the_nodes_its_run_reaches_are_checked(
    auth_client, redis_client_mock, session_data, graph, child_flow
):
    _run_subflow(graph, child_flow)
    _chain_from_start(child_flow, _python_node(child_flow))
    _agent_node_without_agent(child_flow, child_flow)
    SubGraphNode.objects.create(graph=child_flow, node_name="Nested", node_number=4)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content


def _python_node_reading_an_undeclared_secret(graph: Graph) -> PythonNode:
    return PythonNode.objects.create(
        graph=graph,
        node_name="Fetch",
        node_number=7,
        python_code=PythonCode.objects.create(
            code='def main():\n    return get_secret("API_KEY")\n'
        ),
    )


@pytest.mark.django_db
def test_undeclared_secret_in_a_node_the_run_does_not_reach_does_not_block_it(
    auth_client, redis_client_mock, session_data, graph
):
    _chain_from_start(graph, _python_node(graph))
    _python_node_reading_an_undeclared_secret(graph)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert Session.objects.get(graph=graph).status == Session.SessionStatus.PENDING


@pytest.mark.django_db
def test_undeclared_secret_in_a_node_the_run_reaches_is_refused(
    auth_client, redis_client_mock, session_data, graph
):
    _chain_from_start(graph, _python_node(graph), _python_node_reading_an_undeclared_secret(graph))

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    expected = (
        'Session aborted: node "Fetch" calls get_secret("API_KEY"), which is not declared '
        "for that node. Declared: none."
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    assert response.data == {"error": expected}
    redis_client_mock.publish.assert_not_called()
    session = Session.objects.get(graph=graph)
    assert session.status == Session.SessionStatus.ERROR
    assert session.status_data["reason"] == expected
