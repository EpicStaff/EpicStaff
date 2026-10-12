"""How the TelegramTriggerNode post_save signal logs a failed registration.

An expected, user-fixable failure (an APIException such as a missing Telegram
secret) must log one line, not a traceback: with loguru's `diagnose` on, a
traceback prints local variable values, which include the resolved bot token.
Anything unexpected must still log a full traceback.
"""

import pytest
from loguru import logger as loguru_logger

from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.webhook_models import NgrokWebhookConfig, ProviderType, WebhookTrigger
from tables.services.secrets import secret_service
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService

BOT_TOKEN = "555555555:AAH-signal-logging-SECRET-bot-token"


@pytest.fixture
def captured_log_records():
    """Collect (level name, fully formatted text) like a production sink with diagnose on."""
    records = []
    sink_id = loguru_logger.add(
        lambda message: records.append((message.record["level"].name, str(message))),
        level="DEBUG",
        format="{level} | {message}\n{exception}",
        backtrace=True,
        diagnose=True,
    )
    yield records
    loguru_logger.remove(sink_id)


@pytest.fixture(autouse=True)
def _stub_tunnel_resync(monkeypatch):
    monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)


def _create_node_without_telegram_secret(org):
    trigger = WebhookTrigger.objects.create(
        path="signal-logging-path", provider_type=ProviderType.NGROK, org=org
    )
    NgrokWebhookConfig.objects.create(
        trigger=trigger,
        name="cfg-signal-logging",
        auth_token_secret=secret_service.create(
            text="ngrok-token", org=org, name="signal-logging-ngrok-secret"
        ),
    )
    return TelegramTriggerNode.objects.create(
        node_name="signal-logging-node",
        graph=Graph.objects.create(name="signal-logging-graph", org=org),
        webhook_trigger=trigger,
        telegram_bot_api_key_secret=secret_service.create(
            text=BOT_TOKEN, org=org, name="signal-logging-bot-key"
        ),
    )


@pytest.mark.django_db
def test_missing_telegram_secret_logs_one_error_line_without_a_traceback(
    default_org, captured_log_records
):
    _create_node_without_telegram_secret(default_org)

    assert any(
        level == "ERROR" and "No Telegram secret configured" in text
        for level, text in captured_log_records
    )
    assert not any("Traceback" in text for _level, text in captured_log_records)
    assert not any(BOT_TOKEN in text for _level, text in captured_log_records)


@pytest.mark.django_db
def test_unexpected_registration_error_still_logs_a_traceback(
    default_org, captured_log_records, monkeypatch
):
    def _boom(self, telegram_trigger_instance=None, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(TelegramTriggerService, "register_telegram_trigger", _boom)

    _create_node_without_telegram_secret(default_org)

    assert any(
        level == "ERROR" and "Traceback" in text and "RuntimeError: boom" in text
        for level, text in captured_log_records
    )
