"""POST /api/run-session/test/ — test-run a flow from a webhook or Telegram trigger node."""

import json

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode, WebhookTrigger
from tables.models.graph_models import (
    PythonNode,
    TelegramTriggerNode,
    TelegramTriggerNodeField,
    WebhookTriggerNode,
)
from tables.models.session_models import Session, SessionPrincipal, SessionTrigger
from tables.services.secrets import secret_service
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec
from tests.fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

URL = reverse("run-session-test")
WEBHOOK_PAYLOAD = {"order_id": 42, "items": [{"sku": "A-1"}]}
STORED_TEST_PAYLOAD_MARKER = "stored-designer-sample"
NON_ASCII_PAYLOAD = {"text": "привіт 🙂"}
MALFORMED_BODY = {"node_type": "webhook-trigger", "payload": [1, 2]}


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="test-run-flow", org=acme)


@pytest.fixture
def webhook_node(acme, acme_graph):
    trigger = WebhookTrigger.objects.create(path="test-run-path", org=acme)
    return WebhookTriggerNode.objects.create(
        graph=acme_graph,
        node_name="Incoming order",
        webhook_trigger=trigger,
        python_code=PythonCode.objects.create(code="def main(trigger_payload, **kwargs): ..."),
        test_payload={"marker": STORED_TEST_PAYLOAD_MARKER},
    )


@pytest.fixture
def telegram_node(acme_graph, mock_telegram_service):
    node = TelegramTriggerNode.objects.create(graph=acme_graph, node_name="Bot message")
    for parent, field_name in (("message", "text"), ("message", "chat"), ("callback_query", "data")):
        TelegramTriggerNodeField.objects.create(
            telegram_trigger_node=node,
            parent=parent,
            field_name=field_name,
            variable_path=f"variables.{parent}_{field_name}",
        )
    return node


@pytest.fixture
def acme_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _body(node, node_type, payload, graph_id=None):
    return {
        "graph_id": graph_id if graph_id is not None else node.graph_id,
        "node_type": node_type,
        "node_id": node.id,
        "payload": payload,
    }


