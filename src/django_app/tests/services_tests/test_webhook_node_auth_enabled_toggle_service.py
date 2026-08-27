"""Unit coverage for `WebhookTriggerService.ensure_webhook_auth` (extended
with an `enabled` kwarg), `disable_webhook_auth`, and `sync_webhook_auth` --
the service-layer primitives backing the writable `webhook_node_auth`
`{"enabled": bool}` shape on `WebhookTriggerNodeSerializer`.
"""

import pytest

from tables.models.graph_models import Graph, WebhookTriggerNode
from tables.models.python_models import PythonCode
from tables.models.webhook_models import WebhookNodeAuth
from tables.services.webhook_trigger_service import WebhookTriggerService


def _make_node(org, graph) -> WebhookTriggerNode:
    python_code = PythonCode.objects.create(
        code="def handler(event, context): return event", entrypoint="handler"
    )
    return WebhookTriggerNode.objects.create(
        node_name="svc-toggle-node", graph=graph, python_code=python_code
    )


@pytest.mark.django_db
class TestEnsureWebhookAuth:
    def test_creates_enabled_row_with_secret_by_default(self, default_org):
        graph = Graph.objects.create(name="g-ensure-default", org=default_org)
        node = _make_node(default_org, graph)

        node_auth = WebhookTriggerService().ensure_webhook_auth(node)

        assert node_auth.enabled is True
        assert node_auth.signing_secret

    def test_creates_disabled_row_when_enabled_false(self, default_org):
        graph = Graph.objects.create(name="g-ensure-disabled", org=default_org)
        node = _make_node(default_org, graph)

        node_auth = WebhookTriggerService().ensure_webhook_auth(node, enabled=False)

        assert node_auth.enabled is False
        # a secret is still generated so a later enable doesn't need one
        assert node_auth.signing_secret

    def test_reenabling_existing_disabled_row_preserves_secret(self, default_org):
        graph = Graph.objects.create(name="g-ensure-reenable", org=default_org)
        node = _make_node(default_org, graph)
        service = WebhookTriggerService()

        first = service.ensure_webhook_auth(node)
        original_secret = first.signing_secret
        service.disable_webhook_auth(node)

        second = service.ensure_webhook_auth(node, enabled=True)

        assert second.enabled is True
        assert second.signing_secret == original_secret

    def test_idempotent_on_already_enabled_row(self, default_org):
        graph = Graph.objects.create(name="g-ensure-idempotent", org=default_org)
        node = _make_node(default_org, graph)
        service = WebhookTriggerService()

        first = service.ensure_webhook_auth(node)
        second = service.ensure_webhook_auth(node)

        assert WebhookNodeAuth.objects.filter(webhook_trigger_node=node).count() == 1
        assert second.signing_secret == first.signing_secret


@pytest.mark.django_db
class TestDisableWebhookAuth:
    def test_disables_existing_enabled_row_without_deleting(self, default_org):
        graph = Graph.objects.create(name="g-disable-existing", org=default_org)
        node = _make_node(default_org, graph)
        service = WebhookTriggerService()
        service.ensure_webhook_auth(node)

        result = service.disable_webhook_auth(node)

        assert result.enabled is False
        assert WebhookNodeAuth.objects.filter(webhook_trigger_node=node).exists()

    def test_returns_none_when_no_row_exists(self, default_org):
        graph = Graph.objects.create(name="g-disable-missing", org=default_org)
        node = _make_node(default_org, graph)

        result = WebhookTriggerService().disable_webhook_auth(node)

        assert result is None
        assert not WebhookNodeAuth.objects.filter(webhook_trigger_node=node).exists()


@pytest.mark.django_db
class TestSyncWebhookAuth:
    def test_enabled_true_delegates_to_ensure(self, default_org):
        graph = Graph.objects.create(name="g-sync-true", org=default_org)
        node = _make_node(default_org, graph)

        result = WebhookTriggerService().sync_webhook_auth(node, enabled=True)

        assert result.enabled is True

    def test_enabled_false_delegates_to_disable(self, default_org):
        graph = Graph.objects.create(name="g-sync-false", org=default_org)
        node = _make_node(default_org, graph)
        service = WebhookTriggerService()
        service.ensure_webhook_auth(node)

        result = service.sync_webhook_auth(node, enabled=False)

        assert result.enabled is False
