from tables.graph_versioning.handlers.null_fk_handler import NullFkHandler
from tables.import_export.enums import NodeType


class WebhookTriggerNodeHandler(NullFkHandler):
    node_type = NodeType.WEBHOOK_TRIGGER_NODE
    fk_field = "webhook_trigger"
    missing_set_attr = "webhooks"
    dependency_label = "Webhook Trigger"
