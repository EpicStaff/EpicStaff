import pytest

from tables.models import Graph, PythonCode
from tables.models.graph_models import TelegramTriggerNode, WebhookTriggerNode
from tables.models.session_models import SessionTrigger
from tables.services.trigger_spec import TriggerSpec


@pytest.mark.django_db
def test_as_test_run_keeps_the_webhook_spec_and_adds_the_flag(default_org):
    graph = Graph.objects.create(name="spec-test-run-webhook", org=default_org)
    node = WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="Hook",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )
    original = TriggerSpec.webhook(node, path="some-path", config_id="ngrok:1:some-path")

    test_run_spec = original.as_test_run()

    assert test_run_spec.trigger_type == SessionTrigger.TriggerType.WEBHOOK
    assert test_run_spec.webhook_trigger_node_id == node.id
    assert test_run_spec.node_name == "Hook"
    assert test_run_spec.node_id == node.id
    assert test_run_spec.extra == {
        "path": "some-path",
        "config_id": "ngrok:1:some-path",
        SessionTrigger.TEST_RUN_EXTRA_KEY: True,
    }
    assert original.extra == {"path": "some-path", "config_id": "ngrok:1:some-path"}


@pytest.mark.django_db
def test_as_test_run_keeps_the_telegram_chat_id(default_org, mock_telegram_service):
    graph = Graph.objects.create(name="spec-test-run-telegram", org=default_org)
    node = TelegramTriggerNode.objects.create(graph=graph, node_name="Bot")
    original = TriggerSpec.telegram(node, {"message": {"chat": {"id": 5}}})

    test_run_spec = original.as_test_run()

    assert test_run_spec.trigger_type == SessionTrigger.TriggerType.TELEGRAM
    assert test_run_spec.telegram_trigger_node_id == node.id
    assert test_run_spec.extra == {"chat_id": 5, SessionTrigger.TEST_RUN_EXTRA_KEY: True}
    assert original.extra == {"chat_id": 5}


def test_as_test_run_materialises_into_session_trigger_fields():
    fields = TriggerSpec.manual().as_test_run().to_fields()

    assert fields["trigger_type"] == SessionTrigger.TriggerType.MANUAL
    assert fields["extra"] == {SessionTrigger.TEST_RUN_EXTRA_KEY: True}


@pytest.mark.parametrize(
    "extra, expected",
    [
        ({}, False),
        ({"chat_id": 1}, False),
        ({SessionTrigger.TEST_RUN_EXTRA_KEY: True}, True),
        # Only JSON `true` counts, the same rule as the `?is_test_run=` list filter.
        ({SessionTrigger.TEST_RUN_EXTRA_KEY: 1}, False),
        ({SessionTrigger.TEST_RUN_EXTRA_KEY: "true"}, False),
        ({SessionTrigger.TEST_RUN_EXTRA_KEY: False}, False),
    ],
)
def test_session_trigger_is_test_run_reads_extra(extra, expected):
    assert SessionTrigger(extra=extra).is_test_run is expected
