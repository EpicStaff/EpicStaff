"""EST-3622 regression suite, extended for EST-3862/EST-3826 (C3) org scoping.

Three related classes of the same underlying bug:

1. `WebhookTriggerService.get_trigger_filters` must never let a resolved
   tunnel config_id (e.g. "ngrok:<org_id>:<path>") clobber the real requested
   path with something else. config_id may only disambiguate provider_type
   (and now org); the real `path` argument always drives the lookup.

2. `config_id` has the shape `"<provider>:<org_id>:<registered_path>"` (==
   `BaseTunnelConfigData.unique_id`, src/shared/models/ai_providers.py) — the
   segment after the provider is the numeric id of the org that owns the
   `WebhookTrigger` the tunnel was registered for, and the final segment is
   that trigger's `path` (see `ConverterService.convert_ngrok_webhook_config_
   to_pydantic` / `convert_localhost_webhook_config_to_pydantic`, which build
   `name=config.trigger.path, org_id=config.trigger.org_id`, and
   `NgrokWebhookConfig.get_redis_key()` / `LocalhostWebhookConfig.
   get_redis_key()`, which mirror the same format). It is NOT an arbitrary
   `NgrokWebhookConfig.name` / `LocalhostWebhookConfig.name` label, and
   confirming ownership never needs a DB lookup by that label — it's a direct
   string comparison between the registered path embedded in `config_id` and
   the path actually requested in the URL. If they differ, the request
   arrived via a domain/tunnel that was registered for a *different* path
   than the one in the URL, and no flow may start — even if some other
   trigger elsewhere happens to have that path.

3. C3 (this suite's new coverage): `WebhookTrigger.path` is only unique
   per-org (`unique_together(org, path, provider_type)`), not globally, so
   two different orgs can legally register the identical path string.
   Without an org filter, the legacy no-auth-configured fan-out
   (`config_id=None`) or a `config_id` missing its org segment could dispatch
   an inbound event across orgs into the wrong org's graph. `get_trigger_
   filters` now (a) adds `webhook_trigger__org_id` to the filter dict
   whenever `config_id` carries a parseable org segment, and (b) fails CLOSED
   -- returns `None`, no dispatch -- when `config_id` has a recognized
   provider prefix but a missing/unparseable org segment, rather than
   silently falling back to an org-unscoped filter.
"""

import pytest

from src.shared.models import UNAUTHENTICATED_FALLBACK_PRINCIPAL

