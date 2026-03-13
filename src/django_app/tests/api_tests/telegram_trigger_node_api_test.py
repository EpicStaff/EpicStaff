import pytest
from django.urls import reverse
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.models.graph_models import TelegramTriggerNode
from tables.models.webhook_models import WebhookTrigger


@pytest.mark.django_db
class TestTelegramTriggerViewSet:
    def test_create_telegram_trigger_node(
        self, api_client, graph, mock_telegram_service
    ):
        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "StartNode",
            "telegram_bot_api_key": "123456:ABC-DEF",
            "graph": graph.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "user_id",
                    "variable_path": "from.id",
                }
            ],
        }

        response = api_client.post(url, data, format="json")

        assert response.status_code == 201
        assert TelegramTriggerNode.objects.count() == 1
        assert TelegramTriggerNode.objects.first().fields.count() == 1
        # Verify signal triggered the service at least once
        assert mock_telegram_service.call_count >= 1

    def test_update_telegram_trigger_node(self, api_client, graph, mocker):
        # 1. Mock the specific method on the Singleton class
        # This prevents the real network call during .create() and .put()
        mock_register = mocker.patch.object(
            TelegramTriggerService,
            "register_telegram_trigger",
            return_value={"ok": True},
        )

        # 2. Create the initial node (triggers signal -> uses mock)
        node = TelegramTriggerNode.objects.create(
            node_name="OldName",
            telegram_bot_api_key="12345:fake_key",
            graph=graph,
        )

        # 3. Update via API
        url = reverse("telegramtriggernode-detail", args=[node.id])
        data = {
            "node_name": "NewName",
            "telegram_bot_api_key": "54321:new_fake_key",
            "graph": graph.id,
            "fields": [
                {
                    "parent": "message",
                    "field_name": "text",
                    "variable_path": "message.text",
                }
            ],
        }

        response = api_client.put(url, data, format="json")

        # Assertions
        assert response.status_code == 200
        node.refresh_from_db()
        assert node.node_name == "NewName"
        assert node.telegram_bot_api_key == "54321:new_fake_key"

        # Verify the mock was called (once for create, once for update)
        assert mock_register.call_count == 2

    def test_create_telegram_trigger_node_with_webhook_trigger(
        self, api_client, graph, mock_telegram_service
    ):
        """
        Ensure that telegram-trigger-nodes endpoint accepts webhook_trigger FK
        and links the node to an existing WebhookTrigger.
        """
        trigger = WebhookTrigger.objects.create(path="tgWebhook123")

        url = reverse("telegramtriggernode-list")
        data = {
            "node_name": "TelegramWithWebhook",
            "telegram_bot_api_key": "123456:ABC-DEF",
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

        response = api_client.post(url, data, format="json")

        assert response.status_code == 201
        node = TelegramTriggerNode.objects.get(node_name="TelegramWithWebhook")
        assert node.webhook_trigger == trigger
        # service should still be called (signal)
        mock_telegram_service.assert_called()
