"""Bug fix: `WebhookTriggerNode` had no `post_save`/`post_delete` signal
receiver, unlike `TelegramTriggerNode` (`telegram_signals.py`'s
`_resync_tunnel_registration`, exercised by
`TestTelegramNodeAttachResyncsTunnelRegistration` in
`test_telegram_tunnel_registration.py`) and `WebhookNodeAuth` (fixed earlier
this session, `webhook_signals.py`).

The realistic ordering: a `WebhookTrigger` + its `NgrokWebhookConfig`/
`LocalhostWebhookConfig` are created FIRST and registered under the bare path
(no `WebhookTriggerNode` exists yet -- the serializer/API can only pick an
EXISTING trigger, never create one for a node). Attaching a
`WebhookTriggerNode` to that already-registered trigger afterward -- or
detaching one -- must still re-push the tunnel/config registration via
`tables.signals.webhook_signals`, otherwise the running `webhook` service
keeps serving a stale config that doesn't reflect the node's
`webhook_node_auth` (see `webhook_routes.py`: an empty pushed credential list
means auth verification is skipped entirely).
"""

import pytest

from tables.models.graph_models import Graph, WebhookTriggerNode
from tables.models.python_models import PythonCode
from tables.models.webhook_models import NgrokWebhookConfig, ProviderType, WebhookTrigger
from tables.services.secrets import secret_service
from tables.services.webhook_trigger_service import WebhookTriggerService


@pytest.mark.django_db
class TestWebhookTriggerNodeAttachResyncsTunnelRegistration:
    def _make_python_code(self) -> PythonCode:
        return PythonCode.objects.create(
            code="def handler(event, context): return event", entrypoint="handler"
        )

    def test_attaching_webhook_trigger_node_triggers_register_webhooks(
        self, default_org, monkeypatch
    ):
        trigger = WebhookTrigger.objects.create(
            path="wh-attach-resync-path",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        NgrokWebhookConfig.objects.create(
            name="cfg-wh-attach",
            auth_token_secret=secret_service.create(
                text="tok", org=default_org, name="cfg-wh-attach-secret"
            ),
            trigger=trigger,
        )

        calls = []
        monkeypatch.setattr(
            WebhookTriggerService,
            "register_webhooks",
            lambda self: calls.append("register_webhooks") or True,
        )

        graph = Graph.objects.create(name="g-wh-attach-resync", org=default_org)
        WebhookTriggerNode.objects.create(
            node_name="wh-attach-resync-node",
            graph=graph,
            webhook_trigger=trigger,
            python_code=self._make_python_code(),
        )

        assert calls == ["register_webhooks"]

    def test_detaching_webhook_trigger_node_resyncs_tunnel_registration(
        self, default_org, monkeypatch
    ):
        trigger = WebhookTrigger.objects.create(
            path="wh-detach-resync-path",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        NgrokWebhookConfig.objects.create(
            name="cfg-wh-detach",
            auth_token_secret=secret_service.create(
                text="tok", org=default_org, name="cfg-wh-detach-secret"
            ),
            trigger=trigger,
        )
        graph = Graph.objects.create(name="g-wh-detach-resync", org=default_org)
        node = WebhookTriggerNode.objects.create(
            node_name="wh-detach-resync-node",
            graph=graph,
            webhook_trigger=trigger,
            python_code=self._make_python_code(),
        )

        calls = []
        monkeypatch.setattr(
            WebhookTriggerService,
            "register_webhooks",
            lambda self: calls.append("register_webhooks") or True,
        )

        node.delete()

        assert calls == ["register_webhooks"]
