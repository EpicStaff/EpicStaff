"""Updating a webhook trigger that trigger nodes are attached to needs flows:USE.

A trigger's auth, path and tunnel decide whether its webhook and Telegram trigger
nodes receive deliveries, so changing them on a trigger with live attached nodes is
a trigger-node write: 403 `trigger_nodes_require_use_permission` without USE,
nothing written or republished. A trigger with no attached node (a soft-deleted one
doesn't count) stays writable with the webhooks permission alone. Another org's
trigger is a 404.
"""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode, WebhookTrigger
from tables.models.graph_models import TelegramTriggerNode, WebhookTriggerNode
from tables.models.webhook_models import WebhookTriggerAuth, WebhookTriggerAuthKind
from tables.services.secrets import secret_service
from tables.services.webhook_trigger_service import WebhookTriggerService
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

DENIED_CODE = "trigger_nodes_require_use_permission"
WEBHOOK_SECRET = "epicstaff-api-key-value-0123456789-long"
TELEGRAM_SECRET = "telegram_secret_token_0123456789"


def _grants(flows_permissions):
    """`flows_permissions` on flows; full control of webhooks and secrets."""
    return {
        ResourceType.FLOWS: flows_permissions,
        ResourceType.WEBHOOKS: Permission.CREATE
        | Permission.READ
        | Permission.UPDATE
        | Permission.DELETE,
        ResourceType.SECRETS: Permission.CREATE | Permission.READ | Permission.USE,
    }


@pytest.fixture
def editor_client(custom_role_client, acme):
    """Can read flows and fully manage webhooks and secrets, but cannot run flows."""
    return custom_role_client(acme, _grants(Permission.READ), "wt-no-use")


@pytest.fixture
def runner_client(custom_role_client, acme):
    return custom_role_client(acme, _grants(Permission.READ | Permission.USE), "wt-use")


@pytest.fixture
def superadmin_client(org_client_as, superadmin, acme):
    return org_client_as(superadmin, acme)


@pytest.fixture
def republished(mocker, mock_telegram_service):
    """The tunnel config republish and the Telegram setWebhook registration, mocked."""
    return {
        "tunnels": mocker.patch.object(WebhookTriggerService, "register_webhooks", return_value=True),
        "telegram": mock_telegram_service,
    }


def _trigger(org, path):
    return WebhookTrigger.objects.create(path=path, org=org, provider_type=None)


def _attach_webhook_node(trigger):
    graph = Graph.objects.create(name=f"flow-{trigger.path}", org=trigger.org)
    return WebhookTriggerNode.objects.create(
        graph=graph,
        node_name="Incoming",
        webhook_trigger=trigger,
        python_code=PythonCode.objects.create(code="def main(**kwargs): ..."),
    )


def _attach_telegram_node(trigger):
    graph = Graph.objects.create(name=f"flow-{trigger.path}", org=trigger.org)
    return TelegramTriggerNode.objects.create(
        graph=graph, node_name="Bot", webhook_trigger=trigger
    )


def _detail(trigger):
    return reverse("webhooktrigger-detail", args=[trigger.id])


def _state(trigger):
    trigger.refresh_from_db()
    auth = WebhookTriggerAuth.objects.filter(trigger=trigger).first()
    return (
        trigger.path,
        trigger.provider_type,
        None if auth is None else (auth.kind, auth.secret_id),
    )


ATTACHMENTS = [
    pytest.param(_attach_webhook_node, WEBHOOK_SECRET, "webhook", id="webhook-node"),
    pytest.param(_attach_telegram_node, TELEGRAM_SECRET, "telegram", id="telegram-node"),
]


