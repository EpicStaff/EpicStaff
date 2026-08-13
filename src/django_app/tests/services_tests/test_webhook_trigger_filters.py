"""EST-3622 regression suite.

Two related classes of the same underlying bug:

1. `WebhookTriggerService.get_trigger_filters` must never let a resolved
   tunnel config_id (e.g. "ngrok:<path>") clobber the real requested path
   with something else. config_id may only disambiguate provider_type; the
   real `path` argument always drives the lookup.

2. `config_id` has the shape `"<provider>:<registered_path>"` — the segment
   after the provider is the `path` of the `WebhookTrigger` that was
   registered for that specific domain/tunnel at connect time (see
   `ConverterService.convert_ngrok_webhook_config_to_pydantic` /
   `convert_localhost_webhook_config_to_pydantic`, which build
   `name=config.trigger.path`, and `NgrokWebhookConfig.get_redis_key()` /
   `LocalhostWebhookConfig.get_redis_key()`, which use the same
   `trigger.path`). It is NOT an arbitrary `NgrokWebhookConfig.name` /
   `LocalhostWebhookConfig.name` label, and confirming ownership never needs
   a DB lookup by that label — it's a direct string comparison between the
   registered path embedded in `config_id` and the path actually requested
   in the URL. If they differ, the request arrived via a domain/tunnel that
   was registered for a *different* path than the one in the URL, and no
   flow may start — even if some other trigger elsewhere happens to have
   that path.
"""

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
from tables.services.session_manager_service import SessionManagerService
from tables.services.telegram_trigger_service import TelegramTriggerService
from tables.services.webhook_trigger_service import WebhookTriggerService


class _FakeGraphDump:
    def model_dump(self, mode=None):
        return {}


class _FakeSessionData:
    graph = _FakeGraphDump()


def _stub_publish(monkeypatch):
    """Stub the run_session tail (SessionData build + Redis publish)."""
    sm = SessionManagerService()
    monkeypatch.setattr(sm, "create_session_data", lambda session: _FakeSessionData())
    monkeypatch.setattr(
        sm.redis_service, "publish_session_data", lambda session_data: 2
    )
    return sm


def _make_webhook_trigger_node(*, graph: Graph, path: str, provider_type=None):
    trigger = WebhookTrigger.objects.create(
        path=path, provider_type=provider_type, org=graph.org
    )
    python_code = PythonCode.objects.create(
        code="def handler(event, context): return event", entrypoint="handler"
    )
    return WebhookTriggerNode.objects.create(
        node_name=f"node_{path}",
        graph=graph,
        webhook_trigger=trigger,
        python_code=python_code,
    )


def _make_telegram_trigger_node(*, graph: Graph, path: str, provider_type=None):
    trigger = WebhookTrigger.objects.create(
        path=path, provider_type=provider_type, org=graph.org
    )
    return TelegramTriggerNode.objects.create(
        node_name=f"tg_node_{path}",
        graph=graph,
        webhook_trigger=trigger,
    )


def _registered_config_id(provider: str, trigger: WebhookTrigger) -> str:
    """Build a `config_id` the way it's actually produced in production:
    `"<provider>:<registered_path>"`, where `registered_path` is the path of
    the trigger the tunnel was registered for (see module docstring) — NOT a
    config's `.name` label."""
    return f"{provider}:{trigger.path}"


