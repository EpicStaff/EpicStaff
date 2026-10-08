import pytest

from tables.models import Graph, PythonCode, WebhookTrigger
from tables.models.graph_models import WebhookTriggerNode
from tables.models.session_models import SessionTrigger
from tables.services.trigger_test_run.registry import TEST_RUN_STRATEGIES
from tables.services.trigger_test_run.telegram_trigger_strategy import (
    TelegramTriggerTestRunStrategy,
)
from tables.services.trigger_test_run.webhook_trigger_strategy import (
    WebhookTriggerTestRunStrategy,
)
from tables.services.webhook_trigger_service import WebhookTriggerService


@pytest.fixture
def webhook_node(default_org):
    graph = Graph.objects.create(name="webhook-test-run-strategy", org=default_org)
    return WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="Hook",
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )


@pytest.mark.django_db
class TestWebhookTriggerTestRunStrategy:
    def test_accepts_any_object_payload(self, webhook_node):
        WebhookTriggerTestRunStrategy().validate_payload(webhook_node, {"anything": [1, None]})

    def test_variables_match_the_real_handler_shape(self):
        payload = {"order": 1}

        assert WebhookTriggerTestRunStrategy().build_variables(payload) == {
            "trigger_payload": payload
        }

    def test_trigger_carries_the_selected_trigger_path(self, default_org, webhook_node):
        webhook_node.webhook_trigger = WebhookTrigger.objects.create(
            path="strategy-path", org=default_org
        )
        webhook_node.save()

        trigger = WebhookTriggerTestRunStrategy().build_trigger(webhook_node, {})

        assert trigger.trigger_type == SessionTrigger.TriggerType.WEBHOOK
        assert trigger.webhook_trigger_node_id == webhook_node.id
        assert trigger.node_name == "Hook"
        assert trigger.extra == {"path": "strategy-path", "config_id": None}

    def test_trigger_path_is_none_without_a_selected_trigger(self, webhook_node):
        trigger = WebhookTriggerTestRunStrategy().build_trigger(webhook_node, {})

        assert trigger.extra == {"path": None, "config_id": None}

    def test_run_inputs_match_what_the_real_inbound_handler_passes(
        self, default_org, webhook_node, mocker
    ):
        # The strategy mirrors `handle_webhook_trigger`; renaming the run variable
        # or changing the trigger in only one of them must fail here.
        webhook_node.webhook_trigger = WebhookTrigger.objects.create(
            path="strategy-handler-link", org=default_org
        )
        webhook_node.save()
        webhook_trigger_service = WebhookTriggerService()
        run_session = mocker.patch.object(
            webhook_trigger_service.session_manager_service, "run_session"
        )
        payload = {"order": 1, "items": [{"sku": "A-1"}]}
        strategy = WebhookTriggerTestRunStrategy()

        webhook_trigger_service.handle_webhook_trigger(
            path="strategy-handler-link", payload=payload
        )

        run_session.assert_called_once()
        handler_kwargs = run_session.call_args.kwargs
        assert handler_kwargs["graph_id"] == webhook_node.graph_id
        assert handler_kwargs["variables"] == strategy.build_variables(payload)
        assert handler_kwargs["trigger"] == strategy.build_trigger(webhook_node, payload)


def test_registry_maps_each_canvas_node_type_to_its_strategy():
    assert {
        node_type: type(strategy) for node_type, strategy in TEST_RUN_STRATEGIES.items()
    } == {
        "webhook-trigger": WebhookTriggerTestRunStrategy,
        "telegram-trigger": TelegramTriggerTestRunStrategy,
    }