@pytest.mark.django_db
class TestAttachedTrigger:
    @pytest.mark.parametrize(("attach", "secret_text", "auth_kind"), ATTACHMENTS)
    def test_patch_without_use_is_403_and_changes_nothing(
        self,
        editor_client,
        acme,
        republished,
        django_capture_on_commit_callbacks,
        attach,
        secret_text,
        auth_kind,
    ):
        trigger = _trigger(acme, f"attached-{auth_kind}")
        attach(trigger)
        secret = secret_service.create(text=secret_text, org=acme, name=f"rekey-{auth_kind}")
        before = _state(trigger)
        # Attaching a Telegram node resyncs tunnels and Telegram itself; only what the
        # request does counts.
        republished["tunnels"].reset_mock()
        republished["telegram"].reset_mock()

        with django_capture_on_commit_callbacks(execute=True):
            response = editor_client.patch(
                _detail(trigger),
                {"auth_secret_id": secret.id, "auth_kind": auth_kind},
                format="json",
            )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data["code"] == DENIED_CODE
        assert _state(trigger) == before
        republished["tunnels"].assert_not_called()
        republished["telegram"].assert_not_called()

    @pytest.mark.parametrize(("attach", "secret_text", "auth_kind"), ATTACHMENTS)
    def test_put_without_use_is_403_and_changes_nothing(
        self, editor_client, acme, republished, attach, secret_text, auth_kind
    ):
        trigger = _trigger(acme, f"put-attached-{auth_kind}")
        attach(trigger)
        before = _state(trigger)

        response = editor_client.put(
            _detail(trigger), {"path": "renamed-path", "provider_type": None}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data["code"] == DENIED_CODE
        assert _state(trigger) == before

    def test_body_errors_still_get_the_same_403(self, editor_client, acme, republished):
        trigger = _trigger(acme, "attached-bad-body")
        _attach_webhook_node(trigger)

        response = editor_client.patch(
            _detail(trigger), {"provider_type": "not-a-provider"}, format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert response.data["code"] == DENIED_CODE

    def test_with_use_the_trigger_is_rekeyed(
        self, runner_client, acme, republished, django_capture_on_commit_callbacks
    ):
        trigger = _trigger(acme, "attached-use")
        _attach_webhook_node(trigger)
        secret = secret_service.create(text=WEBHOOK_SECRET, org=acme, name="rekey-use")

        with django_capture_on_commit_callbacks(execute=True):
            response = runner_client.patch(
                _detail(trigger), {"auth_secret_id": secret.id}, format="json"
            )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _state(trigger)[2] == (WebhookTriggerAuthKind.WEBHOOK, secret.id)

    @pytest.mark.parametrize(
        ("flows_permissions", "expected_status", "expected_path"),
        [
            pytest.param(
                Permission.READ, status.HTTP_403_FORBIDDEN, "attached-key", id="without-use"
            ),
            pytest.param(
                Permission.READ | Permission.USE, status.HTTP_200_OK, "key-renamed", id="with-use"
            ),
        ],
    )
    def test_a_user_api_key_acts_with_its_owners_role(
        self, custom_role_client, acme, republished, flows_permissions, expected_status,
        expected_path,
    ):
        client = custom_role_client(
            acme, _grants(flows_permissions), "wt-key", via_api_key=True
        )
        trigger = _trigger(acme, "attached-key")
        _attach_webhook_node(trigger)

        response = client.patch(_detail(trigger), {"path": "key-renamed"}, format="json")

        assert response.status_code == expected_status, response.content
        if expected_status == status.HTTP_403_FORBIDDEN:
            assert response.data["code"] == DENIED_CODE
        assert _state(trigger)[0] == expected_path

    def test_superadmin_needs_no_role(self, superadmin_client, acme, republished):
        trigger = _trigger(acme, "attached-superadmin")
        _attach_webhook_node(trigger)

        response = superadmin_client.patch(
            _detail(trigger), {"path": "superadmin-renamed"}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _state(trigger)[0] == "superadmin-renamed"


@pytest.mark.django_db
class TestUnattachedTrigger:
    def test_patch_needs_only_the_webhooks_permission(self, editor_client, acme, republished):
        trigger = _trigger(acme, "unattached")
        secret = secret_service.create(text=WEBHOOK_SECRET, org=acme, name="rekey-free")

        response = editor_client.patch(
            _detail(trigger), {"auth_secret_id": secret.id}, format="json"
        )

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _state(trigger)[2] == (WebhookTriggerAuthKind.WEBHOOK, secret.id)

    def test_a_soft_deleted_node_does_not_count(self, editor_client, acme, republished):
        trigger = _trigger(acme, "soft-deleted-node")
        node = _attach_webhook_node(trigger)
        WebhookTriggerNode.all_objects.filter(pk=node.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )

        response = editor_client.patch(_detail(trigger), {"path": "freed-path"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert _state(trigger)[0] == "freed-path"

    def test_create_and_delete_need_no_use(self, editor_client, acme, republished):
        created = editor_client.post(
            reverse("webhooktrigger-list"),
            {"path": "fresh-trigger", "provider_type": None},
            format="json",
        )
        assert created.status_code == status.HTTP_201_CREATED, created.content

        attached = _trigger(acme, "delete-attached")
        _attach_webhook_node(attached)
        deleted = editor_client.delete(_detail(attached))
        assert deleted.status_code == status.HTTP_204_NO_CONTENT, deleted.content


@pytest.mark.django_db
@pytest.mark.parametrize("client_fixture", ["editor_client", "runner_client", "superadmin_client"])
def test_another_orgs_trigger_is_404_for_everyone(request, beta, republished, client_fixture):
    trigger = _trigger(beta, "beta-attached")
    _attach_webhook_node(trigger)

    response = request.getfixturevalue(client_fixture).patch(
        _detail(trigger), {"path": "stolen"}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
    assert _state(trigger)[0] == "beta-attached"
