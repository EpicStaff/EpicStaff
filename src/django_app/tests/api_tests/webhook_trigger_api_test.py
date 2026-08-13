from unittest import mock

import pytest
from django.urls import reverse

from tables.models.graph_models import Graph, TelegramTriggerNode, WebhookTriggerNode
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.models.webhook_models import (
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)
from tables.serializers.base_serializers import WebhookTriggerNestedSerializer
from rest_framework.test import APIClient


@pytest.fixture
def other_org(db):
    return Organization.objects.create(name="Other Organization")


@pytest.fixture
def other_org_client(other_org, django_user_model):
    """A Member of `other_org` — used to prove cross-org invisibility/rejection."""
    role_member = Role.objects.get(
        name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True
    )
    user = django_user_model.objects.create_user(
        email="other-org-member@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=other_org, role=role_member)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(other_org.id))
    return client


@pytest.mark.django_db
class TestWebhookTriggerAndNodeAPI:
    def test_create_webhook_trigger(self, auth_client, default_org):
        """
        Basic smoke test for /api/webhook-triggers/ create endpoint.
        Creates a trigger with no provider (provider_type=None), lands in the
        caller's active org.
        """
        url = reverse("webhooktrigger-list")
        payload = {
            "path": "myWebhook123",
            "provider_type": None,
        }

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201
        assert WebhookTrigger.objects.count() == 1
        trigger = WebhookTrigger.objects.first()
        assert trigger.path == "myWebhook123"
        assert trigger.provider_type is None
        assert trigger.org_id == default_org.id

    def test_create_webhook_trigger_node_with_nested_trigger(
        self, auth_client, graph: Graph, default_org
    ):
        """
        Inline trigger creation from a node was removed (EST-2987/EST-3491) —
        /api/webhook-trigger-nodes/ only accepts an *existing* WebhookTrigger
        id. Create the trigger via /api/webhook-triggers/ first, then attach
        it to the node by id.
        """
        trigger_response = auth_client.post(
            reverse("webhooktrigger-list"),
            {"path": "myWebhookNested", "provider_type": None},
            format="json",
        )
        assert trigger_response.status_code == 201, trigger_response.json()
        trigger_id = trigger_response.json()["id"]

        url = reverse("webhooktriggernode-list")
        payload = {
            "node_name": "My Webhook Trigger",
            "graph": graph.id,
            "python_code": {
                "libraries": ["requests"],
                "code": "def handler(event, context):\n    return event",
                "entrypoint": "handler",
                "global_kwargs": {},
            },
            "webhook_trigger": trigger_id,
            "metadata": {},
        }

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["node_name"] == "My Webhook Trigger"
        assert data["webhook_trigger"] == trigger_id

        # WebhookTrigger should be created with no provider type, org-stamped
        trigger = WebhookTrigger.objects.get(path="myWebhookNested")
        assert trigger.provider_type is None
        assert trigger.org_id == default_org.id

    def test_create_webhook_trigger_node_without_trigger(
        self, auth_client, graph: Graph
    ):
        """
        `webhook_trigger` is optional (matches the nullable model FK) — a node
        may be created before any trigger is attached to it.
        """
        url = reverse("webhooktriggernode-list")
        payload = {
            "node_name": "No Trigger Yet",
            "graph": graph.id,
            "python_code": {
                "libraries": [],
                "code": "def handler(event, context):\n    return event",
                "entrypoint": "handler",
                "global_kwargs": {},
            },
            "metadata": {},
        }

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["webhook_trigger"] is None

    def test_create_webhook_trigger_node_with_ngrok_trigger(
        self, auth_client, graph: Graph
    ):
        """
        Create a WebhookTrigger with a nested ngrok config via
        /api/webhook-triggers/, then attach it to a node by id.
        """
        trigger_response = auth_client.post(
            reverse("webhooktrigger-list"),
            {
                "path": "myNgrokWebhook",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "test-ngrok",
                    "auth_token": "test-token-abc",
                    "domain": None,
                },
            },
            format="json",
        )
        assert trigger_response.status_code == 201, trigger_response.json()
        trigger_id = trigger_response.json()["id"]

        url = reverse("webhooktriggernode-list")
        payload = {
            "node_name": "My Ngrok Webhook Trigger",
            "graph": graph.id,
            "python_code": {
                "libraries": [],
                "code": "def handler(event, context):\n    return event",
                "entrypoint": "handler",
                "global_kwargs": {},
            },
            "webhook_trigger": trigger_id,
            "metadata": {},
        }

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["node_name"] == "My Ngrok Webhook Trigger"
        assert data["webhook_trigger"] == trigger_id

        trigger = WebhookTrigger.objects.get(path="myNgrokWebhook")
        assert trigger.provider_type == ProviderType.NGROK
        assert NgrokWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_create_webhook_trigger_node_with_localhost_trigger(
        self, auth_client, graph: Graph
    ):
        """
        Create a WebhookTrigger with a nested localhost config via
        /api/webhook-triggers/, then attach it to a node by id.
        """
        trigger_response = auth_client.post(
            reverse("webhooktrigger-list"),
            {
                "path": "myLocalhostWebhook",
                "provider_type": "localhost",
                "localhost_config": {
                    "name": "test-localhost",
                    "domain": "localhost:8080",
                },
            },
            format="json",
        )
        assert trigger_response.status_code == 201, trigger_response.json()
        trigger_id = trigger_response.json()["id"]

        url = reverse("webhooktriggernode-list")
        payload = {
            "node_name": "My Localhost Webhook Trigger",
            "graph": graph.id,
            "python_code": {
                "libraries": [],
                "code": "def handler(event, context):\n    return event",
                "entrypoint": "handler",
                "global_kwargs": {},
            },
            "webhook_trigger": trigger_id,
            "metadata": {},
        }

        response = auth_client.post(url, payload, format="json")

        assert response.status_code == 201, response.json()
        data = response.json()
        assert data["node_name"] == "My Localhost Webhook Trigger"
        assert data["webhook_trigger"] == trigger_id

        trigger = WebhookTrigger.objects.get(path="myLocalhostWebhook")
        assert trigger.provider_type == ProviderType.LOCALHOST
        assert LocalhostWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_get_webhook_trigger_node_expands_nested_trigger_info(
        self, auth_client, graph: Graph
    ):
        """
        GET on /api/webhook-trigger-nodes/{id}/ (and the list endpoint) must
        expand `webhook_trigger` to its full nested representation (path,
        provider_type, ngrok_config) instead of the bare id — the write side
        (POST/PATCH) still takes/returns a plain id.
        """
        trigger_response = auth_client.post(
            reverse("webhooktrigger-list"),
            {
                "path": "myNgrokWebhookForGet",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "get-test-ngrok",
                    "auth_token": "super-secret-value",
                    "domain": None,
                },
            },
            format="json",
        )
        assert trigger_response.status_code == 201, trigger_response.json()
        trigger_id = trigger_response.json()["id"]

        create_response = auth_client.post(
            reverse("webhooktriggernode-list"),
            {
                "node_name": "Get Nested Trigger",
                "graph": graph.id,
                "python_code": {
                    "libraries": [],
                    "code": "def handler(event, context):\n    return event",
                    "entrypoint": "handler",
                    "global_kwargs": {},
                },
                "webhook_trigger": trigger_id,
                "metadata": {},
            },
            format="json",
        )
        assert create_response.status_code == 201, create_response.json()
        # Write side (POST response) still returns the plain id, unchanged.
        assert create_response.json()["webhook_trigger"] == trigger_id
        node_id = create_response.json()["id"]

        detail = auth_client.get(
            reverse("webhooktriggernode-detail", args=[node_id])
        )
        assert detail.status_code == 200, detail.json()
        wt = detail.json()["webhook_trigger"]
        assert wt is not None
        assert wt["id"] == trigger_id
        assert wt["path"] == "myNgrokWebhookForGet"
        assert wt["provider_type"] == "ngrok"
        assert wt["ngrok_config"]["name"] == "get-test-ngrok"
        # auth_token must stay write-only/masked on the nested read (EST-3491)
        assert "auth_token" not in wt["ngrok_config"]

        listing = auth_client.get(reverse("webhooktriggernode-list"))
        assert listing.status_code == 200
        listed = next(
            row for row in listing.json()["results"] if row["id"] == node_id
        )
        assert listed["webhook_trigger"]["path"] == "myNgrokWebhookForGet"

    def test_get_webhook_trigger_node_with_no_trigger_returns_null(
        self, auth_client, graph: Graph
    ):
        create_response = auth_client.post(
            reverse("webhooktriggernode-list"),
            {
                "node_name": "No Trigger For Get",
                "graph": graph.id,
                "python_code": {
                    "libraries": [],
                    "code": "def handler(event, context):\n    return event",
                    "entrypoint": "handler",
                    "global_kwargs": {},
                },
                "metadata": {},
            },
            format="json",
        )
        assert create_response.status_code == 201, create_response.json()
        node_id = create_response.json()["id"]

        detail = auth_client.get(
            reverse("webhooktriggernode-detail", args=[node_id])
        )
        assert detail.status_code == 200
        assert detail.json()["webhook_trigger"] is None


