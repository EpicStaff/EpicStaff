"""
EST-1869: prefix-based exclusivity routing for webhook/telegram triggers has
been removed in favor of DB-driven fan-out. `WebhookTrigger`s no longer carry
a `telegram-trigger/`-prefixed tunnel-registration name -- both
`WebhookTriggerNode` and `TelegramTriggerNode` register and resolve under the
same bare `WebhookTrigger.path`, and a single `WebhookTrigger` may legitimately
be attached to both node types at once (zero, one, or both fan out).

This suite proves:

(a) the tunnel name registered by the converter is always the bare path,
    regardless of which trigger node type(s) are attached;
(b) `redis_pubsub.webhook_events_handler` fans a single inbound event out to
    both `WebhookTriggerService` and `TelegramTriggerService` independently --
    a trigger attached to both node types starts sessions for both, and one
    handler raising an exception never prevents the other from running.
"""

import json

import pytest

from tables.models.graph_models import Graph, TelegramTriggerNode, WebhookTriggerNode
from tables.models.python_models import PythonCode
from tables.models.session_models import Session
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)
from tables.services import redis_pubsub
from tables.services.converter_service import ConverterService
from tables.services.secrets import secret_service
from tables.services.session_manager_service import SessionManagerService
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService


class _FakeGraphDump:
    def model_dump(self, mode=None):
        return {}


class _FakeSessionData:
    graph = _FakeGraphDump()


def _stub_publish(monkeypatch):
    sm = SessionManagerService()
    monkeypatch.setattr(sm, "create_session_data", lambda session: _FakeSessionData())
    monkeypatch.setattr(sm.redis_service, "publish_session_data", lambda session_data: 2)
    return sm


class _FakeRedis:
    def pubsub(self):
        return object()

    def keys(self, pattern):
        return []


