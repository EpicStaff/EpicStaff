import pytest
from django.urls import reverse
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.models import Secret
from tables.models.graph_models import Graph, TelegramTriggerNode
from tables.models.webhook_models import WebhookTrigger
from tables.services.secrets import secret_encryption, secret_service
from tables.services.webhook_trigger_service import WebhookTriggerService


@pytest.mark.django_db
class TestTelegramTriggerViewSet:
    def test_create_telegram_trigger_node(
        self, auth_client, graph, mock_telegram_service
    ):
        secret = secret_service.create(
            text="123456:ABC-DEF", org=graph.org, name="tg-create-key"
        )
        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "StartNode",
            "telegram_bot_api_key_secret_id": secret.id,
            "graph": graph.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "user_id",
                    "variable_path": "from.id",
                }
            ],
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == 201
        assert TelegramTriggerNode.objects.count() == 1
        assert TelegramTriggerNode.objects.first().fields.count() == 1
        # Verify signal triggered the service at least once
        assert mock_telegram_service.call_count >= 1

    def test_update_telegram_trigger_node(self, auth_client, graph, mocker):
        # 1. Mock the specific method on the Singleton class
        # This prevents the real network call during .create() and .put()
        mock_register = mocker.patch.object(
            TelegramTriggerService,
            "register_telegram_trigger",
            return_value={"ok": True},
        )

        # 2. Create the initial node (triggers signal -> uses mock)
        secret = Secret(org=graph.org, name="telegram-trigger-node-test-key")
        secret_encryption.encrypt(text="12345:fake_key").write_to(secret)
        secret.save()
        node = TelegramTriggerNode.objects.create(
            node_name="OldName",
            telegram_bot_api_key_secret=secret,
            graph=graph,
        )

        # 3. Update via API — swap to a different secret
        new_secret = secret_service.create(
            text="54321:new_fake_key", org=graph.org, name="tg-update-key"
        )
        url = reverse("telegramtriggernode-detail", args=[node.id])
        data = {
            "node_name": "NewName",
            "telegram_bot_api_key_secret_id": new_secret.id,
            "graph": graph.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "text",
                    "variable_path": "message.text",
                }
            ],
        }

        response = auth_client.put(url, data, format="json")

        # Assertions
        assert response.status_code == 200
        node.refresh_from_db()
        assert node.node_name == "NewName"
        assert node.telegram_bot_api_key_secret_id == new_secret.id
        # The secret previously attached is untouched — swapping does not rotate.
        secret.refresh_from_db()
        assert secret_encryption.decrypt(encryptedtext=secret.value) == "12345:fake_key"

        # Verify the mock was called (once for create, once for update)
        assert mock_register.call_count == 2

    def test_create_telegram_trigger_node_with_webhook_trigger(
        self, auth_client, graph, mock_telegram_service, default_org
    ):
        """
        EST-2987/EST-3491: inline trigger creation was removed — the
        telegram-trigger-nodes endpoint only accepts an *existing*
        WebhookTrigger id and links the node to it.
        """
        trigger = WebhookTrigger.objects.create(
            path="tgWebhook123", provider_type=None, org=default_org
        )
        secret = secret_service.create(
            text="123456:ABC-DEF", org=graph.org, name="tg-webhook-key"
        )

        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "TelegramWithWebhook",
            "telegram_bot_api_key_secret_id": secret.id,
            "graph": graph.id,
            "webhook_trigger": trigger.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "text",
                    "variable_path": "variables.telegram_data.user_input",
                }
            ],
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == 201, response.json()
        node = TelegramTriggerNode.objects.get(node_name="TelegramWithWebhook")
        assert node.webhook_trigger == trigger
        # Write side (POST response) still returns the plain id, unchanged.
        assert response.json()["webhook_trigger"] == trigger.id
        # service should still be called (signal)
        mock_telegram_service.assert_called()

    def test_create_telegram_trigger_node_rejects_localhost_provider(
        self, auth_client, graph, default_org
    ):
        """
        EST-3632: POST must 400 when the linked webhook_trigger uses the
        localhost provider — Telegram's setWebhook API requires a public
        HTTPS URL and can never reach a localhost tunnel. Mirrors
        TwilioChannelSerializer.validate() rejecting localhost for Twilio.
        """
        from tables.models.webhook_models import LocalhostWebhookConfig, ProviderType

        trigger = WebhookTrigger.objects.create(
            path="tg-create-localhost",
            provider_type=ProviderType.LOCALHOST,
            org=default_org,
        )
        LocalhostWebhookConfig.objects.create(
            trigger=trigger, name="tg-localhost", domain="localhost:8009"
        )

        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "TelegramLocalhostRejected",
            "telegram_bot_api_key": "123456:ABC-DEF",
            "graph": graph.id,
            "webhook_trigger": trigger.id,
            "fields": [],
        }

        response = auth_client.post(url, data, format="json")

        assert response.status_code == 400, response.json()
        assert "localhost" in str(response.json()).lower()
        assert not TelegramTriggerNode.objects.filter(
            node_name="TelegramLocalhostRejected"
        ).exists()

    def test_get_telegram_trigger_node_expands_nested_trigger_info(
        self, auth_client, graph, mock_telegram_service, default_org
    ):
        """
        GET on /api/telegram-trigger-nodes/{id}/ (and the list endpoint) must
        expand `webhook_trigger` to its full nested representation, not just
        the bare id — write side (POST/PATCH) is unaffected.

        Uses an ngrok-backed trigger (not localhost) — EST-3632 rejects
        localhost trigger config on TelegramTriggerNode create/update, so a
        localhost trigger can no longer be used here; ngrok is a publicly
        reachable equivalent for exercising the nested-expansion behavior.
        """
        from tables.models.webhook_models import NgrokWebhookConfig, ProviderType

        trigger = WebhookTrigger.objects.create(
            path="tgWebhookForGet",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        NgrokWebhookConfig.objects.create(
            trigger=trigger,
            name="tg-ngrok",
            auth_token_secret=secret_service.create(
                text="tok", org=default_org, name="tg-ngrok-secret"
            ),
        )

        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "TelegramGetNested",
            "telegram_bot_api_key": "123456:ABC-DEF",
            "graph": graph.id,
            "webhook_trigger": trigger.id,
            "fields": [],
        }
        create_response = auth_client.post(url, data, format="json")
        assert create_response.status_code == 201, create_response.json()
        assert create_response.json()["webhook_trigger"] == trigger.id
        node_id = create_response.json()["id"]

        detail = auth_client.get(
            reverse("telegramtriggernode-detail", args=[node_id])
        )
        assert detail.status_code == 200, detail.json()
        wt = detail.json()["webhook_trigger"]
        assert wt is not None
        assert wt["id"] == trigger.id
        assert wt["path"] == "tgWebhookForGet"
        assert wt["provider_type"] == "ngrok"
        assert wt["ngrok_config"]["name"] == "tg-ngrok"

        listing = auth_client.get(reverse("telegramtriggernode-list"))
        assert listing.status_code == 200
        listed = next(
            row for row in listing.json()["results"] if row["id"] == node_id
        )
        assert listed["webhook_trigger"]["path"] == "tgWebhookForGet"


