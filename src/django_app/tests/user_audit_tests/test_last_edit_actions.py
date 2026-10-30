import pytest
from django.urls import reverse
from rest_framework import status
from src.shared.models import UserAction

from agents.models import AgentDefinition
from rbac.authorship import LastEditTracker, record_last_edits
from tables.models import Graph, PythonNode
from user_audit.context import user_action_context

from tests.fixtures import *  # noqa: F401,F403

NODE_METADATA = {"position": {"x": 100, "y": 200}, "color": "#5672cd"}
ORIGINAL_CODE = "def main():\n    return 1\n"


@pytest.fixture
def flow(default_org):
    return Graph.objects.create(name="Billing flow", org=default_org)


def _python_item(*, code=ORIGINAL_CODE, metadata=NODE_METADATA, **identity) -> dict:
    return {
        "node_name": "Fetch invoices",
        "metadata": metadata,
        "python_code": {"code": code, "entrypoint": "main", "libraries": []},
        **identity,
    }


def _post_save(client, flow, lists):
    flow.refresh_from_db()
    response = client.post(
        reverse("graphs-save-flow", args=[flow.id]),
        {"save_version": flow.save_version, **lists},
        format="json",
    )
    assert response.status_code == status.HTTP_200_OK, response.content


def _save_flow(client, flow, capture, **lists):
    with capture(execute=True):
        _post_save(client, flow, lists)


@pytest.fixture
def python_node(auth_client, flow):
    # Saved the way the editor saves it, so an unchanged resave compares equal. Its own
    # record is never sent: on-commit callbacks are not captured here.
    _post_save(
        auth_client,
        flow,
        {
            "python_node_list": [
                _python_item(graph=flow.id, temp_id="11111111-1111-1111-1111-111111111111")
            ]
        },
    )
    return PythonNode.objects.get(graph=flow)


def _target(event) -> tuple:
    return event.action, event.target_type, event.target_id, event.target_name


def _parent(event) -> tuple:
    return event.parent_type, event.parent_id, event.parent_name


@pytest.mark.django_db
def test_editing_python_node_code_records_updated_node_in_flow(
    auth_client, flow, python_node, default_org, sent_events, django_capture_on_commit_callbacks
):
    _save_flow(
        auth_client,
        flow,
        django_capture_on_commit_callbacks,
        python_node_list=[
            _python_item(id=python_node.id, graph=flow.id, code="def main():\n    return 2\n")
        ],
    )

    [event] = sent_events
    assert _target(event) == ("updated", "python node", str(python_node.id), "Fetch invoices")
    assert _parent(event) == ("flow", str(flow.id), "Billing flow")
    assert event.org_id == default_org.id
    assert event.previous_name is None


@pytest.mark.django_db
def test_moving_a_node_records_updated_flow_only(
    auth_client, flow, python_node, default_org, sent_events, django_capture_on_commit_callbacks
):
    moved = {**NODE_METADATA, "position": {"x": 400, "y": 50}}

    _save_flow(
        auth_client,
        flow,
        django_capture_on_commit_callbacks,
        python_node_list=[_python_item(id=python_node.id, graph=flow.id, metadata=moved)],
    )

    [event] = sent_events
    assert _target(event) == ("updated", "flow", str(flow.id), "Billing flow")
    assert _parent(event) == (None, None, None)
    assert event.org_id == default_org.id


@pytest.mark.django_db
def test_adding_a_node_records_created_node_not_updated_flow(
    auth_client, flow, sent_events, django_capture_on_commit_callbacks
):
    _save_flow(
        auth_client,
        flow,
        django_capture_on_commit_callbacks,
        python_node_list=[
            _python_item(
                node_name="Send reminders",
                graph=flow.id,
                temp_id="22222222-2222-2222-2222-222222222222",
            )
        ],
    )

    created = PythonNode.objects.get(graph=flow)
    [event] = sent_events
    assert _target(event) == ("created", "python node", str(created.id), "Send reminders")
    assert _parent(event) == ("flow", str(flow.id), "Billing flow")


@pytest.mark.django_db
def test_save_with_no_change_records_nothing(
    auth_client, flow, python_node, sent_events, django_capture_on_commit_callbacks
):
    _save_flow(
        auth_client,
        flow,
        django_capture_on_commit_callbacks,
        python_node_list=[_python_item(id=python_node.id, graph=flow.id)],
    )

    assert sent_events == []


@pytest.mark.django_db
def test_renaming_flow_records_renamed_with_previous_name(
    auth_client, flow, default_org, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = auth_client.patch(
            reverse("graphs-detail", args=[flow.id]),
            {"name": "Invoicing flow", "save_version": flow.save_version},
            format="json",
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    [event] = sent_events
    assert _target(event) == ("renamed", "flow", str(flow.id), "Invoicing flow")
    assert event.previous_name == "Billing flow"
    assert event.org_id == default_org.id


@pytest.mark.django_db
def test_creating_agent_records_created(
    auth_client, default_org, regular_user, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = auth_client.post(
            reverse("agentdefinition-list"), {"name": "invoice-agent"}, format="json"
        )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    agent = AgentDefinition.objects.get(pk=response.data["id"])
    [event] = sent_events
    assert _target(event) == ("created", "agent definition", str(agent.id), "invoice-agent")
    assert (event.org_id, event.actor_user_id) == (default_org.id, regular_user.id)


@pytest.mark.django_db
def test_record_last_edits_direct_call_records_updated_once(
    rf,
    flow,
    python_node,
    default_org,
    regular_user,
    sent_events,
    django_capture_on_commit_callbacks,
):
    request = rf.post("/api/graphs/")
    request.user = regular_user

    with user_action_context(request), django_capture_on_commit_callbacks(execute=True):
        record_last_edits([python_node, python_node], regular_user)

    [event] = sent_events
    assert _target(event) == ("updated", "python node", str(python_node.id), "Fetch invoices")
    assert _parent(event) == ("flow", str(flow.id), "Billing flow")
    assert event.org_id == default_org.id


@pytest.mark.django_db
def test_tracker_that_changed_nothing_still_marks_the_request_recorded(
    rf, regular_user, sent_events
):
    request = rf.post("/api/graphs/")
    request.user = regular_user

    with user_action_context(request) as context:
        LastEditTracker(regular_user).finish()

    assert context.recorded is True
    assert sent_events == []


@pytest.mark.django_db
def test_binning_a_flow_records_no_updated_action(
    auth_client, flow, sent_events, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        response = auth_client.delete(reverse("graphs-detail", args=[flow.id]))

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content
    assert UserAction.UPDATED not in {event.action for event in sent_events}