from tables.models.graph_models import Graph, TelegramTriggerNode, WebhookTriggerNode
from tables.models.python_models import PythonCode
from tables.models.rbac_models import Organization
from tables.models.session_models import Session
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    WebhookAuthScheme,
    WebhookNodeAuth,
    WebhookTrigger,
)
from tables.services.session_manager_service import SessionManagerService
from tables.services.secrets import secret_service
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
    `"<provider>:<org_id>:<registered_path>"` (== `BaseTunnelConfigData.
    unique_id`), where `org_id`/`registered_path` come from the trigger the
    tunnel was registered for (see module docstring) — NOT a config's
    `.name` label."""
    return f"{provider}:{trigger.org_id}:{trigger.path}"


@pytest.mark.django_db
class TestGetTriggerFilters:
    def test_config_id_with_matching_registered_path_adds_provider_type_and_org(
        self, default_org
    ):
        """The tunnel's registered path (embedded in config_id) matches the
        requested path — provider_type and org_id are added, nothing is
        rejected."""
        service = WebhookTriggerService()
        trigger = WebhookTrigger.objects.create(
            path="valid_path", provider_type=ProviderType.NGROK, org=default_org
        )
        secret = secret_service.create(
            text="tok", org=default_org, name="some-unrelated-config-secret"
        )
        NgrokWebhookConfig.objects.create(
            name="some-unrelated-config-name",
            auth_token_secret=secret,
            trigger=trigger,
        )

        filters = service.get_trigger_filters(
            path="valid_path",
            config_id=_registered_config_id(ProviderType.NGROK, trigger),
        )

        assert filters == {
            "webhook_trigger__path": "valid_path",
            "webhook_trigger__provider_type": "ngrok",
            "webhook_trigger__org_id": default_org.id,
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
            "webhook_trigger__org_id": default_org.id,
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

    def test_unknown_provider_prefix_fails_closed(self):
        """C3 hardening: a `config_id` that claims to identify a specific
        resolved tunnel (it has a colon) but names a provider this code
        doesn't recognize must never fall back to an org-unscoped match --
        that is exactly the kind of value that must never be trusted to
        skip org scoping."""
        service = WebhookTriggerService()

        filters = service.get_trigger_filters(
            path="valid_path", config_id="unknown-provider:some-name"
        )

        assert filters is None

    def test_missing_config_id_falls_back_to_path_only(self):
        service = WebhookTriggerService()

        filters = service.get_trigger_filters(path="valid_path", config_id=None)

        assert filters == {"webhook_trigger__path": "valid_path"}

    def test_legacy_2part_config_id_with_known_provider_fails_closed(self):
        """C3: a `config_id` with a recognized provider prefix but missing
        the org segment (the pre-fix 2-part shape) must be rejected outright
        -- never silently treated as an org-unscoped path-only match."""
        service = WebhookTriggerService()

        filters = service.get_trigger_filters(
            path="valid_path", config_id="ngrok:valid_path"
        )

        assert filters is None

    def test_config_id_with_unparseable_org_segment_fails_closed(self, default_org):
        service = WebhookTriggerService()

        filters = service.get_trigger_filters(
            path="valid_path", config_id="ngrok:not-an-int:valid_path"
        )

        assert filters is None


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
        for path 'p2' (config_id 'ngrok:<org>:p2'), but the URL path is 'p1'.
        Even though a trigger with path 'p1' DOES exist, it wasn't reached
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
            config_id=f"ngrok:{default_org.id}:p2",
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
            config_id=f"ngrok:{default_org.id}:p1",
        )

        assert Session.objects.filter(graph=graph_1).count() == 1
        assert Session.objects.filter(graph=graph_2).count() == 0

    def test_localhost_flow_id_5_repro_starts_flow(self, default_org, monkeypatch):
        """Grounded in the real flow id=5 repro data: WebhookTrigger(path='n1',
        provider_type='localhost') behind LocalhostWebhookConfig(name='l1').
        The tunnel is registered under name='n1' (trigger.path, per the wire
        contract) — not 'l1' — so config_id is 'localhost:<org>:n1'. This
        must start the flow now that ownership no longer depends on the
        config's `.name` label."""
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
            config_id=f"localhost:{default_org.id}:n1",
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
            config_id=f"ngrok:{default_org.id}:tg-p2",
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
            config_id=f"ngrok:{default_org.id}:tg-p1b",
        )

        assert Session.objects.filter(graph=graph_1).count() == 1


@pytest.mark.django_db
class TestAuthPrincipalDispatchRestriction:
    """EST-3862/EST-3826: a principal-bearing event restricts fan-out to only
    the node it names; a `None`-principal event preserves today's
    unrestricted fan-out to every attached node on the path.

    Principal parsing (`"<label>:<pk>"` -> a specific `node_id`, cross-type
    label rejection) is `RedisPubSub._parse_auth_principal`'s job, not the
    service layer's -- these are service-level unit tests, so they exercise
    `handle_webhook_trigger`/`handle_telegram_trigger` with the already
    resolved `node_id` int, the shape `RedisPubSub.webhook_events_handler`
    actually calls them with.
    """

    @pytest.fixture(autouse=True)
    def _mock_telegram_signal_side_effects(self, monkeypatch):
        monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
        monkeypatch.setattr(
            TelegramTriggerService,
            "register_telegram_trigger",
            lambda self, telegram_trigger_instance=None, **kwargs: None,
        )

    def test_telegram_node_id_restricts_to_its_own_node_only(
        self, default_org, monkeypatch
    ):
        graph = Graph.objects.create(name="principal-tg-graph", org=default_org)
        trigger = WebhookTrigger.objects.create(
            path="principal-shared-path", provider_type=ProviderType.NGROK, org=default_org
        )
        telegram_node = TelegramTriggerNode.objects.create(
            node_name="principal-tg-node", graph=graph, webhook_trigger=trigger
        )
        TelegramTriggerNode.objects.create(
            node_name="principal-tg-node-other", graph=graph, webhook_trigger=trigger
        )

        _stub_publish(monkeypatch)

        TelegramTriggerService().handle_telegram_trigger(
            path="principal-shared-path",
            payload={"m": 1},
            config_id=f"ngrok:{default_org.id}:principal-shared-path",
            node_id=telegram_node.pk,
        )

        assert Session.objects.filter(graph=graph).count() == 1

    def test_webhook_node_id_restricts_to_its_own_node_only(
        self, default_org, monkeypatch
    ):
        graph = Graph.objects.create(name="principal-wh-graph", org=default_org)
        node_a = _make_webhook_trigger_node(
            graph=graph, path="principal-wh-shared", provider_type=ProviderType.NGROK
        )
        python_code = PythonCode.objects.create(
            code="def handler(event, context): return event", entrypoint="handler"
        )
        WebhookTriggerNode.objects.create(
            node_name="principal-wh-node-b",
            graph=graph,
            webhook_trigger=node_a.webhook_trigger,
            python_code=python_code,
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="principal-wh-shared",
            payload={"m": 1},
            config_id=f"ngrok:{default_org.id}:principal-wh-shared",
            node_id=node_a.pk,
        )

        assert Session.objects.filter(graph=graph).count() == 1

    def test_none_principal_preserves_unrestricted_fan_out(
        self, default_org, monkeypatch
    ):
        graph = Graph.objects.create(name="principal-none-graph", org=default_org)
        node_a = _make_webhook_trigger_node(
            graph=graph, path="principal-none-path", provider_type=ProviderType.NGROK
        )
        python_code = PythonCode.objects.create(
            code="def handler(event, context): return event", entrypoint="handler"
        )
        WebhookTriggerNode.objects.create(
            node_name="principal-none-node-b",
            graph=graph,
            webhook_trigger=node_a.webhook_trigger,
            python_code=python_code,
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="principal-none-path",
            payload={"m": 1},
            config_id=f"ngrok:{default_org.id}:principal-none-path",
            node_id=None,
        )

        assert Session.objects.filter(graph=graph).count() == 2