@pytest.mark.django_db
class TestTunnelRegistrationNameIsAlwaysBarePath:
    """EST-1869: `tunnel_registration_name` was removed -- both converters
    now always register the bare `WebhookTrigger.path`, regardless of which
    (or how many) trigger node types are attached."""

    @pytest.fixture(autouse=True)
    def _mock_telegram_signal_side_effects(self, monkeypatch):
        """`TelegramTriggerNode.objects.create()` fires
        `telegram_signals.telegram_trigger_post_save_handler`, which calls a
        REAL `WebhookTriggerService().register_webhooks()` (live Redis
        publish) and a REAL `TelegramTriggerService().register_telegram_trigger()`
        (outbound Telegram API call) on every save. This suite only cares
        about the converter's tunnel-name output, not the signal's side
        effects, so stub both to no-ops -- see
        `TestTelegramNodeAttachResyncsTunnelRegistration` below for the tests
        that actually exercise this signal."""
        monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
        monkeypatch.setattr(
            TelegramTriggerService,
            "register_telegram_trigger",
            lambda self, telegram_trigger_instance=None, **kwargs: None,
        )

    def test_telegram_linked_trigger_keeps_bare_tunnel_name(self, default_org):
        trigger = WebhookTrigger.objects.create(
            path="tg-path", provider_type=ProviderType.NGROK, org=default_org
        )
        TelegramTriggerNode.objects.create(
            node_name="tg-node", graph=Graph.objects.create(name="g", org=default_org),
            webhook_trigger=trigger,
        )
        ngrok_config = NgrokWebhookConfig.objects.create(
            name="cfg", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-secret"), trigger=trigger
        )

        pydantic_config = ConverterService().convert_ngrok_webhook_config_to_pydantic(
            ngrok_config
        )

        assert pydantic_config.name == trigger.path
        assert (
            pydantic_config.unique_id
            == f"ngrok:{trigger.path}"
            == ngrok_config.get_redis_key()
        )

    def test_telegram_linked_localhost_trigger_keeps_bare_tunnel_name(
        self, default_org
    ):
        trigger = WebhookTrigger.objects.create(
            path="tg-local-path", provider_type=ProviderType.LOCALHOST, org=default_org
        )
        TelegramTriggerNode.objects.create(
            node_name="tg-node-local",
            graph=Graph.objects.create(name="g-local", org=default_org),
            webhook_trigger=trigger,
        )
        localhost_config = LocalhostWebhookConfig.objects.create(
            name="cfg-local", trigger=trigger
        )

        pydantic_config = (
            ConverterService().convert_localhost_webhook_config_to_pydantic(
                localhost_config
            )
        )

        assert pydantic_config.name == trigger.path
        assert (
            pydantic_config.unique_id
            == f"localhost:{trigger.path}"
            == localhost_config.get_redis_key()
        )

    def test_plain_webhook_trigger_node_keeps_bare_tunnel_name(self, default_org):
        trigger = WebhookTrigger.objects.create(
            path="plain-path", provider_type=ProviderType.NGROK, org=default_org
        )
        python_code = PythonCode.objects.create(
            code="def handler(event, context): return event", entrypoint="handler"
        )
        WebhookTriggerNode.objects.create(
            node_name="plain-node",
            graph=Graph.objects.create(name="g-plain", org=default_org),
            webhook_trigger=trigger,
            python_code=python_code,
        )
        ngrok_config = NgrokWebhookConfig.objects.create(
            name="cfg-plain", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-plain-secret"), trigger=trigger
        )

        pydantic_config = ConverterService().convert_ngrok_webhook_config_to_pydantic(
            ngrok_config
        )

        assert pydantic_config.name == "plain-path"
        assert (
            pydantic_config.unique_id
            == "ngrok:plain-path"
            == ngrok_config.get_redis_key()
        )

    def test_trigger_attached_to_both_node_types_keeps_bare_tunnel_name(
        self, default_org
    ):
        """New in EST-1869: dual-attach is now legitimate and must not
        change the registered tunnel name either."""
        trigger = WebhookTrigger.objects.create(
            path="dual-path", provider_type=ProviderType.NGROK, org=default_org
        )
        python_code = PythonCode.objects.create(
            code="def handler(event, context): return event", entrypoint="handler"
        )
        graph = Graph.objects.create(name="g-dual", org=default_org)
        WebhookTriggerNode.objects.create(
            node_name="dual-webhook-node",
            graph=graph,
            webhook_trigger=trigger,
            python_code=python_code,
        )
        TelegramTriggerNode.objects.create(
            node_name="dual-telegram-node", graph=graph, webhook_trigger=trigger
        )
        ngrok_config = NgrokWebhookConfig.objects.create(
            name="cfg-dual", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-dual-secret"), trigger=trigger
        )

        pydantic_config = ConverterService().convert_ngrok_webhook_config_to_pydantic(
            ngrok_config
        )

        assert pydantic_config.name == "dual-path"

    def test_trigger_with_no_linked_node_keeps_bare_tunnel_name(self, default_org):
        """No node attached yet (config created before the node) -- must not
        error."""
        trigger = WebhookTrigger.objects.create(
            path="unlinked-path", provider_type=ProviderType.NGROK, org=default_org
        )
        ngrok_config = NgrokWebhookConfig.objects.create(
            name="cfg-unlinked", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-unlinked-secret"), trigger=trigger
        )

        pydantic_config = ConverterService().convert_ngrok_webhook_config_to_pydantic(
            ngrok_config
        )

        assert pydantic_config.name == "unlinked-path"


