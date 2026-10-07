from tables.models.graph_models import WebhookTriggerNode
from tables.services.trigger_spec import TriggerSpec
from tables.services.trigger_test_run.base import TriggerTestRunStrategy


class WebhookTriggerTestRunStrategy(TriggerTestRunStrategy):
    """Starts a run at a webhook trigger node; no tunnel, auth or selected trigger is required."""

    node_type = "webhook-trigger"
    node_model = WebhookTriggerNode

    def build_variables(self, payload: dict) -> dict:
        return {"trigger_payload": payload}

    def build_trigger(self, node: WebhookTriggerNode, payload: dict) -> TriggerSpec:
        path = node.webhook_trigger.path if node.webhook_trigger_id else None
        return TriggerSpec.webhook(node, path=path, config_id=None)