@pytest.mark.django_db
class TestUnauthenticatedFallbackSentinelDispatch:
    """Post-implementation dual-attach fix (EST-1869): a mixed-attach path --
    one node with mandatory/enabled auth, one node with none -- must not
    401-brick the auth-free node. `RedisPubSub.webhook_events_handler`
    recognizes `UNAUTHENTICATED_FALLBACK_PRINCIPAL` and calls both services
    with `unauthenticated_only=True`: `handle_webhook_trigger` restricts to
    nodes with no enabled `WebhookNodeAuth`; `handle_telegram_trigger`
    always no-ops, since Telegram auth is mandatory and unconditional.
    """

    @pytest.fixture(autouse=True)
    def _mock_telegram_signal_side_effects(self, monkeypatch):
        monkeypatch.setattr(WebhookTriggerService, "register_webhooks", lambda self: True)
        monkeypatch.setattr(
            TelegramTriggerService,
            "register_telegram_trigger",
            lambda self, telegram_trigger_instance=None, **kwargs: None,
        )

    def test_sentinel_restricts_webhook_dispatch_to_the_auth_free_node_only(
        self, default_org, monkeypatch
    ):
        # Separate graphs per node so which node actually dispatched is
        # unambiguous from which graph got a session.
        auth_free_graph = Graph.objects.create(
            name="sentinel-webhook-auth-free-graph", org=default_org
        )
        auth_required_graph = Graph.objects.create(
            name="sentinel-webhook-auth-required-graph", org=default_org
        )
        auth_free_node = _make_webhook_trigger_node(
            graph=auth_free_graph,
            path="sentinel-shared-path",
            provider_type=ProviderType.NGROK,
        )
        python_code = PythonCode.objects.create(
            code="def handler(event, context): return event", entrypoint="handler"
        )
        auth_required_node = WebhookTriggerNode.objects.create(
            node_name="sentinel-auth-required-node",
            graph=auth_required_graph,
            webhook_trigger=auth_free_node.webhook_trigger,
            python_code=python_code,
        )
        WebhookNodeAuth.objects.create(
            enabled=True,
            scheme=WebhookAuthScheme.HMAC_SHA256,
            header_name="X-Webhook-Signature",
            signing_secret="hmac-key",
            webhook_trigger_node=auth_required_node,
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="sentinel-shared-path",
            payload={"m": 1},
            config_id=f"ngrok:{default_org.id}:sentinel-shared-path",
            unauthenticated_only=True,
        )

        assert Session.objects.filter(graph=auth_free_graph).count() == 1
        assert Session.objects.filter(graph=auth_required_graph).count() == 0

    def test_sentinel_never_drives_a_telegram_node(self, default_org, monkeypatch):
        graph = Graph.objects.create(name="sentinel-telegram-graph", org=default_org)
        _make_telegram_trigger_node(
            graph=graph, path="sentinel-telegram-path", provider_type=ProviderType.NGROK
        )

        _stub_publish(monkeypatch)

        TelegramTriggerService().handle_telegram_trigger(
            path="sentinel-telegram-path",
            payload={"m": 1},
            config_id=f"ngrok:{default_org.id}:sentinel-telegram-path",
            unauthenticated_only=True,
        )

        assert Session.objects.filter(graph=graph).count() == 0

    def test_sentinel_never_drives_a_node_with_disabled_auth_row_marked_enabled_elsewhere(
        self, default_org, monkeypatch
    ):
        """A node whose `WebhookNodeAuth.enabled` is False counts as
        auth-free for sentinel dispatch purposes -- disabled auth means no
        credential is required, matching `ConverterService._convert_node_auth`
        (which also excludes disabled rows from `auths`)."""
        graph = Graph.objects.create(
            name="sentinel-disabled-auth-graph", org=default_org
        )
        node = _make_webhook_trigger_node(
            graph=graph,
            path="sentinel-disabled-auth-path",
            provider_type=ProviderType.NGROK,
        )
        WebhookNodeAuth.objects.create(
            enabled=False,
            scheme=WebhookAuthScheme.HMAC_SHA256,
            header_name="X-Webhook-Signature",
            signing_secret="hmac-key",
            webhook_trigger_node=node,
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="sentinel-disabled-auth-path",
            payload={"m": 1},
            config_id=f"ngrok:{default_org.id}:sentinel-disabled-auth-path",
            unauthenticated_only=True,
        )

        assert Session.objects.filter(graph=graph).count() == 1