@pytest.mark.django_db
class TestGetTriggerFilters:
    def test_config_id_with_matching_registered_path_adds_provider_type(
        self, default_org
    ):
        """The tunnel's registered path (embedded in config_id) matches the
        requested path — provider_type is added, nothing is rejected."""
        service = WebhookTriggerService()
        trigger = WebhookTrigger.objects.create(
            path="valid_path", provider_type=ProviderType.NGROK, org=default_org
        )
        NgrokWebhookConfig.objects.create(
            name="some-unrelated-config-name", auth_token="tok", trigger=trigger
        )

        filters = service.get_trigger_filters(
            path="valid_path",
            config_id=_registered_config_id(ProviderType.NGROK, trigger),
        )

        assert filters == {
            "webhook_trigger__path": "valid_path",
            "webhook_trigger__provider_type": "ngrok",
        }

    def test_config_id_with_mismatched_registered_path_returns_none(
        self, default_org
    ):
        """Cross-config repro: the tunnel/domain the request arrived on was
        registered for a DIFFERENT path than the one in the URL. Must return
        None — the caller must not fall back to a path-only match."""
        service = WebhookTriggerService()
        registered_trigger = WebhookTrigger.objects.create(
            path="registered_path", provider_type=ProviderType.NGROK, org=default_org
        )

        filters = service.get_trigger_filters(
            path="requested_path",
            config_id=_registered_config_id(ProviderType.NGROK, registered_trigger),
        )

        assert filters is None

    def test_config_id_with_matching_registered_path_localhost(self, default_org):
        """Same rule for the localhost provider — this is the flow id=5
        repro: LocalhostWebhookConfig(name='l1') != trigger.path('n1'), but
        the check no longer looks at the config's name field at all."""
        service = WebhookTriggerService()
        trigger = WebhookTrigger.objects.create(
            path="n1", provider_type=ProviderType.LOCALHOST, org=default_org
        )
        LocalhostWebhookConfig.objects.create(name="l1", trigger=trigger)

        filters = service.get_trigger_filters(
            path="n1",
            config_id=_registered_config_id(ProviderType.LOCALHOST, trigger),
        )

        assert filters == {
            "webhook_trigger__path": "n1",
            "webhook_trigger__provider_type": "localhost",
        }

    def test_config_id_with_mismatched_registered_path_returns_none_localhost(
        self, default_org
    ):
        service = WebhookTriggerService()
        registered_trigger = WebhookTrigger.objects.create(
            path="registered_path",
            provider_type=ProviderType.LOCALHOST,
            org=default_org,
        )

        filters = service.get_trigger_filters(
            path="requested_path",
            config_id=_registered_config_id(
                ProviderType.LOCALHOST, registered_trigger
            ),
        )

        assert filters is None

    def test_config_id_without_prefix_does_not_override_path(self):
        service = WebhookTriggerService()

        filters = service.get_trigger_filters(
            path="valid_path", config_id="bare-config-name"
        )

        assert filters == {"webhook_trigger__path": "valid_path"}

    def test_unknown_provider_prefix_is_ignored(self):
        service = WebhookTriggerService()

        filters = service.get_trigger_filters(
            path="valid_path", config_id="unknown-provider:some-name"
        )

        assert filters == {"webhook_trigger__path": "valid_path"}

    def test_missing_config_id_falls_back_to_path_only(self):
        service = WebhookTriggerService()

        filters = service.get_trigger_filters(path="valid_path", config_id=None)

        assert filters == {"webhook_trigger__path": "valid_path"}


@pytest.mark.django_db
class TestHandleWebhookTriggerConfigIsolation:
    """Reproduces the EST-3622 cross-config scenario: two ngrok configs each
    have their own domain and their own trigger/path. Hitting one domain's
    tunnel (registered for its own path) with the OTHER trigger's path in
    the URL must start nothing."""

    def test_wrong_domain_registered_path_for_requested_path_starts_no_flow(
        self, default_org, monkeypatch
    ):
        """The literal repro: the request arrived via the tunnel registered
        for path 'p2' (config_id 'ngrok:p2'), but the URL path is 'p1'. Even
        though a trigger with path 'p1' DOES exist, it wasn't reached
        through its own tunnel — no flow may start."""
        graph_1 = Graph.objects.create(name="graph-1", org=default_org)
        graph_2 = Graph.objects.create(name="graph-2", org=default_org)

        _make_webhook_trigger_node(
            graph=graph_1, path="p1", provider_type=ProviderType.NGROK
        )
        _make_webhook_trigger_node(
            graph=graph_2, path="p2", provider_type=ProviderType.NGROK
        )

        _stub_publish(monkeypatch)

        # config_id encodes the path the *tunnel* was registered for (p2),
        # not the path in the URL (p1).
        WebhookTriggerService().handle_webhook_trigger(
            path="p1",
            payload={"m": 1},
            config_id="ngrok:p2",
        )

        assert Session.objects.filter(graph=graph_1).count() == 0
        assert Session.objects.filter(graph=graph_2).count() == 0

    def test_correct_domain_and_own_path_starts_flow(self, default_org, monkeypatch):
        """No regression: hitting a tunnel registered for its own path still
        starts the flow."""
        graph_1 = Graph.objects.create(name="graph-1b", org=default_org)
        graph_2 = Graph.objects.create(name="graph-2b", org=default_org)

        _make_webhook_trigger_node(
            graph=graph_1, path="p1", provider_type=ProviderType.NGROK
        )
        _make_webhook_trigger_node(
            graph=graph_2, path="p2", provider_type=ProviderType.NGROK
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="p1",
            payload={"m": 1},
            config_id="ngrok:p1",
        )

        assert Session.objects.filter(graph=graph_1).count() == 1
        assert Session.objects.filter(graph=graph_2).count() == 0

    def test_localhost_flow_id_5_repro_starts_flow(self, default_org, monkeypatch):
        """Grounded in the real flow id=5 repro data: WebhookTrigger(path='n1',
        provider_type='localhost') behind LocalhostWebhookConfig(name='l1').
        The tunnel is registered under name='n1' (trigger.path, per the wire
        contract) — not 'l1' — so config_id is 'localhost:n1'. This must
        start the flow now that ownership no longer depends on the config's
        `.name` label."""
        graph = Graph.objects.create(name="flow-5-repro", org=default_org)
        node = _make_webhook_trigger_node(
            graph=graph, path="n1", provider_type=ProviderType.LOCALHOST
        )
        LocalhostWebhookConfig.objects.create(
            name="l1", trigger=node.webhook_trigger
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="n1",
            payload={"m": 1},
            config_id="localhost:n1",
        )

        assert Session.objects.filter(graph=graph).count() == 1

    def test_request_for_unregistered_path_starts_no_flow(self, default_org, monkeypatch):
        graph_valid = Graph.objects.create(name="graph-valid-2", org=default_org)

        _make_webhook_trigger_node(
            graph=graph_valid, path="valid_path", provider_type=ProviderType.NGROK
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="invalid_path",
            payload={"m": 1},
            config_id=None,
        )

        assert Session.objects.filter(graph=graph_valid).count() == 0


