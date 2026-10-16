from tables.services.trigger_test_run.base import TriggerTestRunStrategy
from tables.services.trigger_test_run.telegram_trigger_strategy import (
    TelegramTriggerTestRunStrategy,
)
from tables.services.trigger_test_run.webhook_trigger_strategy import (
    WebhookTriggerTestRunStrategy,
)

TEST_RUN_STRATEGIES: dict[str, TriggerTestRunStrategy] = {
    strategy.node_type: strategy
    for strategy in (
        WebhookTriggerTestRunStrategy(),
        TelegramTriggerTestRunStrategy(),
    )
}