@pytest.mark.django_db
class TestCrossOrgPathCollisionIsolation:
    """C3 (EST-3862/EST-3826 architect follow-up): two different orgs each
    legally register a `WebhookTrigger` with the IDENTICAL `path` string
    (`unique_together` is `(org, path, provider_type)`, not globally unique
    on `path`). An inbound event that resolved to one org's tunnel config
    must dispatch ONLY into that org's graph, never the other org's, even
    though both triggers share the same `path`."""

    def test_org_scoped_config_id_never_dispatches_into_the_other_orgs_graph(
        self, default_org, monkeypatch
    ):
        other_org = Organization.objects.create(name="est-3862-other-org")

        graph_default = Graph.objects.create(
            name="collision-default-org-graph", org=default_org
        )
        graph_other = Graph.objects.create(
            name="collision-other-org-graph", org=other_org
        )

        _make_webhook_trigger_node(
            graph=graph_default,
            path="collision-shared-path",
            provider_type=ProviderType.NGROK,
        )
        _make_webhook_trigger_node(
            graph=graph_other,
            path="collision-shared-path",
            provider_type=ProviderType.NGROK,
        )

        _stub_publish(monkeypatch)

        # config_id carries default_org's id -- dispatch must land only in
        # default_org's graph, never other_org's, despite the identical path.
        WebhookTriggerService().handle_webhook_trigger(
            path="collision-shared-path",
            payload={"m": 1},
            config_id=f"ngrok:{default_org.id}:collision-shared-path",
        )

        assert Session.objects.filter(graph=graph_default).count() == 1
        assert Session.objects.filter(graph=graph_other).count() == 0

    def test_other_orgs_config_id_dispatches_only_into_its_own_graph(
        self, default_org, monkeypatch
    ):
        """Symmetric case: flip which org's config_id is used -- confirms
        this isn't accidentally order- or default-org-dependent."""
        other_org = Organization.objects.create(name="est-3862-other-org-2")

        graph_default = Graph.objects.create(
            name="collision2-default-org-graph", org=default_org
        )
        graph_other = Graph.objects.create(
            name="collision2-other-org-graph", org=other_org
        )

        _make_webhook_trigger_node(
            graph=graph_default,
            path="collision2-shared-path",
            provider_type=ProviderType.NGROK,
        )
        _make_webhook_trigger_node(
            graph=graph_other,
            path="collision2-shared-path",
            provider_type=ProviderType.NGROK,
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="collision2-shared-path",
            payload={"m": 1},
            config_id=f"ngrok:{other_org.id}:collision2-shared-path",
        )

        assert Session.objects.filter(graph=graph_other).count() == 1
        assert Session.objects.filter(graph=graph_default).count() == 0