@pytest.mark.django_db
class TestHandleTelegramTriggerConfigIsolation:
    """`get_trigger_filters` is shared between `WebhookTriggerService` and
    `TelegramTriggerService` — a `None` return (config resolved to a tunnel
    registered for a different path than requested) must be honored by BOTH
    callers. `TelegramTriggerService.handle_telegram_trigger` must not blow
    up with `TypeError` on `TelegramTriggerNode.objects.filter(**None)` when
    the same cross-config mismatch occurs for a Telegram trigger."""

    @pytest.fixture(autouse=True)
    def _mock_telegram_signal_side_effects(self, monkeypatch):
        """`_make_telegram_trigger_node()` calls `TelegramTriggerNode.objects.create()`,
        which fires `telegram_signals.telegram_trigger_post_save_handler` --
        a REAL `WebhookTriggerService().register_webhooks()` Redis publish
        and a REAL outbound Telegram API call via
        `TelegramTriggerService().register_telegram_trigger()`. Stub both;
        this class tests `get_trigger_filters`/`handle_telegram_trigger`
        dispatch, not the attach signal."""
        monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
        monkeypatch.setattr(
            TelegramTriggerService,
            "register_telegram_trigger",
            lambda self, telegram_trigger_instance=None, **kwargs: None,
        )

    def test_wrong_domain_registered_path_for_requested_path_starts_no_flow(
        self, default_org, monkeypatch
    ):
        graph_1 = Graph.objects.create(name="tg-graph-1", org=default_org)
        graph_2 = Graph.objects.create(name="tg-graph-2", org=default_org)

        _make_telegram_trigger_node(
            graph=graph_1, path="tg-p1", provider_type=ProviderType.NGROK
        )
        _make_telegram_trigger_node(
            graph=graph_2, path="tg-p2", provider_type=ProviderType.NGROK
        )

        _stub_publish(monkeypatch)

        # Must not raise, and must start no flow.
        TelegramTriggerService().handle_telegram_trigger(
            path="tg-p1",
            payload={"m": 1},
            config_id="ngrok:tg-p2",
        )

        assert Session.objects.filter(graph=graph_1).count() == 0
        assert Session.objects.filter(graph=graph_2).count() == 0

    def test_correct_domain_and_own_path_starts_flow(self, default_org, monkeypatch):
        graph_1 = Graph.objects.create(name="tg-graph-1b", org=default_org)

        _make_telegram_trigger_node(
            graph=graph_1, path="tg-p1b", provider_type=ProviderType.NGROK
        )

        _stub_publish(monkeypatch)

        TelegramTriggerService().handle_telegram_trigger(
            path="tg-p1b",
            payload={"m": 1},
            config_id="ngrok:tg-p1b",
        )

        assert Session.objects.filter(graph=graph_1).count() == 1