@pytest.mark.django_db
class TestWebhookTriggerOrgIsolation:
    """EST-3491: WebhookTrigger is now a top-level org-owned resource."""

    def test_non_superadmin_can_crud_own_org_trigger(
        self, auth_client, graph: Graph, default_org
    ):
        create = auth_client.post(
            reverse("webhooktrigger-list"),
            {"path": "org-crud-path", "provider_type": None},
            format="json",
        )
        assert create.status_code == 201
        trigger_id = create.data["id"]

        # EST-3491 follow-up: /api/webhook-triggers/ only lists/retrieves
        # triggers that are actually attached to a flow trigger node — attach
        # one here so the subsequent list/update calls resolve via
        # get_queryset() as expected for a real flow-owned trigger.
        node_response = auth_client.post(
            reverse("webhooktriggernode-list"),
            {
                "node_name": "Own org CRUD node",
                "graph": graph.id,
                "python_code": {
                    "libraries": [],
                    "code": "def handler(event, context):\n    return event",
                    "entrypoint": "handler",
                    "global_kwargs": {},
                },
                "webhook_trigger": trigger_id,
                "metadata": {},
            },
            format="json",
        )
        assert node_response.status_code == 201, node_response.json()

        listing = auth_client.get(reverse("webhooktrigger-list"))
        assert listing.status_code == 200
        ids = [row["id"] for row in listing.json()["results"]]
        assert trigger_id in ids

        update = auth_client.patch(
            reverse("webhooktrigger-detail", args=[trigger_id]),
            {"path": "org-crud-path-renamed"},
            format="json",
        )
        assert update.status_code == 200
        assert WebhookTrigger.objects.get(id=trigger_id).path == "org-crud-path-renamed"

    def test_another_orgs_trigger_is_invisible(
        self, auth_client, other_org_client, other_org
    ):
        other_trigger = WebhookTrigger.objects.create(
            path="other-org-only-path", provider_type=None, org=other_org
        )
        # EST-3491 follow-up: /api/webhook-triggers/ only surfaces triggers
        # attached to a flow trigger node — attach one in other_org so the
        # "own org can see it" control below reflects a real flow-owned row.
        other_org_graph = Graph.objects.create(name="other-org-graph", org=other_org)
        node_response = other_org_client.post(
            reverse("webhooktriggernode-list"),
            {
                "node_name": "Other org node",
                "graph": other_org_graph.id,
                "python_code": {
                    "libraries": [],
                    "code": "def handler(event, context):\n    return event",
                    "entrypoint": "handler",
                    "global_kwargs": {},
                },
                "webhook_trigger": other_trigger.id,
                "metadata": {},
            },
            format="json",
        )
        assert node_response.status_code == 201, node_response.json()

        listing = auth_client.get(reverse("webhooktrigger-list"))
        assert listing.status_code == 200
        ids = [row["id"] for row in listing.json()["results"]]
        assert other_trigger.id not in ids

        detail = auth_client.get(
            reverse("webhooktrigger-detail", args=[other_trigger.id])
        )
        assert detail.status_code == 404

        # confirm the other org's own client *can* see it (control)
        own_detail = other_org_client.get(
            reverse("webhooktrigger-detail", args=[other_trigger.id])
        )
        assert own_detail.status_code == 200

    def test_reusing_path_of_another_orgs_trigger_is_rejected(
        self, auth_client, other_org
    ):
        """
        Path is a global namespace, but a trigger already claimed by another
        org (same path + provider_type) must be rejected exactly like a
        non-existent row. This is enforced by
        WebhookTriggerNestedSerializer.validate()'s (path, provider_type)
        uniqueness check, exercised via /api/webhook-triggers/ (the actual
        trigger-creation flow now that nodes only reference an existing
        trigger by id).
        """
        WebhookTrigger.objects.create(
            path="claimed-by-other-org", provider_type=None, org=other_org
        )

        response = auth_client.post(
            reverse("webhooktrigger-list"),
            {"path": "claimed-by-other-org", "provider_type": None},
            format="json",
        )
        assert response.status_code == 400
        # the other org's row must not have been reused or mutated
        assert (
            WebhookTrigger.objects.filter(path="claimed-by-other-org").count() == 1
        )

    def test_creating_node_with_webhook_trigger_int_ref_to_other_org_is_rejected(
        self, auth_client, graph: Graph, other_org
    ):
        other_trigger = WebhookTrigger.objects.create(
            path="cross-org-int-ref", provider_type=None, org=other_org
        )

        response = auth_client.post(
            reverse("webhooktriggernode-list"),
            {
                "node_name": "Cross org int ref",
                "graph": graph.id,
                "python_code": {
                    "libraries": [],
                    "code": "def handler(event, context):\n    return event",
                    "entrypoint": "handler",
                    "global_kwargs": {},
                },
                "webhook_trigger": other_trigger.id,
                "metadata": {},
            },
            format="json",
        )
        assert response.status_code == 400

    def test_non_superadmin_can_set_ngrok_config_on_own_org_trigger(
        self, auth_client
    ):
        response = auth_client.post(
            reverse("webhooktrigger-list"),
            {
                "path": "own-org-ngrok",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "own-org-ngrok-config",
                    "auth_token": "secret-token-value",
                    "domain": None,
                },
            },
            format="json",
        )
        assert response.status_code == 201, response.json()
        trigger = WebhookTrigger.objects.get(path="own-org-ngrok")
        assert NgrokWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_auth_token_absent_from_get_response(self, auth_client, graph: Graph):
        create = auth_client.post(
            reverse("webhooktrigger-list"),
            {
                "path": "hide-auth-token",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "hide-token-config",
                    "auth_token": "super-secret-value",
                    "domain": None,
                },
            },
            format="json",
        )
        assert create.status_code == 201, create.json()
        trigger_id = create.json()["id"]

        # WebhookTriggerViewSet.get_queryset only surfaces triggers attached
        # to a flow trigger node — attach one so the detail lookup below
        # resolves for a real flow-owned trigger.
        node_response = auth_client.post(
            reverse("webhooktriggernode-list"),
            {
                "node_name": "Ngrok auth token hidden",
                "graph": graph.id,
                "python_code": {
                    "libraries": [],
                    "code": "def handler(event, context):\n    return event",
                    "entrypoint": "handler",
                    "global_kwargs": {},
                },
                "webhook_trigger": trigger_id,
                "metadata": {},
            },
            format="json",
        )
        assert node_response.status_code == 201, node_response.json()

        detail = auth_client.get(reverse("webhooktrigger-detail", args=[trigger_id]))
        assert detail.status_code == 200
        ngrok_config = detail.json()["ngrok_config"]
        assert "auth_token" not in ngrok_config