@pytest.mark.django_db
class TestRedisPubsubTelegramDispatch:
    """EST-1869: `webhook_events_handler` fans a single inbound event out to
    both `WebhookTriggerService` and `TelegramTriggerService` independently,
    keyed by the bare `WebhookTrigger.path` -- no more prefix-based routing
    exclusivity."""

    @pytest.fixture(autouse=True)
    def _mock_telegram_signal_side_effects(self, monkeypatch):
        """Same isolation concern as `TestTunnelRegistrationNameIsAlwaysBarePath`
        above: every `TelegramTriggerNode.objects.create()` here fires the
        real `telegram_trigger_post_save_handler`, which would otherwise
        publish to live Redis and attempt a real outbound Telegram API call.
        Stub both to no-ops; this class tests `webhook_events_handler`
        dispatch, not the attach signal itself."""
        monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
        monkeypatch.setattr(
            TelegramTriggerService,
            "register_telegram_trigger",
            lambda self, telegram_trigger_instance=None, **kwargs: None,
        )

    def _make_svc(self, monkeypatch):
        monkeypatch.setattr(
            redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: _FakeRedis()
        )
        monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
        svc = redis_pubsub.RedisPubSub()
        monkeypatch.setattr(svc, "_save_session_storage_files", lambda session: None)
        return svc

    def test_telegram_only_trigger_starts_a_session(self, default_org, monkeypatch):
        graph = Graph.objects.create(name="tg-e2e", org=default_org)
        trigger = WebhookTrigger.objects.create(
            path="tg-e2e-path", provider_type=ProviderType.NGROK, org=default_org
        )
        TelegramTriggerNode.objects.create(
            node_name="tg-e2e-node", graph=graph, webhook_trigger=trigger
        )
        NgrokWebhookConfig.objects.create(
            name="cfg-e2e", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-e2e-secret"), trigger=trigger
        )

        _stub_publish(monkeypatch)
        svc = self._make_svc(monkeypatch)

        # Telegram's registered setWebhook URL always ends in a trailing
        # slash -- the handler must normalize it before filtering.
        message = {
            "data": json.dumps(
                {
                    "path": f"{trigger.path}/",
                    "payload": {"message": {"text": "hi"}},
                    "config_id": f"ngrok:{trigger.path}",
                }
            )
        }

        svc.webhook_events_handler(message)

        assert Session.objects.filter(graph=graph).count() == 1

    def test_webhook_only_trigger_starts_a_session(self, default_org, monkeypatch):
        graph = Graph.objects.create(name="wh-e2e", org=default_org)
        trigger = WebhookTrigger.objects.create(
            path="wh-e2e-path", provider_type=ProviderType.NGROK, org=default_org
        )
        python_code = PythonCode.objects.create(
            code="def handler(event, context): return event", entrypoint="handler"
        )
        WebhookTriggerNode.objects.create(
            node_name="wh-e2e-node",
            graph=graph,
            webhook_trigger=trigger,
            python_code=python_code,
        )
        NgrokWebhookConfig.objects.create(
            name="cfg-wh-e2e", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-wh-e2e-secret"), trigger=trigger
        )

        _stub_publish(monkeypatch)
        svc = self._make_svc(monkeypatch)

        message = {
            "data": json.dumps(
                {
                    "path": trigger.path,
                    "payload": {"m": 1},
                    "config_id": f"ngrok:{trigger.path}",
                }
            )
        }

        svc.webhook_events_handler(message)

        assert Session.objects.filter(graph=graph).count() == 1

    def test_trigger_attached_to_both_node_types_fans_out_to_both(
        self, default_org, monkeypatch
    ):
        """New in EST-1869: a single event for a `WebhookTrigger` attached to
        BOTH a `WebhookTriggerNode` and a `TelegramTriggerNode` must start a
        session for each -- zero/one/two fan-out, no prefix-based exclusivity."""
        graph = Graph.objects.create(name="dual-e2e", org=default_org)
        trigger = WebhookTrigger.objects.create(
            path="dual-e2e-path", provider_type=ProviderType.NGROK, org=default_org
        )
        python_code = PythonCode.objects.create(
            code="def handler(event, context): return event", entrypoint="handler"
        )
        WebhookTriggerNode.objects.create(
            node_name="dual-e2e-webhook-node",
            graph=graph,
            webhook_trigger=trigger,
            python_code=python_code,
        )
        TelegramTriggerNode.objects.create(
            node_name="dual-e2e-telegram-node", graph=graph, webhook_trigger=trigger
        )
        NgrokWebhookConfig.objects.create(
            name="cfg-dual-e2e", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-dual-e2e-secret"), trigger=trigger
        )

        _stub_publish(monkeypatch)
        svc = self._make_svc(monkeypatch)

        message = {
            "data": json.dumps(
                {
                    "path": trigger.path,
                    "payload": {"message": {"text": "hi"}},
                    "config_id": f"ngrok:{trigger.path}",
                }
            )
        }

        svc.webhook_events_handler(message)

        assert Session.objects.filter(graph=graph).count() == 2

    def test_one_handler_raising_does_not_block_the_other(
        self, default_org, monkeypatch
    ):
        """The generic webhook branch raising must not prevent the telegram
        branch from still running for the same event."""
        graph = Graph.objects.create(name="isolation-e2e", org=default_org)
        trigger = WebhookTrigger.objects.create(
            path="isolation-e2e-path", provider_type=ProviderType.NGROK, org=default_org
        )
        TelegramTriggerNode.objects.create(
            node_name="isolation-e2e-telegram-node",
            graph=graph,
            webhook_trigger=trigger,
        )
        NgrokWebhookConfig.objects.create(
            name="cfg-isolation-e2e", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-isolation-e2e-secret"), trigger=trigger
        )

        _stub_publish(monkeypatch)
        svc = self._make_svc(monkeypatch)

        monkeypatch.setattr(
            WebhookTriggerService,
            "handle_webhook_trigger",
            lambda self, *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("boom")
            ),
        )

        message = {
            "data": json.dumps(
                {
                    "path": trigger.path,
                    "payload": {"message": {"text": "hi"}},
                    "config_id": f"ngrok:{trigger.path}",
                }
            )
        }

        svc.webhook_events_handler(message)

        assert Session.objects.filter(graph=graph).count() == 1


