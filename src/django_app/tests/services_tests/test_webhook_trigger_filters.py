"""EST-3622 regression: WebhookTriggerService.get_trigger_filters must never
let a resolved tunnel config_id (e.g. "ngrok:<config-name>") clobber the real
requested path. config_id may only disambiguate provider_type; the real
`path` argument always drives the lookup.
"""

import pytest

from tables.models.graph_models import Graph, WebhookTriggerNode
from tables.models.python_models import PythonCode
from tables.models.session_models import Session
from tables.models.webhook_models import ProviderType, WebhookTrigger
from tables.services.session_manager_service import SessionManagerService
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


@pytest.mark.django_db
class TestGetTriggerFilters:
    def test_config_id_suffix_does_not_override_path(self):
        """Direct unit check on get_trigger_filters: the buggy version
        overwrote webhook_trigger__path with the config_id suffix (a config
        name, not a path). It must always stay equal to the real `path` arg,
        with config_id only contributing provider_type."""
        service = WebhookTriggerService()

        filters = service.get_trigger_filters(
            path="valid_path", config_id="ngrok:some-unrelated-config-name"
        )

        assert filters == {
            "webhook_trigger__path": "valid_path",
            "webhook_trigger__provider_type": "ngrok",
        }

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


@pytest.mark.django_db
class TestHandleWebhookTriggerConfigIdIsolation:
    """Reproduces the literal EST-3622 scenario: two triggers exist under the
    same resolved tunnel config (same provider), one of which happens to
    share its "name" with the config's arbitrary label. A request for the
    genuinely correct path must start only that flow, and a bogus/unknown
    path must start none — never falling back to whatever trigger's path
    happens to match the config_id suffix."""

    def test_request_for_registered_path_starts_only_matching_flow(self, default_org, monkeypatch):
        graph_valid = Graph.objects.create(name="graph-valid", org=default_org)
        graph_other = Graph.objects.create(name="graph-other", org=default_org)

        _make_webhook_trigger_node(
            graph=graph_valid, path="valid_path", provider_type=ProviderType.NGROK
        )
        # Config's arbitrary human label coincides with this OTHER trigger's
        # path — under the old bug this is exactly what got matched instead.
        _make_webhook_trigger_node(
            graph=graph_other, path="other_path", provider_type=ProviderType.NGROK
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="valid_path",
            payload={"m": 1},
            config_id="ngrok:other_path",
        )

        assert Session.objects.filter(graph=graph_valid).count() == 1
        assert Session.objects.filter(graph=graph_other).count() == 0

    def test_request_for_unregistered_path_starts_no_flow(self, default_org, monkeypatch):
        graph_valid = Graph.objects.create(name="graph-valid-2", org=default_org)

        _make_webhook_trigger_node(
            graph=graph_valid, path="valid_path", provider_type=ProviderType.NGROK
        )

        _stub_publish(monkeypatch)

        WebhookTriggerService().handle_webhook_trigger(
            path="invalid_path",
            payload={"m": 1},
            config_id="ngrok:other_path",
        )

        assert Session.objects.filter(graph=graph_valid).count() == 0