@pytest.mark.django_db
class TestWebhookTriggerProviderSwitchCleanup:
    """Cover WebhookTriggerNestedSerializer.update — switching provider_type
    must delete the orphan config from the previous provider in both
    directions, and when the provider is cleared entirely."""

    def _update(self, instance, data):
        serializer = WebhookTriggerNestedSerializer()
        return serializer.update(instance, data)

    def test_switch_ngrok_to_localhost_deletes_ngrok_config(self, default_org):
        trigger = WebhookTrigger.objects.create(
            path="switchNgrokToLocal", provider_type=ProviderType.NGROK, org=default_org
        )
        NgrokWebhookConfig.objects.create(trigger=trigger, name="ng", auth_token="tok")

        self._update(
            trigger,
            {
                "provider_type": ProviderType.LOCALHOST,
                "localhost_config": {"name": "lh", "domain": "localhost:8080"},
            },
        )

        trigger.refresh_from_db()
        assert trigger.provider_type == ProviderType.LOCALHOST
        assert LocalhostWebhookConfig.objects.filter(trigger=trigger).exists()
        assert not NgrokWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_switch_localhost_to_ngrok_deletes_localhost_config(self, default_org):
        trigger = WebhookTrigger.objects.create(
            path="switchLocalToNgrok", provider_type=ProviderType.LOCALHOST, org=default_org
        )
        LocalhostWebhookConfig.objects.create(
            trigger=trigger, name="lh", domain="localhost:8080"
        )

        self._update(
            trigger,
            {
                "provider_type": ProviderType.NGROK,
                "ngrok_config": {"name": "ng", "auth_token": "tok", "domain": None},
            },
        )

        trigger.refresh_from_db()
        assert trigger.provider_type == ProviderType.NGROK
        assert NgrokWebhookConfig.objects.filter(trigger=trigger).exists()
        assert not LocalhostWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_update_deletes_orphan_independent_of_new_config_presence(self, default_org):
        """Internal `update()` contract: cleanup of the old provider's config
        must not depend on the new provider's config being supplied.

        Note: via the API, `validate()` rejects provider=ngrok/localhost
        without the matching config, so this exact payload can't reach the
        endpoint — but the cleanup must not be coupled to config presence
        (the original bug nested deletion inside the `and X_data` branch).
        The real API-reachable case of this class of bug is covered by
        `test_clear_provider_deletes_existing_config`."""
        trigger = WebhookTrigger.objects.create(
            path="switchNoData", provider_type=ProviderType.NGROK, org=default_org
        )
        NgrokWebhookConfig.objects.create(trigger=trigger, name="ng", auth_token="tok")

        self._update(trigger, {"provider_type": ProviderType.LOCALHOST})

        trigger.refresh_from_db()
        assert trigger.provider_type == ProviderType.LOCALHOST
        assert not NgrokWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_clear_provider_deletes_existing_config(self, default_org):
        trigger = WebhookTrigger.objects.create(
            path="clearProvider", provider_type=ProviderType.LOCALHOST, org=default_org
        )
        LocalhostWebhookConfig.objects.create(
            trigger=trigger, name="lh", domain="localhost:8080"
        )

        self._update(trigger, {"provider_type": None})

        trigger.refresh_from_db()
        assert trigger.provider_type is None
        assert not LocalhostWebhookConfig.objects.filter(trigger=trigger).exists()

    def test_no_provider_change_keeps_config(self, default_org):
        """Same provider + new config data updates in place, no deletion."""
        trigger = WebhookTrigger.objects.create(
            path="sameProvider", provider_type=ProviderType.NGROK, org=default_org
        )
        NgrokWebhookConfig.objects.create(trigger=trigger, name="ng", auth_token="old")

        self._update(
            trigger,
            {
                "provider_type": ProviderType.NGROK,
                "ngrok_config": {"name": "ng", "auth_token": "new", "domain": None},
            },
        )

        trigger.refresh_from_db()
        assert trigger.provider_type == ProviderType.NGROK
        cfg = NgrokWebhookConfig.objects.get(trigger=trigger)
        assert cfg.auth_token == "new"


