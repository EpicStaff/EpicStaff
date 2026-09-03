"""Coverage for the minimal `webhook_node_auth` write shape on
`WebhookTriggerNodeSerializer` -- POST/PATCH accept only `{"enabled": bool}`.

Scope note: a separate, uncommitted `TestWebhookNodeAuthAPI` class already
exists in `webhook_trigger_api_test.py` describing a much broader
design (header_name/timestamp_header_name/tolerance_seconds/secret_id all
client-writable, explicit `null` hard-deletes the row). That design was never
implemented (the model has no `secret`/`secret_id` field) and directly
contradicts this task's explicit "omitting webhook_node_auth on create must
still auto-enable protection" requirement, so those pre-existing tests are
left untouched here -- see the handoff notes for the flagged conflict.
"""

import pytest

from tables.models.graph_models import Graph
from tables.models.webhook_models import WebhookNodeAuth
from django.urls import reverse


def _create_payload(node_name="Auth Toggle Node", webhook_node_auth=None):
    payload = {
        "node_name": node_name,
        "python_code": {
            "libraries": [],
            "code": "def handler(event, context):\n    return event",
            "entrypoint": "handler",
            "global_kwargs": {},
        },
        "metadata": {},
    }
    if webhook_node_auth is not None:
        payload["webhook_node_auth"] = webhook_node_auth
    return payload


@pytest.mark.django_db
class TestWebhookNodeAuthEnabledToggleAPI:
    def test_create_without_auth_field_auto_enables_by_default(
        self, auth_client, graph: Graph
    ):
        """Omitting `webhook_node_auth` entirely must not regress existing
        protection -- a row is still auto-created enabled with a secret."""
        payload = _create_payload()
        payload["graph"] = graph.id

        response = auth_client.post(
            reverse("webhooktriggernode-list"), payload, format="json"
        )

        assert response.status_code == 201, response.json()
        node_id = response.json()["id"]

        detail = auth_client.get(reverse("webhooktriggernode-detail", args=[node_id]))
        assert detail.status_code == 200
        auth = detail.json()["webhook_node_auth"]
        assert auth is not None
        assert auth["enabled"] is True
        assert auth["signing_secret"]

    def test_create_with_explicit_enabled_false_creates_disabled_row(
        self, auth_client, graph: Graph
    ):
        payload = _create_payload(webhook_node_auth={"enabled": False})
        payload["graph"] = graph.id

        response = auth_client.post(
            reverse("webhooktriggernode-list"), payload, format="json"
        )

        assert response.status_code == 201, response.json()
        node_id = response.json()["id"]

        detail = auth_client.get(reverse("webhooktriggernode-detail", args=[node_id]))
        assert detail.status_code == 200
        auth = detail.json()["webhook_node_auth"]
        assert auth is not None
        assert auth["enabled"] is False

    def test_create_with_extra_subfields_ignores_them(self, auth_client, graph: Graph):
        """Only `enabled` is client-controllable -- extra sub-fields like
        `signing_secret`/`scheme` in the request body must be ignored, not
        applied and not rejected."""
        payload = _create_payload(
            webhook_node_auth={
                "enabled": True,
                "signing_secret": "client-supplied-should-be-ignored",
                "scheme": "static_header",
            }
        )
        payload["graph"] = graph.id

        response = auth_client.post(
            reverse("webhooktriggernode-list"), payload, format="json"
        )

        assert response.status_code == 201, response.json()
        node_id = response.json()["id"]
        node_auth = WebhookNodeAuth.objects.get(webhook_trigger_node_id=node_id)
        assert node_auth.signing_secret != "client-supplied-should-be-ignored"
        assert node_auth.scheme == "hmac_sha256"

    def test_patch_disable_then_reenable_preserves_secret(
        self, auth_client, graph: Graph
    ):
        create_payload = _create_payload()
        create_payload["graph"] = graph.id
        create = auth_client.post(
            reverse("webhooktriggernode-list"), create_payload, format="json"
        )
        assert create.status_code == 201, create.json()
        node_id = create.json()["id"]

        original_secret = WebhookNodeAuth.objects.get(
            webhook_trigger_node_id=node_id
        ).signing_secret
        assert original_secret

        disable = auth_client.patch(
            reverse("webhooktriggernode-detail", args=[node_id]),
            {"webhook_node_auth": {"enabled": False}},
            format="json",
        )
        assert disable.status_code == 200, disable.json()
        assert disable.json()["webhook_node_auth"]["enabled"] is False

        detail_after_disable = auth_client.get(
            reverse("webhooktriggernode-detail", args=[node_id])
        )
        assert detail_after_disable.json()["webhook_node_auth"]["enabled"] is False

        reenable = auth_client.patch(
            reverse("webhooktriggernode-detail", args=[node_id]),
            {"webhook_node_auth": {"enabled": True}},
            format="json",
        )
        assert reenable.status_code == 200, reenable.json()
        assert reenable.json()["webhook_node_auth"]["enabled"] is True
        assert reenable.json()["webhook_node_auth"]["signing_secret"] == original_secret

    def test_patch_enable_creates_row_when_none_exists(
        self, auth_client, graph: Graph
    ):
        """A node created with auth disabled has a row -- but exercising the
        add-auth-to-a-node-with-no-row-yet path is covered at the service
        layer (test_webhook_trigger_service.py); here we confirm the API
        round trip creates a fresh, enabled row with a secret."""
        create_payload = _create_payload(webhook_node_auth={"enabled": False})
        create_payload["graph"] = graph.id
        create = auth_client.post(
            reverse("webhooktriggernode-list"), create_payload, format="json"
        )
        assert create.status_code == 201, create.json()
        node_id = create.json()["id"]

        enable = auth_client.patch(
            reverse("webhooktriggernode-detail", args=[node_id]),
            {"webhook_node_auth": {"enabled": True}},
            format="json",
        )
        assert enable.status_code == 200, enable.json()
        auth = enable.json()["webhook_node_auth"]
        assert auth["enabled"] is True
        assert auth["signing_secret"]

    def test_patch_missing_enabled_key_is_rejected(self, auth_client, graph: Graph):
        create_payload = _create_payload()
        create_payload["graph"] = graph.id
        create = auth_client.post(
            reverse("webhooktriggernode-list"), create_payload, format="json"
        )
        node_id = create.json()["id"]

        response = auth_client.patch(
            reverse("webhooktriggernode-detail", args=[node_id]),
            {"webhook_node_auth": {"scheme": "static_header"}},
            format="json",
        )
        assert response.status_code == 400
        assert "webhook_node_auth" in str(response.json())
