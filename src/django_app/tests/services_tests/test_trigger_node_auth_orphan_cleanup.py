"""Coverage for `webhook_signals._cleanup_orphaned_webhook_node_auth` /
`telegram_signals._cleanup_orphaned_telegram_node_auth` -- generalizing the
existing `kind=twilio` orphan-cleanup pattern (see
`test_twilio_channel_auth_sync.py`) to the webhook/telegram kinds.

Detaching (or deleting) the LAST `WebhookTriggerNode`/`TelegramTriggerNode`
of a given kind from a trigger must clear that trigger's `WebhookTriggerAuth`
row for that kind -- otherwise the kind stays permanently locked with no
node left to justify it, and a later attempt to reassign a different kind
is incorrectly rejected.
"""

import pytest

from tables.models.graph_models import Graph, TelegramTriggerNode, WebhookTriggerNode
from tables.models.python_models import PythonCode
from tables.models.rbac_models import Organization
from tables.models.webhook_models import (
    WebhookTrigger,
    WebhookTriggerAuth,
    WebhookTriggerAuthKind,
)
from tables.services.secrets import secret_service
from tables.services.webhook_trigger_service import WebhookTriggerService


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org NodeAuthOrphanCleanup")


def _make_trigger(org, path):
    return WebhookTrigger.objects.create(path=path, provider_type=None, org=org)


def _make_graph(org, name):
    return Graph.objects.create(name=name, org=org)


def _make_python_code():
    return PythonCode.objects.create(
        code="def handler(event, context): return event", entrypoint="handler"
    )