@pytest.mark.django_db
class TestWebhookTriggerTwilioOnlyVisibility:
    """EST-3491 follow-up, corrected: /api/webhook-triggers/ exposes every
    WebhookTrigger in the org regardless of what else references it.
    WebhookTrigger is a standalone resource — a row also reused by
    TwilioChannelSerializer (an AGENTS-domain concern) has no bearing on its
    visibility through this Flows endpoint."""

    def test_twilio_only_trigger_remains_visible(self, auth_client, default_org):
        from tables.models.webhook_models import RealtimeChannel, TwilioChannel

        twilio_only_trigger = WebhookTrigger.objects.create(
            path="twilio-only-path", provider_type=None, org=default_org
        )
        realtime_channel = RealtimeChannel.objects.create(
            name="twilio-only-channel", org=default_org
        )
        TwilioChannel.objects.create(
            channel=realtime_channel,
            account_sid="AC_test",
            auth_token="auth_test",
            webhook_trigger=twilio_only_trigger,
        )

        listing = auth_client.get(reverse("webhooktrigger-list"))
        assert listing.status_code == 200
        ids = [row["id"] for row in listing.json()["results"]]
        assert twilio_only_trigger.id in ids

        detail = auth_client.get(
            reverse("webhooktrigger-detail", args=[twilio_only_trigger.id])
        )
        assert detail.status_code == 200

    def test_trigger_with_flow_node_and_twilio_only_trigger_both_remain_visible(
        self, auth_client, graph: Graph, default_org
    ):
        from tables.models.webhook_models import RealtimeChannel, TwilioChannel

        # A Twilio-only trigger in the same org, to prove it stays visible too.
        twilio_only_trigger = WebhookTrigger.objects.create(
            path="twilio-only-sibling", provider_type=None, org=default_org
        )
        realtime_channel = RealtimeChannel.objects.create(
            name="twilio-only-sibling-channel", org=default_org
        )
        TwilioChannel.objects.create(
            channel=realtime_channel,
            account_sid="AC_test",
            auth_token="auth_test",
            webhook_trigger=twilio_only_trigger,
        )

        # A real flow-owned trigger: created via /api/webhook-triggers/, then
        # attached to a node by id (inline node creation was removed).
        trigger_response = auth_client.post(
            reverse("webhooktrigger-list"),
            {"path": "flow-owned-path", "provider_type": None},
            format="json",
        )
        assert trigger_response.status_code == 201, trigger_response.json()
        flow_owned_trigger_id = trigger_response.json()["id"]

        node_response = auth_client.post(
            reverse("webhooktriggernode-list"),
            {
                "node_name": "Flow owned trigger",
                "graph": graph.id,
                "python_code": {
                    "libraries": [],
                    "code": "def handler(event, context):\n    return event",
                    "entrypoint": "handler",
                    "global_kwargs": {},
                },
                "webhook_trigger": flow_owned_trigger_id,
                "metadata": {},
            },
            format="json",
        )
        assert node_response.status_code == 201, node_response.json()
        flow_owned_trigger = WebhookTrigger.objects.get(path="flow-owned-path")

        listing = auth_client.get(reverse("webhooktrigger-list"))
        assert listing.status_code == 200
        ids = [row["id"] for row in listing.json()["results"]]
        assert flow_owned_trigger.id in ids
        assert twilio_only_trigger.id in ids


