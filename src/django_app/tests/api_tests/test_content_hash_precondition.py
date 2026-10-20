import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import AgentNode, StartNode
from tables.models.graph_models import WebhookTriggerNode
from tables.models.python_models import PythonCode
from tables.services.secrets import secret_service
from tables.models.webhook_models import (
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)
from tests.fixtures import *


@pytest.fixture
def agent_node(graph):
    return AgentNode.objects.create(node_name="test_agent_node", graph=graph)


@pytest.fixture
def start_node(graph):
    return StartNode.objects.create(graph=graph, variables={})


# ---------------------------------------------------------------------------
# View-level: standard viewset (AgentNode)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestContentHashPreconditionViewSet:
    def test_patch_with_correct_hash_succeeds(self, auth_client, agent_node):
        url = reverse("agentnode-detail", args=[agent_node.id])
        response = auth_client.patch(
            url,
            {"node_name": "updated_name", "content_hash": agent_node.content_hash},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_patch_with_stale_hash_returns_409(self, auth_client, agent_node):
        url = reverse("agentnode-detail", args=[agent_node.id])
        response = auth_client.patch(
            url,
            {"node_name": "updated_name", "content_hash": "stale_or_wrong_hash"},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        assert response.data["code"] == "content_hash_conflict"

    def test_patch_without_hash_succeeds(self, auth_client, agent_node):
        """Omitting content_hash skips validation — backward compatible."""
        url = reverse("agentnode-detail", args=[agent_node.id])
        response = auth_client.patch(
            url,
            {"node_name": "updated_name"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_put_with_correct_hash_succeeds(self, auth_client, agent_node):
        url = reverse("agentnode-detail", args=[agent_node.id])
        response = auth_client.put(
            url,
            {
                "node_name": "replaced_name",
                "graph": agent_node.graph_id,
                "content_hash": agent_node.content_hash,
                "metadata": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_put_with_stale_hash_returns_409(self, auth_client, agent_node):
        url = reverse("agentnode-detail", args=[agent_node.id])
        response = auth_client.put(
            url,
            {
                "node_name": "replaced_name",
                "graph": agent_node.graph_id,
                "content_hash": "outdated_hash",
                "metadata": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.content

    def test_second_concurrent_update_is_rejected(self, auth_client, agent_node):
        """Simulate two users: first save wins, second is rejected with stale hash."""
        original_hash = agent_node.content_hash
        url = reverse("agentnode-detail", args=[agent_node.id])

        # User A saves successfully
        response_a = auth_client.patch(
            url,
            {"node_name": "user_a_name", "content_hash": original_hash},
            format="json",
        )
        assert response_a.status_code == status.HTTP_200_OK

        # User B still holds the original hash — their save is rejected
        response_b = auth_client.patch(
            url,
            {"node_name": "user_b_name", "content_hash": original_hash},
            format="json",
        )
        assert response_b.status_code == status.HTTP_409_CONFLICT


# ---------------------------------------------------------------------------
# View-level: StartNode (BaseGraphEntity without BaseNode)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestContentHashStartNode:
    def test_patch_with_correct_hash_succeeds(self, auth_client, start_node):
        url = reverse("startnode-detail", args=[start_node.id])
        response = auth_client.patch(
            url,
            {"variables": {"key": "value"}, "content_hash": start_node.content_hash},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_patch_with_stale_hash_returns_409(self, auth_client, start_node):
        url = reverse("startnode-detail", args=[start_node.id])
        response = auth_client.patch(
            url,
            {"variables": {"key": "value"}, "content_hash": "wrong_hash"},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.content


# ---------------------------------------------------------------------------
# Webhook node: nested python_code hash validation
# ---------------------------------------------------------------------------


@pytest.fixture
def python_code():
    return PythonCode.objects.create(
        code="def main(): return 1",
        entrypoint="main",
        libraries=[],
        global_kwargs={},
    )


@pytest.fixture
def webhook_node(graph, python_code):
    return WebhookTriggerNode.objects.create(
        node_name="webhook_node",
        graph=graph,
        python_code=python_code,
        webhook_trigger=None,
    )


@pytest.fixture
def ngrok_config(default_org):
    trigger = WebhookTrigger.objects.create(
        path="ngrokConfigFixturePath",
        provider_type=ProviderType.NGROK,
        org=default_org,
    )
    secret = secret_service.create(
        text="test_token_123", org=default_org, name="ngrok-config-fixture-secret"
    )
    return NgrokWebhookConfig.objects.create(
        name="test_ngrok",
        auth_token_secret=secret,
        region="eu",
        trigger=trigger,
    )


@pytest.mark.django_db
class TestWebhookNodeNestedHashValidation:
    def test_stale_python_code_hash_returns_409(self, auth_client, webhook_node):
        """Sending a stale python_code.content_hash must be rejected with 409."""
        url = reverse("webhooktriggernode-detail", args=[webhook_node.id])
        response = auth_client.put(
            url,
            {
                "node_name": webhook_node.node_name,
                "graph": webhook_node.graph_id,
                "python_code": {
                    "code": "def main(): return 99",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "content_hash": "stale_python_code_hash",
                },
                "webhook_trigger": None,
                "metadata": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.content

    def test_correct_python_code_hash_succeeds(self, auth_client, webhook_node):
        """Sending the current python_code.content_hash succeeds."""
        url = reverse("webhooktriggernode-detail", args=[webhook_node.id])
        response = auth_client.put(
            url,
            {
                "node_name": webhook_node.node_name,
                "graph": webhook_node.graph_id,
                "python_code": {
                    "code": "def main(): return 99",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "content_hash": webhook_node.python_code.content_hash,
                },
                "webhook_trigger": None,
                "metadata": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_node_hash_changes_after_python_code_edit(self, auth_client, webhook_node):
        """Editing python_code must change the node's content_hash too."""
        original_node_hash = webhook_node.content_hash
        url = reverse("webhooktriggernode-detail", args=[webhook_node.id])
        auth_client.put(
            url,
            {
                "node_name": webhook_node.node_name,
                "graph": webhook_node.graph_id,
                "python_code": {
                    "code": "def main(): return 999",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
                "webhook_trigger": None,
                "metadata": {},
            },
            format="json",
        )

        webhook_node.python_code.refresh_from_db()
        webhook_node.refresh_from_db()
        assert webhook_node.content_hash != original_node_hash

    def test_adding_or_removing_webhook_trigger_auth_does_not_change_node_content_hash(
        self, webhook_node, default_org
    ):
        """`WebhookTriggerAuth` now attaches to the `WebhookTrigger`, not the
        node, so it can never reach `WebhookTriggerNode._meta.fields` at all
        -- `generate_hash()` iterates only that node's own fields, so
        creating an auth row on its trigger must never perturb
        `WebhookTriggerNode.content_hash`."""
        from tables.models.webhook_models import WebhookTriggerAuth, WebhookTriggerAuthKind

        trigger = WebhookTrigger.objects.create(
            path="content-hash-lock-path", provider_type=None, org=default_org
        )
        webhook_node.webhook_trigger = trigger
        webhook_node.save()
        hash_before = webhook_node.content_hash

        secret = secret_service.create(
            text="content-hash-lock-secret",
            org=default_org,
            name="content-hash-lock-secret",
        )
        auth = WebhookTriggerAuth.objects.create(
            trigger=trigger,
            kind=WebhookTriggerAuthKind.WEBHOOK,
            secret=secret,
        )
        webhook_node.refresh_from_db()
        assert webhook_node.content_hash == hash_before

        auth.delete()
        webhook_node.refresh_from_db()
        assert webhook_node.content_hash == hash_before
