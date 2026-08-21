"""EST-3862 backfill command: `manage.py backfill_telegram_webhook_secrets`.

Generates a `WebhookNodeAuth` (+ its `Secret`) and re-registers `setWebhook`
for every existing `TelegramTriggerNode` that doesn't have one yet. No-ops
for nodes that already have one, `--dry-run` makes no DB changes, and one
node's failure never aborts the rest.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    WebhookAuthScheme,
    WebhookNodeAuth,
    WebhookTrigger,
)
from tables.services.secrets import secret_service
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService

# Captured at import time, before any test/fixture monkeypatches the class
# attribute -- the only reliable way to get back to the genuine
# implementation after the autouse fixture below replaces it.
_REAL_REGISTER_TELEGRAM_TRIGGER = TelegramTriggerService.register_telegram_trigger


@pytest.fixture(autouse=True)
def _mock_telegram_signal_side_effects(monkeypatch):
    """Node creation below fires the real post_save registration signal --
    stub it so setup doesn't make a live Redis publish / outbound Telegram
    call. The command itself calls the real `register_telegram_trigger`
    through a separately-stubbed path per test."""
    monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
    monkeypatch.setattr(
        TelegramTriggerService,
        "register_telegram_trigger",
        lambda self, telegram_trigger_instance=None, **kwargs: None,
    )


def _make_node(*, default_org, path, with_secret=True):
    graph = Graph.objects.create(name=f"g-{path}", org=default_org)
    trigger = WebhookTrigger.objects.create(
        path=path, provider_type=ProviderType.NGROK, org=default_org
    )
    NgrokWebhookConfig.objects.create(
        name=f"cfg-{path}",
        auth_token_secret=secret_service.create(
            text="tok", org=default_org, name=f"{path}-ngrok-secret"
        ),
        trigger=trigger,
    )
    kwargs = {}
    if with_secret:
        kwargs["telegram_bot_api_key_secret"] = secret_service.create(
            text="bot-token", org=default_org, name=f"{path}-bot-secret"
        )
    return TelegramTriggerNode.objects.create(
        node_name=f"node-{path}", graph=graph, webhook_trigger=trigger, **kwargs
    )


@pytest.mark.django_db
class TestBackfillTelegramWebhookSecrets:
    def test_generates_and_registers_for_nodes_missing_a_row(
        self, default_org, monkeypatch
    ):
        node = _make_node(default_org=default_org, path="backfill-missing")

        # Restore the real implementation for the command's own call, but
        # stub the outbound bits it needs (tunnel URL + the Telegram HTTP
        # call itself) so this stays a unit test.
        monkeypatch.setattr(
            WebhookTriggerService,
            "wait_for_tunnel_url_for_trigger",
            lambda self, trigger: "https://tunnel.test",
        )
        monkeypatch.setattr(
            TelegramTriggerService,
            "_call_telegram_api",
            lambda self, method, api_key, endpoint, params=None: {"ok": True},
        )
        monkeypatch.setattr(
            TelegramTriggerService,
            "register_telegram_trigger",
            _REAL_REGISTER_TELEGRAM_TRIGGER,
        )

        out = StringIO()
        call_command("backfill_telegram_webhook_secrets", stdout=out)

        node.refresh_from_db()
        assert WebhookNodeAuth.objects.filter(telegram_trigger_node=node).exists()
        auth = node.webhook_node_auth
        assert auth.scheme == WebhookAuthScheme.STATIC_HEADER
        assert auth.enabled is True
        assert "Succeeded: 1" in out.getvalue()

    def test_noops_for_nodes_that_already_have_a_row(self, default_org):
        node = _make_node(default_org=default_org, path="backfill-existing")
        secret = secret_service.create(
            text="already-there", org=default_org, name="backfill-existing-secret"
        )
        WebhookNodeAuth.objects.create(
            enabled=True,
            scheme=WebhookAuthScheme.STATIC_HEADER,
            header_name="X-Telegram-Bot-Api-Secret-Token",
            secret=secret,
            telegram_trigger_node=node,
        )

        out = StringIO()
        call_command("backfill_telegram_webhook_secrets", stdout=out)

        assert "No TelegramTriggerNode is missing a WebhookNodeAuth row." in (
            out.getvalue()
        )
        assert WebhookNodeAuth.objects.filter(telegram_trigger_node=node).count() == 1

    def test_dry_run_makes_no_db_changes(self, default_org):
        _make_node(default_org=default_org, path="backfill-dry-run")

        out = StringIO()
        call_command("backfill_telegram_webhook_secrets", "--dry-run", stdout=out)

        assert "would register" in out.getvalue()
        assert WebhookNodeAuth.objects.count() == 0

    def test_one_nodes_failure_does_not_abort_the_rest(self, default_org, monkeypatch):
        healthy = _make_node(default_org=default_org, path="backfill-healthy")
        broken = _make_node(default_org=default_org, path="backfill-broken")

        def _fake_register(self, telegram_trigger_instance):
            if telegram_trigger_instance.pk == broken.pk:
                raise RuntimeError("simulated failure for broken node")
            secret = secret_service.create(
                text="ok",
                org=default_org,
                name=f"backfill-ok-secret-{telegram_trigger_instance.pk}",
            )
            return WebhookNodeAuth.objects.create(
                enabled=True,
                scheme=WebhookAuthScheme.STATIC_HEADER,
                header_name="X-Telegram-Bot-Api-Secret-Token",
                secret=secret,
                telegram_trigger_node=telegram_trigger_instance,
            )

        monkeypatch.setattr(
            TelegramTriggerService, "register_telegram_trigger", _fake_register
        )

        out = StringIO()
        call_command("backfill_telegram_webhook_secrets", stdout=out)

        assert WebhookNodeAuth.objects.filter(telegram_trigger_node=healthy).exists()
        assert not WebhookNodeAuth.objects.filter(
            telegram_trigger_node=broken
        ).exists()
        assert "Succeeded: 1" in out.getvalue()
        assert "Failed: 1" in out.getvalue()