@pytest.mark.django_db
class TestWebhookTriggerDuplicatePathValidation:
    """EST-3620: PUT/PATCH to /api/webhook-triggers/<id>/ with a (path,
    provider_type) pair that collides with another existing WebhookTrigger
    must fail cleanly with a serializer ValidationError (-> 400), not blow
    up with a raw IntegrityError from the DB's unique_together constraint at
    save time."""

    def test_full_update_colliding_path_and_provider_is_rejected(self, default_org):
        """Full PUT-style call (all fields present) with a path that
        collides with another trigger's (path, provider_type) is rejected
        by validate() before hitting the DB."""
        WebhookTrigger.objects.create(
            path="taken-path", provider_type=ProviderType.NGROK, org=default_org
        )
        other_trigger = WebhookTrigger.objects.create(
            path="my-own-path", provider_type=ProviderType.NGROK, org=default_org
        )

        serializer = WebhookTriggerNestedSerializer(
            instance=other_trigger,
            data={
                "path": "taken-path",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "ng",
                    "auth_token": "tok",
                    "domain": None,
                },
            },
        )

        assert not serializer.is_valid()
        assert "non_field_errors" in serializer.errors
        assert (
            "already exists" in str(serializer.errors["non_field_errors"][0]).lower()
        )
        # nothing was mutated at the DB level
        other_trigger.refresh_from_db()
        assert other_trigger.path == "my-own-path"

    def test_partial_update_omitting_provider_type_still_detects_collision(
        self, default_org
    ):
        """The actual bug repro (EST-3620): a PATCH-style partial update
        supplies only `path` and omits `provider_type` from the payload.
        The fallback to self.instance.provider_type must still catch a
        collision with another trigger sharing that provider_type — before
        the fix, data.get("provider_type") returned None here and the
        duplicate check silently no-opped."""
        WebhookTrigger.objects.create(
            path="taken-ngrok-path", provider_type=ProviderType.NGROK, org=default_org
        )
        other_trigger = WebhookTrigger.objects.create(
            path="my-ngrok-path", provider_type=ProviderType.NGROK, org=default_org
        )

        serializer = WebhookTriggerNestedSerializer(
            instance=other_trigger,
            data={"path": "taken-ngrok-path"},
            partial=True,
        )

        assert not serializer.is_valid()
        assert "non_field_errors" in serializer.errors
        assert (
            "already exists" in str(serializer.errors["non_field_errors"][0]).lower()
        )
        other_trigger.refresh_from_db()
        assert other_trigger.path == "my-ngrok-path"

    def test_partial_update_to_new_non_colliding_path_succeeds(self, default_org):
        """Sanity check: renaming a trigger's path to something new and
        non-colliding must still succeed (no false positive from the
        duplicate check)."""
        trigger = WebhookTrigger.objects.create(
            path="original-path", provider_type=ProviderType.NGROK, org=default_org
        )
        NgrokWebhookConfig.objects.create(trigger=trigger, name="ng", auth_token="tok")

        serializer = WebhookTriggerNestedSerializer(
            instance=trigger,
            data={"path": "brand-new-unique-path"},
            partial=True,
        )

        assert serializer.is_valid(), serializer.errors
        updated = serializer.save()
        assert updated.path == "brand-new-unique-path"


