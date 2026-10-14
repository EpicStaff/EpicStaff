"""`starts_runs` in NODE_TYPE_REGISTRY is the one place that says which nodes are triggers.

The RUN checks and `has_trigger_nodes` derive their trigger sets from it; these tests
pin that every derivation sees the same three node types.
"""

from tables.models.graph_models import (
    ScheduleTriggerNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.services.code_run_targets import CODE_RUN_TARGETS
from tables.services.graph_bulk_save_service.registry import (
    TRIGGER_NODE_LIST_KEYS,
    TRIGGER_NODE_MODELS,
)
from tables.services.trigger_nodes import _TRIGGER_NODE_PYTHON_CODE_FIELDS

EXPECTED_LIST_KEYS = {
    "webhook_trigger_node_list",
    "telegram_trigger_node_list",
    "schedule_trigger_node_list",
}


def test_registry_flags_exactly_the_trigger_node_types():
    assert TRIGGER_NODE_LIST_KEYS == EXPECTED_LIST_KEYS


def test_trigger_models_derive_from_the_registry():
    assert TRIGGER_NODE_MODELS == {WebhookTriggerNode, TelegramTriggerNode, ScheduleTriggerNode}


def test_only_the_webhook_trigger_code_run_target_is_a_trigger():
    assert {
        target_type
        for target_type, target in CODE_RUN_TARGETS.items()
        if target.owner_is_trigger_node
    } == {"webhook_trigger_node"}


def test_trigger_code_owner_relations_derive_from_the_registry():
    """Only the webhook trigger node holds a PythonCode today; a trigger type gaining
    one is picked up without touching run-python-code."""
    assert _TRIGGER_NODE_PYTHON_CODE_FIELDS == ((WebhookTriggerNode, "python_code"),)