def _compact_utf8_size(payload: dict) -> int:
    return len(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def _published_session_data(redis_client_mock) -> dict:
    published_json = redis_client_mock.publish.call_args.args[1]
    return json.loads(published_json)


@pytest.mark.django_db
class TestWebhookTriggerTestRun:
    def test_starts_session_at_the_node_with_the_payload(
        self, acme_client, admin_acme, webhook_node, redis_client_mock
    ):
        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        session = Session.objects.get(pk=response.data["session_id"])
        assert session.graph_id == webhook_node.graph_id
        assert session.entrypoint == f"Incoming order #{webhook_node.id}"
        assert session.variables["trigger_payload"] == WEBHOOK_PAYLOAD

        trigger = session.trigger
        assert trigger.trigger_type == SessionTrigger.TriggerType.WEBHOOK
        assert trigger.webhook_trigger_node_id == webhook_node.id
        assert trigger.node_name == "Incoming order"
        assert trigger.extra == {
            "path": "test-run-path",
            "config_id": None,
            SessionTrigger.TEST_RUN_EXTRA_KEY: True,
        }
        assert trigger.is_test_run is True

        principal = session.principal
        assert principal.kind == SessionPrincipal.ActionKind.USER
        assert principal.user_id == admin_acme.id

    def test_user_api_key_caller_is_recorded_as_api_key_principal(
        self, acme, admin_acme, issue_api_key, webhook_node, redis_client_mock
    ):
        # The key acts as its owner; an Org Admin holds the FLOWS.UPDATE the run needs.
        raw_key, api_key = issue_api_key(user=admin_acme)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        session = Session.objects.get(pk=response.data["session_id"])
        assert session.trigger.is_test_run is True
        principal = session.principal
        assert principal.kind == SessionPrincipal.ActionKind.API_KEY_USER
        assert principal.api_key_id == api_key.id
        assert principal.user_id == admin_acme.id

    def test_published_session_data_carries_payload_but_never_the_stored_test_payload(
        self, acme_client, webhook_node, redis_client_mock
    ):
        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        published = _published_session_data(redis_client_mock)
        assert published["initial_state"]["trigger_payload"] == WEBHOOK_PAYLOAD
        trigger_node_data = published["graph"]["webhook_trigger_node_data_list"]
        assert len(trigger_node_data) == 1
        assert "test_payload" not in trigger_node_data[0]
        assert STORED_TEST_PAYLOAD_MARKER not in json.dumps(published)
        session = Session.objects.get(pk=response.data["session_id"])
        assert STORED_TEST_PAYLOAD_MARKER not in json.dumps(session.graph_schema)

    def test_node_without_selected_webhook_trigger_runs_with_null_path(
        self, acme_client, webhook_node, redis_client_mock
    ):
        webhook_node.webhook_trigger = None
        webhook_node.save()

        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", {}), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        trigger = Session.objects.get(pk=response.data["session_id"]).trigger
        assert trigger.extra["path"] is None
        assert trigger.extra[SessionTrigger.TEST_RUN_EXTRA_KEY] is True

    def test_shared_webhook_trigger_starts_only_the_tested_node(
        self, acme, acme_client, acme_graph, webhook_node, redis_client_mock
    ):
        # A real delivery to a shared path fans out to every node on it; a test
        # run must start exactly the node the designer clicked.
        other_graph = Graph.objects.create(name="other-flow-same-trigger", org=acme)
        for graph, node_name in ((acme_graph, "Sibling"), (other_graph, "Other flow")):
            WebhookTriggerNode.objects.create(
                graph=graph,
                node_name=node_name,
                webhook_trigger=webhook_node.webhook_trigger,
                python_code=PythonCode.objects.create(
                    code="def main(trigger_payload, **kwargs): ..."
                ),
            )
        sessions_before = Session.objects.count()

        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        assert Session.objects.count() - sessions_before == 1
        session = Session.objects.get(pk=response.data["session_id"])
        assert session.graph_id == acme_graph.id
        assert session.trigger.webhook_trigger_node_id == webhook_node.id


@pytest.mark.django_db
class TestTriggerTestRunThatFailsToStart:
    def test_failed_start_returns_400_and_keeps_an_error_test_run_session(
        self, acme, acme_client, acme_graph, webhook_node, redis_client_mock
    ):
        # A python node reading a secret it did not declare makes run_session
        # abort after the Session row exists.
        secret_service.create(text="sk-test-run", org=acme, name="TEST_RUN_KEY")
        PythonNode.objects.create(
            graph=acme_graph,
            node_name="Reads undeclared secret",
            python_code=PythonCode.objects.create(
                code='def main(**kwargs):\n    return get_secret("TEST_RUN_KEY")\n'
            ),
        )

        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert set(response.data) == {"status_code", "code", "message"}
        assert response.data["code"] == "undeclared_secret"
        redis_client_mock.publish.assert_not_called()

        session = Session.objects.get(graph=acme_graph)
        assert session.status == Session.SessionStatus.ERROR
        assert session.trigger.is_test_run is True
        assert session.trigger.webhook_trigger_node_id == webhook_node.id

        listed = acme_client.get(reverse("session-list"), {"is_test_run": "true"})
        assert listed.status_code == status.HTTP_200_OK, listed.content
        assert [row["id"] for row in listed.data["results"]] == [session.pk]


@pytest.fixture
def viewer_client(client_as, django_user_model, acme, role_viewer):
    viewer = django_user_model.objects.create_user(
        email="viewer-test-run@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=viewer, org=acme, role=role_viewer)
    client = client_as(viewer)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _client_with_flows_permissions(client_as, django_user_model, org, permissions, name):
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.FLOWS, permissions=int(permissions)
    )
    user = django_user_model.objects.create_user(
        email=f"{name}@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.mark.django_db
class TestTriggerTestRunAccess:
    def test_member_with_update_on_flows_can_run(
        self, client_as, acme, member_only, webhook_node, redis_client_mock
    ):
        client = client_as(member_only)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        session = Session.objects.get(pk=response.data["session_id"])
        assert session.principal.user_id == member_only.id
        assert session.trigger.is_test_run is True

    def test_custom_role_with_only_update_on_flows_can_run(
        self, client_as, django_user_model, acme, webhook_node, redis_client_mock
    ):
        client = _client_with_flows_permissions(
            client_as, django_user_model, acme, Permission.UPDATE, "flows-update-only"
        )

        response = client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content

    def test_viewer_with_only_read_on_flows_gets_403(
        self, viewer_client, webhook_node, redis_client_mock
    ):
        response = viewer_client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not Session.objects.exists()
        redis_client_mock.publish.assert_not_called()

    def test_custom_role_with_only_read_on_flows_gets_403(
        self, client_as, django_user_model, acme, webhook_node, redis_client_mock
    ):
        client = _client_with_flows_permissions(
            client_as, django_user_model, acme, Permission.READ, "flows-read-only"
        )

        response = client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not Session.objects.exists()
        redis_client_mock.publish.assert_not_called()

    def test_viewer_403_does_not_reveal_whether_the_node_exists(
        self, viewer_client, beta, webhook_node, redis_client_mock
    ):
        beta_graph = Graph.objects.create(name="beta-test-run-flow", org=beta)
        beta_node = WebhookTriggerNode.objects.create(
            graph=beta_graph,
            node_name="Beta order",
            python_code=PythonCode.objects.create(code="def main(trigger_payload, **kwargs): ..."),
        )
        missing_node_body = {
            **_body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD),
            "node_id": beta_node.id + 1000,
        }

        responses = [
            viewer_client.post(URL, body, format="json")
            for body in (
                _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD),
                _body(beta_node, "webhook-trigger", WEBHOOK_PAYLOAD),
                missing_node_body,
            )
        ]

        assert [response.status_code for response in responses] == [
            status.HTTP_403_FORBIDDEN
        ] * 3
        assert responses[1].data == responses[0].data
        assert responses[2].data == responses[0].data
        assert not Session.objects.exists()

    def test_viewer_api_key_caller_gets_403(
        self, acme, django_user_model, role_viewer, issue_api_key, webhook_node,
        redis_client_mock,
    ):
        viewer = django_user_model.objects.create_user(
            email="viewer-key-test-run@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=viewer, org=acme, role=role_viewer)
        raw_key, _ = issue_api_key(user=viewer)
        client = APIClient()
        client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not Session.objects.exists()

    def test_member_without_any_flows_permission_gets_403(
        self, client_as, django_user_model, acme, webhook_node, redis_client_mock
    ):
        no_permissions_role = Role.objects.create(
            name="no-flows-test-run", org=acme, is_built_in=False
        )
        user = django_user_model.objects.create_user(
            email="no-flows-test-run@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=user, org=acme, role=no_permissions_role)
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not Session.objects.exists()

    def test_user_outside_the_active_org_gets_403(
        self, client_as, django_user_model, acme, beta, role_org_admin, webhook_node,
        redis_client_mock,
    ):
        outsider = django_user_model.objects.create_user(
            email="beta-admin-test-run@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=outsider, org=beta, role=role_org_admin)
        client = client_as(outsider)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not Session.objects.exists()

    def test_node_in_another_org_is_404(
        self, client_as, django_user_model, beta, role_org_admin, webhook_node,
        redis_client_mock,
    ):
        beta_admin = django_user_model.objects.create_user(
            email="beta-admin-cross-org@example.com", password="StrongPass123!"
        )
        OrganizationUser.objects.create(user=beta_admin, org=beta, role=role_org_admin)
        client = client_as(beta_admin)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

        response = client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert not Session.objects.exists()

    def test_node_from_another_graph_is_404(
        self, acme, acme_client, webhook_node, redis_client_mock
    ):
        other_graph = Graph.objects.create(name="other-flow", org=acme)

        response = acme_client.post(
            URL,
            _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD, graph_id=other_graph.id),
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert not Session.objects.exists()

    def test_node_of_another_type_with_that_id_is_404(
        self, acme_client, webhook_node, redis_client_mock
    ):
        response = acme_client.post(
            URL, _body(webhook_node, "telegram-trigger", {}), format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert not Session.objects.exists()

    def test_soft_deleted_node_is_404(self, acme_client, webhook_node, redis_client_mock):
        WebhookTriggerNode.all_objects.filter(pk=webhook_node.pk).update(
            is_soft_deleted=True, soft_deleted_at=timezone.now()
        )

        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND, response.content
        assert not Session.objects.exists()

    def test_missing_org_header_is_400_org_context_required(
        self, client_as, admin_acme, webhook_node, redis_client_mock
    ):
        response = client_as(admin_acme).post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["code"] == "org_context_required"
        assert not Session.objects.exists()

    def test_missing_org_header_with_malformed_body_is_still_org_context_required(
        self, client_as, admin_acme, redis_client_mock
    ):
        response = client_as(admin_acme).post(URL, MALFORMED_BODY, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["code"] == "org_context_required"

    def test_viewer_with_malformed_body_gets_403_not_a_validation_error(
        self, viewer_client, redis_client_mock
    ):
        response = viewer_client.post(URL, MALFORMED_BODY, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not Session.objects.exists()

    def test_viewer_with_oversized_payload_gets_403_before_the_size_check(
        self, viewer_client, webhook_node, redis_client_mock, monkeypatch
    ):
        monkeypatch.setattr(
            "tables.validators.trigger_payload_validator.MAX_TRIGGER_PAYLOAD_BYTES", 16
        )

        response = viewer_client.post(
            URL,
            _body(webhook_node, "webhook-trigger", {"text": "longer than sixteen bytes"}),
            format="json",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
        assert not Session.objects.exists()

    def test_member_with_malformed_body_gets_the_400_envelope(
        self, client_as, acme, member_only, redis_client_mock
    ):
        client = client_as(member_only)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

        response = client.post(URL, MALFORMED_BODY, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert set(response.data) == {"status_code", "code", "message"}
        assert response.data["status_code"] == 400
        assert not Session.objects.exists()


@pytest.mark.django_db
class TestTriggerTestRunRequestValidation:
    @pytest.mark.parametrize("payload", [[1, 2], "text", None], ids=["list", "string", "null"])
    def test_non_object_payload_is_400(
        self, acme_client, webhook_node, redis_client_mock, payload
    ):
        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", payload), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        expected_reason = (
            "This field may not be null."
            if payload is None
            else "Test payload must be a JSON object."
        )
        assert response.data == {
            "status_code": 400,
            "code": "invalid",
            "message": f"payload: {expected_reason}",
        }
        assert not Session.objects.exists()

    def test_payload_over_the_size_cap_is_400(
        self, acme_client, webhook_node, redis_client_mock, monkeypatch
    ):
        monkeypatch.setattr(
            "tables.validators.trigger_payload_validator.MAX_TRIGGER_PAYLOAD_BYTES", 16
        )

        response = acme_client.post(
            URL,
            _body(webhook_node, "webhook-trigger", {"text": "longer than sixteen bytes"}),
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["code"] == "invalid"
        assert response.data["message"] == (
            "payload: Test payload must not exceed 16 bytes of compact JSON (got 36)."
        )
        assert not Session.objects.exists()

    def test_unknown_node_type_is_400(self, acme_client, webhook_node, redis_client_mock):
        response = acme_client.post(
            URL, _body(webhook_node, "python", WEBHOOK_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["code"] == "invalid"
        assert response.data["message"].startswith("node_type: ")
        assert "errors" not in response.data
        assert not Session.objects.exists()

    @pytest.mark.parametrize(
        "payload",
        [{"text": "a\x00b"}, {"nested": {"key\x00": 1}}, {"items": [{"deep": "\x00"}]}],
        ids=["value", "nested-key", "value-in-list"],
    )
    def test_nul_character_is_400_not_a_database_error(
        self, acme_client, webhook_node, redis_client_mock, payload
    ):
        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", payload), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["code"] == "invalid"
        assert "NUL character" in response.data["message"]
        assert not Session.objects.exists()

    def test_literal_backslash_u0000_text_is_not_mistaken_for_nul(
        self, acme_client, webhook_node, redis_client_mock
    ):
        payload = {"escaped": "\\u0000", "double_backslash": "\\\\u0000"}

        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", payload), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        session = Session.objects.get(pk=response.data["session_id"])
        assert session.variables["trigger_payload"] == payload

    def test_backslash_followed_by_nul_is_400(
        self, acme_client, webhook_node, redis_client_mock
    ):
        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", {"text": "\\\x00"}), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "NUL character" in response.data["message"]

    def test_unpaired_surrogate_is_400_not_a_server_error(
        self, acme_client, webhook_node, redis_client_mock
    ):
        raw_body = json.dumps(_body(webhook_node, "webhook-trigger", {"text": "\ud800"}))

        response = acme_client.post(URL, raw_body, content_type="application/json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert "unpaired Unicode surrogates" in response.data["message"]
        assert not Session.objects.exists()

    def test_size_cap_counts_real_utf8_bytes_not_ascii_escapes(
        self, acme_client, webhook_node, redis_client_mock, monkeypatch
    ):
        utf8_size = _compact_utf8_size(NON_ASCII_PAYLOAD)
        ascii_escaped_size = len(json.dumps(NON_ASCII_PAYLOAD, separators=(",", ":")))
        assert ascii_escaped_size > utf8_size
        monkeypatch.setattr(
            "tables.validators.trigger_payload_validator.MAX_TRIGGER_PAYLOAD_BYTES", utf8_size
        )

        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", NON_ASCII_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        session = Session.objects.get(pk=response.data["session_id"])
        assert session.variables["trigger_payload"] == NON_ASCII_PAYLOAD

    def test_non_ascii_payload_over_the_cap_by_utf8_bytes_is_400(
        self, acme_client, webhook_node, redis_client_mock, monkeypatch
    ):
        utf8_size = _compact_utf8_size(NON_ASCII_PAYLOAD)
        monkeypatch.setattr(
            "tables.validators.trigger_payload_validator.MAX_TRIGGER_PAYLOAD_BYTES",
            utf8_size - 1,
        )

        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", NON_ASCII_PAYLOAD), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert f"(got {utf8_size})" in response.data["message"]
        assert not Session.objects.exists()


@pytest.mark.django_db
class TestTelegramTriggerTestRun:
    def test_starts_session_with_telegram_payload_and_chat_id(
        self, acme_client, telegram_node, redis_client_mock
    ):
        payload = {"message": {"text": "hello", "chat": {"id": 1001}}}

        response = acme_client.post(
            URL, _body(telegram_node, "telegram-trigger", payload), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        session = Session.objects.get(pk=response.data["session_id"])
        assert session.entrypoint == f"Bot message #{telegram_node.id}"
        assert session.variables["telegram_payload"] == payload
        trigger = session.trigger
        assert trigger.trigger_type == SessionTrigger.TriggerType.TELEGRAM
        assert trigger.telegram_trigger_node_id == telegram_node.id
        assert trigger.extra == {"chat_id": 1001, SessionTrigger.TEST_RUN_EXTRA_KEY: True}
        published = _published_session_data(redis_client_mock)
        assert published["initial_state"]["telegram_payload"] == payload

    @pytest.mark.parametrize(
        "payload",
        [{}, {"message": {}}, {"message": {"text": "only text"}}],
        ids=["empty", "empty-parent", "omitted-picked-fields"],
    )
    def test_payloads_within_the_selected_fields_run(
        self, acme_client, telegram_node, redis_client_mock, payload
    ):
        response = acme_client.post(
            URL, _body(telegram_node, "telegram-trigger", payload), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        trigger = Session.objects.get(pk=response.data["session_id"]).trigger
        assert trigger.is_test_run is True

    def test_real_update_with_update_id_runs_and_keeps_update_id(
        self, acme_client, telegram_node, redis_client_mock
    ):
        payload = {"update_id": 123456789, "message": {"text": "hello", "chat": {"id": 1001}}}

        response = acme_client.post(
            URL, _body(telegram_node, "telegram-trigger", payload), format="json"
        )

        assert response.status_code == status.HTTP_201_CREATED, response.content
        session = Session.objects.get(pk=response.data["session_id"])
        assert session.variables["telegram_payload"] == payload
        published = _published_session_data(redis_client_mock)
        assert published["initial_state"]["telegram_payload"]["update_id"] == 123456789

    def test_payload_outside_the_selected_fields_is_400_and_creates_no_session(
        self, acme_client, telegram_node, redis_client_mock
    ):
        payload = {"message": {"photo": []}, "edited_message": {"text": "x"}}

        response = acme_client.post(
            URL, _body(telegram_node, "telegram-trigger", payload), format="json"
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
        assert response.data["code"] == "test_run_payload_invalid"
        assert response.data["errors"] == [
            "'message.photo': field not selected on this node",
            "'edited_message': not a field parent selected on this node",
        ]
        assert not Session.objects.exists()
        redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
class TestIsTestRunInSessionResponses:
    @pytest.fixture
    def session_ids_test_run_and_manual(self, acme_client, webhook_node, redis_client_mock):
        response = acme_client.post(
            URL, _body(webhook_node, "webhook-trigger", WEBHOOK_PAYLOAD), format="json"
        )
        assert response.status_code == status.HTTP_201_CREATED, response.content
        manual_session = SessionManagerService().create_session(
            webhook_node.graph_id, trigger=TriggerSpec.manual()
        )
        return response.data["session_id"], manual_session.pk

    @pytest.mark.parametrize("detailed", ["true", "false"])
    def test_list_reports_is_test_run(self, acme_client, session_ids_test_run_and_manual, detailed):
        test_run_session_id, manual_session_id = session_ids_test_run_and_manual

        response = acme_client.get(reverse("session-list"), {"detailed": detailed})

        assert response.status_code == status.HTTP_200_OK, response.content
        is_test_run_by_session = {
            row["id"]: row["trigger"]["is_test_run"] for row in response.data["results"]
        }
        assert is_test_run_by_session == {test_run_session_id: True, manual_session_id: False}
        assert all("extra" not in row["trigger"] for row in response.data["results"])

    def test_detail_reports_is_test_run(self, acme_client, session_ids_test_run_and_manual):
        test_run_session_id, manual_session_id = session_ids_test_run_and_manual

        test_run_response = acme_client.get(reverse("session-detail", args=[test_run_session_id]))
        manual_response = acme_client.get(reverse("session-detail", args=[manual_session_id]))

        assert test_run_response.status_code == status.HTTP_200_OK, test_run_response.content
        assert test_run_response.data["trigger"]["is_test_run"] is True
        assert manual_response.data["trigger"]["is_test_run"] is False