@pytest.mark.django_db
class TestWebhookTriggerCreateDoesNotMerge:
    """EST-3625: POSTing a `path` that collides with an existing trigger must
    never silently mutate/merge into that other row. `create()` is a plain
    insert; `validate()` (already covered by EST-3620 tests above) is the
    only thing allowed to reject a request before it reaches `create()`."""

    def test_duplicate_path_and_provider_type_is_rejected_not_merged(
        self, auth_client, default_org
    ):
        """An exact (path, provider_type) duplicate must be rejected with a
        clean validation error, and must not mutate the existing row."""
        existing = WebhookTrigger.objects.create(
            path="dup-path-same-provider",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        NgrokWebhookConfig.objects.create(
            trigger=existing, name="original-ngrok", auth_token="original-token"
        )

        response = auth_client.post(
            reverse("webhooktrigger-list"),
            {
                "path": "dup-path-same-provider",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "hijack-attempt",
                    "auth_token": "hijack-token",
                    "domain": None,
                },
            },
            format="json",
        )

        assert response.status_code == 400
        # exactly one row for this (path, provider_type) — no merge, no new row
        assert (
            WebhookTrigger.objects.filter(
                path="dup-path-same-provider", provider_type=ProviderType.NGROK
            ).count()
            == 1
        )
        existing.refresh_from_db()
        assert existing.provider_type == ProviderType.NGROK
        ngrok_config = NgrokWebhookConfig.objects.get(trigger=existing)
        assert ngrok_config.name == "original-ngrok"
        assert ngrok_config.auth_token == "original-token"

    def test_same_path_different_provider_type_creates_separate_row(
        self, auth_client, default_org
    ):
        """The model's actual constraint is unique_together(path,
        provider_type) — two different providers ARE allowed to share a
        path as separate rows. POSTing a new provider_type for an existing
        path must create a sibling row, not hijack/mutate the existing one
        (the EST-3625 bug: the old get_or_create looked up by `path` alone)."""
        existing = WebhookTrigger.objects.create(
            path="shared-path-diff-provider",
            provider_type=ProviderType.LOCALHOST,
            org=default_org,
        )
        LocalhostWebhookConfig.objects.create(
            trigger=existing, name="local-cfg", domain="localhost:9000"
        )

        response = auth_client.post(
            reverse("webhooktrigger-list"),
            {
                "path": "shared-path-diff-provider",
                "provider_type": "ngrok",
                "ngrok_config": {
                    "name": "new-ngrok-cfg",
                    "auth_token": "new-token",
                    "domain": None,
                },
            },
            format="json",
        )

        assert response.status_code == 201, response.json()
        new_trigger_id = response.json()["id"]
        assert new_trigger_id != existing.id

        rows = WebhookTrigger.objects.filter(path="shared-path-diff-provider")
        assert rows.count() == 2

        # the original row must be untouched — same provider, config intact
        existing.refresh_from_db()
        assert existing.provider_type == ProviderType.LOCALHOST
        assert LocalhostWebhookConfig.objects.filter(trigger=existing).exists()
        local_cfg = LocalhostWebhookConfig.objects.get(trigger=existing)
        assert local_cfg.name == "local-cfg"

        # the new row is a genuinely separate WebhookTrigger with its own config
        new_trigger = WebhookTrigger.objects.get(id=new_trigger_id)
        assert new_trigger.provider_type == ProviderType.NGROK
        assert NgrokWebhookConfig.objects.filter(trigger=new_trigger).exists()

    def test_fresh_unique_path_creates_normally(self, auth_client, default_org):
        """No-regression sanity check: a normal POST with a fresh, unique
        path still creates a single new WebhookTrigger as before."""
        response = auth_client.post(
            reverse("webhooktrigger-list"),
            {"path": "brand-new-fresh-path", "provider_type": None},
            format="json",
        )

        assert response.status_code == 201, response.json()
        trigger = WebhookTrigger.objects.get(path="brand-new-fresh-path")
        assert trigger.provider_type is None
        assert trigger.org_id == default_org.id
        assert WebhookTrigger.objects.filter(path="brand-new-fresh-path").count() == 1