@pytest.mark.django_db
class TestTelegramTriggerServiceLocalhostGuard:
    """EST-3632: TelegramTriggerService.register_telegram_trigger() must reject
    localhost-provider webhook triggers before ever calling Telegram's
    setWebhook API, mirroring TwilioChannel.validate_provider()."""

    def test_register_telegram_trigger_rejects_localhost_provider(self, default_org):
        from tables.exceptions import RegisterTelegramTriggerError
        from tables.models.webhook_models import LocalhostWebhookConfig, ProviderType

        trigger = WebhookTrigger.objects.create(
            path="tg-localhost-reject",
            provider_type=ProviderType.LOCALHOST,
            org=default_org,
        )
        LocalhostWebhookConfig.objects.create(
            trigger=trigger, name="tg-localhost", domain="localhost:8009"
        )
        secret = secret_service.create(
            text="123456:fake", org=default_org, name="tg-localhost-reject-key"
        )
        node = TelegramTriggerNode(
            node_name="LocalhostNode",
            telegram_bot_api_key_secret=secret,
            webhook_trigger=trigger,
        )

        with pytest.raises(RegisterTelegramTriggerError) as exc_info:
            TelegramTriggerService().register_telegram_trigger(node)

        assert "localhost" in str(exc_info.value).lower()

    def test_register_telegram_trigger_succeeds_with_ngrok_provider(
        self, default_org, mocker
    ):
        """Regression: an ngrok-backed trigger must still register normally
        after the EST-3632 localhost guard was added."""
        from tables.models.webhook_models import (
            NgrokWebhookConfig,
            ProviderType,
            WebhookTriggerAuthKind,
        )

        trigger = WebhookTrigger.objects.create(
            path="tg-ngrok-ok", provider_type=ProviderType.NGROK, org=default_org
        )
        NgrokWebhookConfig.objects.create(
            trigger=trigger,
            name="tg-ngrok",
            auth_token_secret=secret_service.create(
                text="tok", org=default_org, name="tg-ngrok-secret"
            ),
        )
        secret = secret_service.create(
            text="123456:fake", org=default_org, name="tg-ngrok-ok-key"
        )
        # EST-3939: the Telegram `secret_token` is now user-settable via
        # `WebhookTriggerAuth(kind=telegram)` -- registration fails loudly
        # without one, so it must be set here before the node is created.
        WebhookTriggerService().set_trigger_auth_secret(
            trigger,
            secret_service.create(
                text="tg-ngrok-ok-secret-token",
                org=default_org,
                name="tg-ngrok-ok-auth-secret",
            ),
            kind=WebhookTriggerAuthKind.TELEGRAM,
        )

        mocker.patch(
            "tables.services.webhook_trigger_service.WebhookTriggerService"
            ".get_tunnel_url_for_trigger",
            return_value="https://abcd1234.ngrok-free.app",
        )
        mock_call = mocker.patch.object(
            TelegramTriggerService, "_call_telegram_api", return_value={"ok": True}
        )
        # A real Redis publish in a unit test has 0 subscribers, so the
        # signal's own tunnel resync must be stubbed to report delivery.
        mocker.patch.object(WebhookTriggerService, "register_webhooks", return_value=True)

        # .objects.create() fires the real post_save registration, which is
        # the ONE real registration exercised by this test.
        node = TelegramTriggerNode.objects.create(
            node_name="NgrokNode",
            graph=Graph.objects.create(name="tg-ngrok-ok-graph", org=default_org),
            telegram_bot_api_key_secret=secret,
            webhook_trigger=trigger,
        )

        mock_call.assert_called_once()
        _, kwargs = mock_call.call_args
        assert kwargs["params"]["url"] == (
            "https://abcd1234.ngrok-free.app/webhooks/tg-ngrok-ok/"
        )

        # C4/EST-3862: a resync of the SAME node/trigger (e.g. another
        # unrelated resave) must not rotate the secret or re-hit Telegram's
        # setWebhook endpoint -- it's already validly registered.
        mock_call.reset_mock()
        result = TelegramTriggerService().register_telegram_trigger(node)
        assert result is None
        mock_call.assert_not_called()

        # The explicit "(re)register" action (force=True) still works.
        result = TelegramTriggerService().register_telegram_trigger(node, force=True)
        assert result == {"ok": True}
        mock_call.assert_called_once()