@pytest.mark.django_db
class TestTriggerNodeAuthOrphanCleanup:
    def test_detaching_the_last_telegram_node_clears_telegram_auth_and_frees_the_kind(
        self, org, mock_telegram_service
    ):
        trigger = _make_trigger(org, "telegram-orphan-detach")
        WebhookTriggerAuth.objects.create(
            trigger=trigger, kind=WebhookTriggerAuthKind.TELEGRAM
        )
        graph = _make_graph(org, "g-telegram-orphan-detach")
        node = TelegramTriggerNode.objects.create(
            node_name="Telegram Only", graph=graph, webhook_trigger=trigger
        )

        node.webhook_trigger = None
        node.save()

        assert not WebhookTriggerAuth.objects.filter(trigger=trigger).exists()

        # The kind is now reassignable -- switching to kind=webhook succeeds.
        # Re-fetch: `trigger`'s in-memory `.auth` reverse cache was populated
        # as a side effect of the `WebhookTriggerAuth.objects.create(trigger=
        # trigger, ...)` call above; the signal-based cleanup deletes the DB
        # row via `trigger_id` (a separate query) and has no handle on this
        # specific Python object to invalidate that cache. A fresh fetch is
        # exactly what a new request would do in production.
        trigger = WebhookTrigger.objects.get(pk=trigger.pk)
        secret = secret_service.create(
            text="epicstaff-api-key", org=org, name="orphan-webhook-secret"
        )
        auth = WebhookTriggerService().set_trigger_auth_secret(
            trigger, secret, kind=WebhookTriggerAuthKind.WEBHOOK
        )
        assert auth.kind == WebhookTriggerAuthKind.WEBHOOK

    def test_deleting_the_last_telegram_node_clears_telegram_auth(
        self, org, mock_telegram_service
    ):
        trigger = _make_trigger(org, "telegram-orphan-delete")
        WebhookTriggerAuth.objects.create(
            trigger=trigger, kind=WebhookTriggerAuthKind.TELEGRAM
        )
        graph = _make_graph(org, "g-telegram-orphan-delete")
        node = TelegramTriggerNode.objects.create(
            node_name="Telegram To Delete", graph=graph, webhook_trigger=trigger
        )

        node.delete()

        assert not WebhookTriggerAuth.objects.filter(trigger=trigger).exists()

    def test_deleting_the_last_webhook_node_clears_webhook_auth_and_frees_the_kind(
        self, org
    ):
        trigger = _make_trigger(org, "webhook-orphan-delete")
        WebhookTriggerAuth.objects.create(
            trigger=trigger, kind=WebhookTriggerAuthKind.WEBHOOK
        )
        graph = _make_graph(org, "g-webhook-orphan-delete")
        node = WebhookTriggerNode.objects.create(
            node_name="Webhook Only",
            graph=graph,
            webhook_trigger=trigger,
            python_code=_make_python_code(),
        )

        node.delete()

        assert not WebhookTriggerAuth.objects.filter(trigger=trigger).exists()

        # The kind is now reassignable -- switching to kind=telegram succeeds.
        # Re-fetch for the same reverse-cache reason noted in the telegram
        # variant of this test above.
        trigger = WebhookTrigger.objects.get(pk=trigger.pk)
        secret = secret_service.create(
            text="telegram-bot-secret-token", org=org, name="orphan-telegram-secret"
        )
        auth = WebhookTriggerService().set_trigger_auth_secret(
            trigger, secret, kind=WebhookTriggerAuthKind.TELEGRAM
        )
        assert auth.kind == WebhookTriggerAuthKind.TELEGRAM

    def test_detaching_the_last_webhook_node_clears_webhook_auth(self, org):
        trigger = _make_trigger(org, "webhook-orphan-detach")
        WebhookTriggerAuth.objects.create(
            trigger=trigger, kind=WebhookTriggerAuthKind.WEBHOOK
        )
        graph = _make_graph(org, "g-webhook-orphan-detach")
        node = WebhookTriggerNode.objects.create(
            node_name="Webhook Only",
            graph=graph,
            webhook_trigger=trigger,
            python_code=_make_python_code(),
        )

        node.webhook_trigger = None
        node.save()

        assert not WebhookTriggerAuth.objects.filter(trigger=trigger).exists()

    def test_detaching_one_of_two_webhook_nodes_sharing_a_trigger_keeps_the_auth(
        self, org
    ):
        """Regression: `webhook_trigger` has `related_name="webhook_trigger_nodes"`
        (plural) -- more than one `WebhookTriggerNode` can legally share one
        trigger (same-type fan-out). Detaching ONE must not clear the
        trigger's `kind=webhook` auth while another node still relies on it.
        """
        trigger = _make_trigger(org, "webhook-orphan-shared")
        WebhookTriggerAuth.objects.create(
            trigger=trigger, kind=WebhookTriggerAuthKind.WEBHOOK
        )
        graph = _make_graph(org, "g-webhook-orphan-shared")
        node_a = WebhookTriggerNode.objects.create(
            node_name="Webhook A",
            graph=graph,
            webhook_trigger=trigger,
            python_code=_make_python_code(),
        )
        WebhookTriggerNode.objects.create(
            node_name="Webhook B",
            graph=graph,
            webhook_trigger=trigger,
            python_code=_make_python_code(),
        )

        node_a.webhook_trigger = None
        node_a.save()

        auth = WebhookTriggerAuth.objects.get(trigger=trigger)
        assert auth.kind == WebhookTriggerAuthKind.WEBHOOK

    def test_detaching_one_of_two_telegram_nodes_sharing_a_trigger_keeps_the_auth(
        self, org, mock_telegram_service
    ):
        trigger = _make_trigger(org, "telegram-orphan-shared")
        WebhookTriggerAuth.objects.create(
            trigger=trigger, kind=WebhookTriggerAuthKind.TELEGRAM
        )
        graph = _make_graph(org, "g-telegram-orphan-shared")
        node_a = TelegramTriggerNode.objects.create(
            node_name="Telegram A", graph=graph, webhook_trigger=trigger
        )
        TelegramTriggerNode.objects.create(
            node_name="Telegram B", graph=graph, webhook_trigger=trigger
        )

        node_a.webhook_trigger = None
        node_a.save()

        auth = WebhookTriggerAuth.objects.get(trigger=trigger)
        assert auth.kind == WebhookTriggerAuthKind.TELEGRAM

    def test_repointing_a_telegram_node_cleans_up_the_old_triggers_auth(
        self, org, mock_telegram_service
    ):
        trigger_a = _make_trigger(org, "telegram-orphan-repoint-a")
        trigger_b = _make_trigger(org, "telegram-orphan-repoint-b")
        WebhookTriggerAuth.objects.create(
            trigger=trigger_a, kind=WebhookTriggerAuthKind.TELEGRAM
        )
        graph = _make_graph(org, "g-telegram-orphan-repoint")
        node = TelegramTriggerNode.objects.create(
            node_name="Telegram Repoint", graph=graph, webhook_trigger=trigger_a
        )

        node.webhook_trigger = trigger_b
        node.save()

        assert not WebhookTriggerAuth.objects.filter(trigger=trigger_a).exists()

    def test_repointing_a_webhook_node_cleans_up_the_old_triggers_auth(self, org):
        trigger_a = _make_trigger(org, "webhook-orphan-repoint-a")
        trigger_b = _make_trigger(org, "webhook-orphan-repoint-b")
        WebhookTriggerAuth.objects.create(
            trigger=trigger_a, kind=WebhookTriggerAuthKind.WEBHOOK
        )
        graph = _make_graph(org, "g-webhook-orphan-repoint")
        node = WebhookTriggerNode.objects.create(
            node_name="Webhook Repoint",
            graph=graph,
            webhook_trigger=trigger_a,
            python_code=_make_python_code(),
        )

        node.webhook_trigger = trigger_b
        node.save()

        assert not WebhookTriggerAuth.objects.filter(trigger=trigger_a).exists()
