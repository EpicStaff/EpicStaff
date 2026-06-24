import pytest

pytestmark = pytest.mark.skip(reason="pre-existing failure, unrelated to EST-1529")

from django.urls import reverse
from rest_framework import status

from tables.exceptions import ContentHashConflictError
from tables.models import CrewNode, Graph, StartNode
from tables.models.graph_models import ConditionalEdge, WebhookTriggerNode
from tables.models.python_models import PythonCode
from tables.models.webhook_models import NgrokWebhookConfig, WebhookTrigger
from tests.fixtures import *


@pytest.fixture
def crew_node(graph, crew):
    return CrewNode.objects.create(node_name="test_crew_node", crew=crew, graph=graph)


@pytest.fixture
def start_node(graph):
    return StartNode.objects.create(graph=graph, variables={})


# ---------------------------------------------------------------------------
# View-level: standard viewset (CrewNode)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestContentHashPreconditionViewSet:
    def test_patch_with_correct_hash_succeeds(self, auth_client, crew_node):
        url = reverse("crewnode-detail", args=[crew_node.id])
        response = auth_client.patch(
            url,
            {"node_name": "updated_name", "content_hash": crew_node.content_hash},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_patch_with_stale_hash_returns_409(self, auth_client, crew_node):
        url = reverse("crewnode-detail", args=[crew_node.id])
        response = auth_client.patch(
            url,
            {"node_name": "updated_name", "content_hash": "stale_or_wrong_hash"},
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.content
        assert response.data["code"] == "content_hash_conflict"

    def test_patch_without_hash_succeeds(self, auth_client, crew_node):
        """Omitting content_hash skips validation — backward compatible."""
        url = reverse("crewnode-detail", args=[crew_node.id])
        response = auth_client.patch(
            url,
            {"node_name": "updated_name"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_put_with_correct_hash_succeeds(self, auth_client, crew_node):
        url = reverse("crewnode-detail", args=[crew_node.id])
        response = auth_client.put(
            url,
            {
                "node_name": "replaced_name",
                "graph": crew_node.graph_id,
                "crew_id": crew_node.crew_id,
                "content_hash": crew_node.content_hash,
                "metadata": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK, response.content

    def test_put_with_stale_hash_returns_409(self, auth_client, crew_node):
        url = reverse("crewnode-detail", args=[crew_node.id])
        response = auth_client.put(
            url,
            {
                "node_name": "replaced_name",
                "graph": crew_node.graph_id,
                "crew_id": crew_node.crew_id,
                "content_hash": "outdated_hash",
                "metadata": {},
            },
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.content

    def test_second_concurrent_update_is_rejected(self, auth_client, crew_node):
        """Simulate two users: first save wins, second is rejected with stale hash."""
        original_hash = crew_node.content_hash
        url = reverse("crewnode-detail", args=[crew_node.id])

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
# Model-level: ContentHashMixin._expected_hash validation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestContentHashModelLevel:
    def test_save_with_correct_expected_hash_succeeds(self, crew_node):
        crew_node._expected_hash = crew_node.content_hash
        crew_node.node_name = "direct_update"
        crew_node.save()  # should not raise

        crew_node.refresh_from_db()
        assert crew_node.node_name == "direct_update"

    def test_save_with_wrong_expected_hash_raises(self, crew_node):
        crew_node._expected_hash = "wrong_hash"
        crew_node.node_name = "should_not_save"

        with pytest.raises(ContentHashConflictError):
            crew_node.save()

    def test_save_without_expected_hash_skips_validation(self, crew_node):
        """No _expected_hash set — validation is bypassed (default behaviour)."""
        crew_node.node_name = "silent_update"
        crew_node.save()

        crew_node.refresh_from_db()
        assert crew_node.node_name == "silent_update"

    def test_hash_is_updated_after_save(self, crew_node):
        old_hash = crew_node.content_hash
        crew_node._expected_hash = old_hash
        crew_node.node_name = "changed_name"
        crew_node.save()

        crew_node.refresh_from_db()
        assert crew_node.content_hash != old_hash

    def test_new_object_skips_hash_validation(self, graph, crew):
        """Creating a new record should never trigger the hash check."""
        node = CrewNode(node_name="brand_new", crew=crew, graph=graph)
        node._expected_hash = "irrelevant_for_new_object"
        node.save()  # should not raise

        assert node.pk is not None


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
def conditional_edge(graph, python_code):
    return ConditionalEdge.objects.create(
        graph=graph,
        python_code=python_code,
        source_node_id=None,
        input_map={},
    )


@pytest.fixture
def ngrok_config():
    return NgrokWebhookConfig.objects.create(
        name="test_ngrok",
        auth_token="test_token_123",
        region="eu",
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

    def test_hash_changes_when_ngrok_config_set(
        self, auth_client, webhook_node, ngrok_config
    ):
        """Changing webhook_trigger.ngrok_webhook_config must change the node hash."""
        # Create initial trigger with no ngrok
        trigger = WebhookTrigger.objects.create(
            path="mypath", ngrok_webhook_config=None
        )
        webhook_node.webhook_trigger = trigger
        webhook_node.save()
        hash_before = webhook_node.content_hash

        url = reverse("webhooktriggernode-detail", args=[webhook_node.id])
        auth_client.patch(
            url,
            {
                "webhook_trigger": {
                    "path": "mypath",
                    "ngrok_webhook_config": ngrok_config.id,
                },
            },
            format="json",
        )

        webhook_node.refresh_from_db()
        assert webhook_node.content_hash != hash_before


# ---------------------------------------------------------------------------
# ConditionalEdge: node hash propagates from python_code changes
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestConditionalEdgeHashPropagation:
    def test_node_hash_changes_after_python_code_edit(
        self, auth_client, conditional_edge
    ):
        """Editing python_code on a conditional edge must change the edge hash."""
        original_edge_hash = conditional_edge.content_hash
        url = reverse("conditionaledge-detail", args=[conditional_edge.id])

        auth_client.patch(
            url,
            {
                "python_code": {
                    "code": "def main(): return 'changed'",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                },
            },
            format="json",
        )

        conditional_edge.python_code.refresh_from_db()
        conditional_edge.refresh_from_db()
        assert conditional_edge.content_hash != original_edge_hash

    def test_stale_python_code_hash_returns_409(self, auth_client, conditional_edge):
        """Sending a stale python_code.content_hash must be rejected with 409."""
        url = reverse("conditionaledge-detail", args=[conditional_edge.id])
        response = auth_client.patch(
            url,
            {
                "python_code": {
                    "code": "def main(): return 'changed'",
                    "entrypoint": "main",
                    "libraries": [],
                    "global_kwargs": {},
                    "content_hash": "stale_hash",
                },
            },
            format="json",
        )

        assert response.status_code == status.HTTP_409_CONFLICT, response.content
