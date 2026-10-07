import pytest
from django.urls import reverse

from tables.models.graph_models import Graph, WebhookTriggerNode
from utils.logger import logger

SECRET_MARKER = "WEBHOOK_AUTH_SECRET_MARKER_do_not_log"


@pytest.fixture
def captured_log_messages():
    """Collect every loguru message emitted while the test runs, at every level."""
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="TRACE", format="{message}")
    yield messages
    logger.remove(sink_id)


def _payload_with_marker(graph_id: int | None) -> dict:
    # python_code comes first: utils.logger truncates messages to 200 characters,
    # so only the python_code marker is observable in a dump of the whole body.
    # The global_kwargs and metadata markers catch a narrower log of just those fields.
    payload = {
        "python_code": {
            "code": f"{SECRET_MARKER} = 'sk-live'\ndef handler(event, context):\n    return event",
            "libraries": [],
            "entrypoint": "handler",
            "global_kwargs": {"api_key": SECRET_MARKER},
        },
        "node_name": "Webhook Log Redaction",
        "metadata": {"note": SECRET_MARKER},
    }
    if graph_id is not None:
        payload["graph"] = graph_id
    return payload


@pytest.mark.django_db
class TestWebhookTriggerNodeCreateDoesNotLogBody:
    def test_successful_create_does_not_log_request_body(
        self, auth_client, graph: Graph, captured_log_messages
    ):
        response = auth_client.post(
            reverse("webhooktriggernode-list"), _payload_with_marker(graph.id), format="json"
        )

        assert response.status_code == 201, response.json()
        assert WebhookTriggerNode.objects.filter(graph=graph).count() == 1
        leaked = [message for message in captured_log_messages if SECRET_MARKER in message]
        assert leaked == []

    def test_rejected_create_does_not_log_request_body(
        self, auth_client, captured_log_messages
    ):
        response = auth_client.post(
            reverse("webhooktriggernode-list"), _payload_with_marker(graph_id=None), format="json"
        )

        assert response.status_code == 400, response.json()
        leaked = [message for message in captured_log_messages if SECRET_MARKER in message]
        assert leaked == []