@pytest.mark.django_db
class TestTelegramNodeAttachResyncsTunnelRegistration:
    """Code-review-flagged gap: the realistic ordering is
    `WebhookTrigger` + `NgrokWebhookConfig`/`LocalhostWebhookConfig` created
    FIRST (the only way to obtain one is via `OrgScopedPrimaryKeyRelatedField
    (queryset=WebhookTrigger.objects.all())` on `TelegramTriggerNodeSerializer`
    -- it picks an EXISTING trigger, it never creates one), registered under
    the bare path since no Telegram node exists yet. Attaching a
    `TelegramTriggerNode` to that trigger afterward must still re-push the
    tunnel registration via `tables.signals.telegram_signals` so
    `register_telegram_trigger`'s tunnel-URL read never races a stale
    (pre-attach) tunnel connection."""

    def test_attaching_telegram_node_triggers_register_webhooks(
        self, default_org, monkeypatch
    ):
        from tables.signals import telegram_signals

        trigger = WebhookTrigger.objects.create(
            path="attach-resync-path",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        NgrokWebhookConfig.objects.create(
            name="cfg-attach", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-attach-secret"), trigger=trigger
        )

        calls = []
        monkeypatch.setattr(
            WebhookTriggerService,
            "register_webhooks",
            lambda self: calls.append("register_webhooks") or True,
        )
        monkeypatch.setattr(
            TelegramTriggerService,
            "register_telegram_trigger",
            lambda self, telegram_trigger_instance: calls.append(
                "register_telegram_trigger"
            ),
        )

        graph = Graph.objects.create(name="g-attach-resync", org=default_org)
        TelegramTriggerNode.objects.create(
            node_name="attach-resync-node", graph=graph, webhook_trigger=trigger
        )

        # Tunnel resync must happen, and BEFORE telling Telegram to
        # setWebhook -- the outbound registration must reflect the new
        # (prefixed) name before we ask Telegram to call it / before we try
        # to read its (now possibly-stale) tunnel URL.
        assert calls == ["register_webhooks", "register_telegram_trigger"]

    def test_deleting_telegram_node_resyncs_tunnel_registration(
        self, default_org, monkeypatch
    ):
        trigger = WebhookTrigger.objects.create(
            path="detach-resync-path",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        NgrokWebhookConfig.objects.create(
            name="cfg-detach", auth_token_secret=secret_service.create(text="tok", org=default_org, name="cfg-detach-secret"), trigger=trigger
        )
        graph = Graph.objects.create(name="g-detach-resync", org=default_org)
        node = TelegramTriggerNode.objects.create(
            node_name="detach-resync-node", graph=graph, webhook_trigger=trigger
        )

        calls = []
        monkeypatch.setattr(
            WebhookTriggerService,
            "register_webhooks",
            lambda self: calls.append("register_webhooks") or True,
        )

        node.delete()

        assert calls == ["register_webhooks"]