@pytest.mark.django_db
class TestWebhookTriggerLiveUrlIncludesPath:
    """EST-3626: `WebhookTriggerNestedSerializer.to_representation()` must
    return the full routable URL (`<tunnel-base>/webhooks/<path>`), not just
    the bare tunnel base, since that's the actual inbound route the
    `webhook` service exposes (`POST /webhooks/{custom_path:path}` in
    `src/webhook/app/controllers/webhook_routes.py`)."""

    def test_live_url_appends_trigger_path_when_tunnel_url_available(
        self, default_org
    ):
        trigger = WebhookTrigger.objects.create(
            path="my-trigger-path",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        NgrokWebhookConfig.objects.create(
            trigger=trigger, name="ng", auth_token="tok"
        )

        with mock.patch(
            "tables.services.webhook_trigger_service.WebhookTriggerService"
            ".get_tunnel_url_for_trigger",
            return_value="https://abcd1234.ngrok-free.app",
        ):
            data = WebhookTriggerNestedSerializer(trigger).data

        assert (
            data["live_url"]
            == "https://abcd1234.ngrok-free.app/webhooks/my-trigger-path"
        )

    def test_live_url_stays_bare_path_for_telegram_linked_trigger(
        self, default_org
    ):
        """EST-1869: prefix-based exclusivity routing was removed --
        `live_url` always reflects the bare path now, even for a trigger
        linked to a `TelegramTriggerNode`."""
        trigger = WebhookTrigger.objects.create(
            path="tg-live-url-path",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        TelegramTriggerNode.objects.create(
            node_name="tg-live-url-node",
            graph=Graph.objects.create(name="g-live-url", org=default_org),
            webhook_trigger=trigger,
        )
        NgrokWebhookConfig.objects.create(
            trigger=trigger, name="ng-tg", auth_token="tok"
        )

        with mock.patch(
            "tables.services.webhook_trigger_service.WebhookTriggerService"
            ".get_tunnel_url_for_trigger",
            return_value="https://abcd1234.ngrok-free.app",
        ):
            data = WebhookTriggerNestedSerializer(trigger).data

        assert (
            data["live_url"]
            == "https://abcd1234.ngrok-free.app/webhooks/tg-live-url-path"
        )

    def test_live_url_stays_none_when_no_tunnel_url_available(self, default_org):
        """No live tunnel yet -> live_url must stay None, not become
        `None/<path>`."""
        trigger = WebhookTrigger.objects.create(
            path="my-trigger-path",
            provider_type=ProviderType.NGROK,
            org=default_org,
        )
        NgrokWebhookConfig.objects.create(
            trigger=trigger, name="ng", auth_token="tok"
        )

        with mock.patch(
            "tables.services.webhook_trigger_service.WebhookTriggerService"
            ".get_tunnel_url_for_trigger",
            return_value=None,
        ):
            data = WebhookTriggerNestedSerializer(trigger).data

        assert data["live_url"] is None


@pytest.mark.django_db
class TestCrossTypeTriggerNodeConflictValidation:
    """EST-1869: a single `WebhookTrigger` may now legitimately be attached
    to BOTH a `WebhookTriggerNode` and a `TelegramTriggerNode` at the same
    time -- DB-driven fan-out in `redis_pubsub.webhook_events_handler` means
    each node type is resolved and notified independently, so dual-attach no
    longer breaks either registration scheme. Covered here at the
    serializer/API layer for both directions, plus regression checks for the
    unaffected single-type flows and same-instance re-save."""

    def _webhook_node_payload(self, node_name, graph, webhook_trigger_id="__unset__"):
        payload = {
            "node_name": node_name,
            "graph": graph.id,
            "python_code": {
                "libraries": [],
                "code": "def handler(event, context):\n    return event",
                "entrypoint": "handler",
                "global_kwargs": {},
            },
            "metadata": {},
        }
        if webhook_trigger_id != "__unset__":
            payload["webhook_trigger"] = webhook_trigger_id
        return payload

    def _telegram_node_payload(self, node_name, graph, webhook_trigger_id="__unset__"):
        payload = {
            "node_name": node_name,
            "telegram_bot_api_key": "123456:ABC-DEF",
            "graph": graph.id,
            "fields": [],
        }
        if webhook_trigger_id != "__unset__":
            payload["webhook_trigger"] = webhook_trigger_id
        return payload

    def test_creating_telegram_node_on_trigger_already_claimed_by_webhook_node_allowed(
        self, auth_client, graph: Graph, default_org, mock_telegram_service
    ):
        trigger = WebhookTrigger.objects.create(
            path="claimed-by-webhook-node", provider_type=None, org=default_org
        )
        webhook_create = auth_client.post(
            reverse("webhooktriggernode-list"),
            self._webhook_node_payload("Webhook Owner", graph, trigger.id),
            format="json",
        )
        assert webhook_create.status_code == 201, webhook_create.json()

        response = auth_client.post(
            reverse("telegramtriggernode-list"),
            self._telegram_node_payload("Telegram Conflict", graph, trigger.id),
            format="json",
        )

        assert response.status_code == 201, response.json()
        assert TelegramTriggerNode.objects.filter(
            node_name="Telegram Conflict", webhook_trigger=trigger
        ).exists()
        assert WebhookTriggerNode.objects.filter(
            node_name="Webhook Owner", webhook_trigger=trigger
        ).exists()

    def test_creating_webhook_node_on_trigger_already_claimed_by_telegram_node_allowed(
        self, auth_client, graph: Graph, default_org, mock_telegram_service
    ):
        trigger = WebhookTrigger.objects.create(
            path="claimed-by-telegram-node", provider_type=None, org=default_org
        )
        telegram_create = auth_client.post(
            reverse("telegramtriggernode-list"),
            self._telegram_node_payload("Telegram Owner", graph, trigger.id),
            format="json",
        )
        assert telegram_create.status_code == 201, telegram_create.json()

        response = auth_client.post(
            reverse("webhooktriggernode-list"),
            self._webhook_node_payload("Webhook Conflict", graph, trigger.id),
            format="json",
        )

        assert response.status_code == 201, response.json()
        assert WebhookTriggerNode.objects.filter(
            node_name="Webhook Conflict", webhook_trigger=trigger
        ).exists()
        assert TelegramTriggerNode.objects.filter(
            node_name="Telegram Owner", webhook_trigger=trigger
        ).exists()

    def test_trigger_attached_to_both_node_types_fans_out_via_real_api_create_path(
        self, auth_client, graph: Graph, default_org, mock_telegram_service, monkeypatch
    ):
        """End-to-end regression guard: a `WebhookTrigger` created through the
        real API and attached to both node types must fan out to both
        services on an inbound event -- not just pass serializer validation."""
        import json

        from tables.services import redis_pubsub
        from tables.services.session_manager_service import SessionManagerService
        from tables.models.session_models import Session

        trigger = WebhookTrigger.objects.create(
            path="dual-attach-api-path", provider_type=None, org=default_org
        )
        webhook_create = auth_client.post(
            reverse("webhooktriggernode-list"),
            self._webhook_node_payload("Dual API Webhook", graph, trigger.id),
            format="json",
        )
        assert webhook_create.status_code == 201, webhook_create.json()

        telegram_create = auth_client.post(
            reverse("telegramtriggernode-list"),
            self._telegram_node_payload("Dual API Telegram", graph, trigger.id),
            format="json",
        )
        assert telegram_create.status_code == 201, telegram_create.json()

        class _FakeGraphDump:
            def model_dump(self, mode=None):
                return {}

        class _FakeSessionData:
            graph = _FakeGraphDump()

        sm = SessionManagerService()
        monkeypatch.setattr(
            sm, "create_session_data", lambda session: _FakeSessionData()
        )
        monkeypatch.setattr(
            sm.redis_service, "publish_session_data", lambda session_data: 2
        )

        class _FakeRedis:
            def pubsub(self):
                return object()

            def keys(self, pattern):
                return []

        monkeypatch.setattr(
            redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: _FakeRedis()
        )
        monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
        svc = redis_pubsub.RedisPubSub()
        monkeypatch.setattr(svc, "_save_session_storage_files", lambda session: None)

        message = {
            "data": json.dumps(
                {
                    "path": trigger.path,
                    "payload": {"m": 1},
                    "config_id": None,
                }
            )
        }

        svc.webhook_events_handler(message)

        assert Session.objects.filter(graph=graph).count() == 2

    def test_normal_single_type_webhook_node_create_update_detach_reattach_unaffected(
        self, auth_client, graph: Graph, default_org
    ):
        """Regression guard: the ordinary single-type flow (attach, re-save,
        detach, reattach to a different trigger) for `WebhookTriggerNode`
        must keep working unaffected by the new cross-type check."""
        trigger_a = WebhookTrigger.objects.create(
            path="webhook-node-flow-a", provider_type=None, org=default_org
        )
        trigger_b = WebhookTrigger.objects.create(
            path="webhook-node-flow-b", provider_type=None, org=default_org
        )

        create = auth_client.post(
            reverse("webhooktriggernode-list"),
            self._webhook_node_payload("Webhook Flow Node", graph, trigger_a.id),
            format="json",
        )
        assert create.status_code == 201, create.json()
        node_id = create.json()["id"]

        # re-save with the same trigger (legitimate owner re-saving itself)
        resave = auth_client.put(
            reverse("webhooktriggernode-detail", args=[node_id]),
            self._webhook_node_payload("Webhook Flow Node", graph, trigger_a.id),
            format="json",
        )
        assert resave.status_code == 200, resave.json()

        # detach
        detach = auth_client.put(
            reverse("webhooktriggernode-detail", args=[node_id]),
            self._webhook_node_payload("Webhook Flow Node", graph, None),
            format="json",
        )
        assert detach.status_code == 200, detach.json()
        assert detach.json()["webhook_trigger"] is None

        # reattach to a different trigger
        reattach = auth_client.put(
            reverse("webhooktriggernode-detail", args=[node_id]),
            self._webhook_node_payload("Webhook Flow Node", graph, trigger_b.id),
            format="json",
        )
        assert reattach.status_code == 200, reattach.json()
        assert reattach.json()["webhook_trigger"] == trigger_b.id

    def test_normal_single_type_telegram_node_create_update_detach_reattach_unaffected(
        self, auth_client, graph: Graph, default_org, mock_telegram_service
    ):
        """Regression guard: the ordinary single-type flow for
        `TelegramTriggerNode` must keep working unaffected."""
        trigger_a = WebhookTrigger.objects.create(
            path="telegram-node-flow-a", provider_type=None, org=default_org
        )
        trigger_b = WebhookTrigger.objects.create(
            path="telegram-node-flow-b", provider_type=None, org=default_org
        )

        create = auth_client.post(
            reverse("telegramtriggernode-list"),
            self._telegram_node_payload("Telegram Flow Node", graph, trigger_a.id),
            format="json",
        )
        assert create.status_code == 201, create.json()
        node_id = create.json()["id"]

        detach = auth_client.put(
            reverse("telegramtriggernode-detail", args=[node_id]),
            self._telegram_node_payload("Telegram Flow Node", graph, None),
            format="json",
        )
        assert detach.status_code == 200, detach.json()
        assert detach.json()["webhook_trigger"] is None

        reattach = auth_client.put(
            reverse("telegramtriggernode-detail", args=[node_id]),
            self._telegram_node_payload("Telegram Flow Node", graph, trigger_b.id),
            format="json",
        )
        assert reattach.status_code == 200, reattach.json()
        assert reattach.json()["webhook_trigger"] == trigger_b.id

    def test_updating_telegram_node_that_already_owns_its_trigger_not_spuriously_rejected(
        self, auth_client, graph: Graph, default_org, mock_telegram_service
    ):
        """A `TelegramTriggerNode` re-saving the SAME `webhook_trigger` it
        already legitimately owns (the only `telegram_trigger_nodes` row
        referencing that trigger IS this instance) must not be rejected as a
        conflict against itself."""
        trigger = WebhookTrigger.objects.create(
            path="telegram-self-owned", provider_type=None, org=default_org
        )
        create = auth_client.post(
            reverse("telegramtriggernode-list"),
            self._telegram_node_payload("Telegram Self Owned", graph, trigger.id),
            format="json",
        )
        assert create.status_code == 201, create.json()
        node_id = create.json()["id"]

        # re-save without changing the trigger
        resave = auth_client.put(
            reverse("telegramtriggernode-detail", args=[node_id]),
            self._telegram_node_payload("Telegram Self Owned", graph, trigger.id),
            format="json",
        )
        assert resave.status_code == 200, resave.json()
        assert resave.json()["webhook_trigger"] == trigger.id

        # change only an unrelated field, still referencing the same trigger
        rename = auth_client.put(
            reverse("telegramtriggernode-detail", args=[node_id]),
            self._telegram_node_payload("Telegram Self Owned Renamed", graph, trigger.id),
            format="json",
        )
        assert rename.status_code == 200, rename.json()
        assert TelegramTriggerNode.objects.get(id=node_id).node_name == (
            "Telegram Self Owned Renamed"
        )

