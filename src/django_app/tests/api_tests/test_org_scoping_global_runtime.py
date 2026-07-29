"""Plan 5 — global singletons (superadmin write-lockdown), VoiceSettings/Twilio
(superadmin), and reachable runtime models (RealtimeAgentChat)."""

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from tables.models import Agent
from tables.models.python_models import PythonCode, PythonCodeResult, PythonCodeTool
from tables.models.realtime_models import (
    ConversationRecording,
    RealtimeAgent,
    RealtimeAgentChat,
    RealtimeSessionItem,
)
from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole


@pytest.fixture
def org_a(db):
    return Organization.objects.create(name="Org A")


@pytest.fixture
def org_b(db):
    return Organization.objects.create(name="Org B")


def _member(django_user_model, org, email):
    role = Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


def _client(user, org):
    c = APIClient()
    c.force_authenticate(user=user)
    c.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return c


@pytest.fixture
def client_member(db, django_user_model, org_a):
    return _client(_member(django_user_model, org_a, "gm@example.com"), org_a)


@pytest.fixture
def client_super(db, django_user_model, org_a):
    root = django_user_model.objects.create_user(
        email="groot@example.com", password="StrongPass123!", is_superadmin=True
    )
    return _client(root, org_a)


# ---- default-* singletons: global read, superadmin write ----


@pytest.mark.django_db
def test_default_llm_config_read_allowed_for_member(client_member):
    assert client_member.get("/api/default-llm-config/").status_code == 200


@pytest.mark.django_db
def test_default_llm_config_write_denied_for_member(client_member):
    assert (
        client_member.put("/api/default-llm-config/", {}, format="json").status_code
        == 403
    )


@pytest.mark.django_db
def test_default_llm_config_write_permitted_for_superadmin(client_super):
    # passes the permission gate (not 403); the body/singleton may yield 200/400/404
    assert (
        client_super.put("/api/default-llm-config/", {}, format="json").status_code
        != 403
    )


@pytest.mark.django_db
def test_default_models_write_denied_for_member(client_member):
    assert (
        client_member.put("/api/default-models/", {}, format="json").status_code == 403
    )


@pytest.mark.django_db
def test_default_models_write_permitted_for_superadmin(client_super):
    assert (
        client_super.put("/api/default-models/", {}, format="json").status_code != 403
    )


# ---- VoiceSettings: superadmin only (holds the platform Twilio secret) ----


@pytest.mark.django_db
def test_voice_settings_denied_for_member(client_member):
    assert client_member.get("/api/voice-settings/").status_code == 403


@pytest.mark.django_db
def test_voice_settings_allowed_for_superadmin(client_super):
    assert client_super.get("/api/voice-settings/").status_code == 200


# ---- RealtimeAgentChat: scoped via rt_agent -> agent -> org ----


def _chat(org):
    agent = Agent.objects.create(role="r", goal="g", backstory="b", org=org)
    rt = RealtimeAgent.objects.create(agent=agent)
    return RealtimeAgentChat.objects.create(rt_agent=rt, connection_key="k")


@pytest.mark.django_db
def test_realtime_agent_chat_cross_org_404(client_member, org_b):
    chat = _chat(org_b)
    assert client_member.get(f"/api/realtime-agent-chats/{chat.id}/").status_code == 404


@pytest.mark.django_db
def test_realtime_agent_chat_own_org_visible(client_member, org_a):
    chat = _chat(org_a)
    assert client_member.get(f"/api/realtime-agent-chats/{chat.id}/").status_code == 200


# ---- ConversationRecording: scoped via rt_agent_chat -> rt_agent -> agent -> org ----


def _recording(org):
    chat = _chat(org)
    return ConversationRecording.objects.create(
        rt_agent_chat=chat,
        recording_type=ConversationRecording.RecordingType.INBOUND,
    )


@pytest.mark.django_db
def test_conversation_recording_cross_org_404(client_member, org_b):
    recording = _recording(org_b)
    assert (
        client_member.get(f"/api/conversation-recordings/{recording.id}/").status_code
        == 404
    )


@pytest.mark.django_db
def test_conversation_recording_own_org_visible(client_member, org_a):
    recording = _recording(org_a)
    assert (
        client_member.get(f"/api/conversation-recordings/{recording.id}/").status_code
        == 200
    )


@pytest.mark.django_db
def test_conversation_recording_cross_org_list_excludes_other_org(
    client_member, org_a, org_b
):
    own = _recording(org_a)
    _recording(org_b)
    resp = client_member.get("/api/conversation-recordings/")
    assert resp.status_code == 200
    returned_ids = {row["id"] for row in resp.data["results"]}
    assert returned_ids == {own.id}


def _viewer(django_user_model, org, email):
    role = Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


# ---- python-code-result: list removed, detail superadmin-only ----


@pytest.mark.django_db
def test_python_code_result_list_removed(client_super):
    # retrieve-only viewset: the router registers no collection route, so the
    # list URL no longer exists (404) even for a superadmin.
    assert client_super.get("/api/python-code-result/").status_code == 404


@pytest.mark.django_db
def test_python_code_result_detail_denied_for_member(client_member):
    PythonCodeResult.objects.create(execution_id="exec-1", stdout="secret output")
    assert client_member.get("/api/python-code-result/exec-1/").status_code == 403


@pytest.mark.django_db
def test_python_code_result_detail_allowed_for_superadmin(client_super):
    PythonCodeResult.objects.create(execution_id="exec-1", stdout="ok")
    assert client_super.get("/api/python-code-result/exec-1/").status_code == 200


# ---- realtime-session-items: superadmin-only (holds base64 audio) ----


@pytest.mark.django_db
def test_realtime_session_items_denied_for_member(client_member):
    RealtimeSessionItem.objects.create(connection_key="k", data={"audio": "b64"})
    assert client_member.get("/api/realtime-session-items/").status_code == 403


@pytest.mark.django_db
def test_realtime_session_items_allowed_for_superadmin(client_super):
    RealtimeSessionItem.objects.create(connection_key="k", data={"audio": "b64"})
    assert client_super.get("/api/realtime-session-items/").status_code == 200


# NOTE (EST-3491): the four tests that used to live here
# (`test_ngrok_config_read_denied_for_member`, `test_ngrok_config_read_allowed_for_superadmin`,
# `test_webhook_trigger_ngrok_not_settable_by_member`, `test_webhook_trigger_ngrok_settable_by_superadmin`)
# exercised a schema that no longer exists: `/api/ngrok-config/` was never a
# live route (NgrokWebhookConfigViewSet has now been formally deleted), and
# `WebhookTrigger.ngrok_webhook_config` was removed back in migration 0187
# (`webhook_trigger_remove_old_fks`) in favor of the related
# `NgrokWebhookConfig.trigger` OneToOne. Current coverage for ngrok-on-trigger
# org isolation lives in webhook_trigger_api_test.py
# (`TestWebhookTriggerOrgIsolation.test_non_superadmin_can_set_ngrok_config_on_own_org_trigger`
# and `test_auth_token_absent_from_get_response`).


# ---- run-python-code: org-visibility scope + TOOLS.UPDATE gate ----


def _code_in_org(org):
    """A PythonCode made visible to `org` via an org-owned custom tool."""
    code = PythonCode.objects.create(code="x", entrypoint="main")
    PythonCodeTool.objects.create(
        name=f"tool-{org.id}",
        description="",
        python_code=code,
        built_in=False,
        org=org,
    )
    return code


@pytest.mark.django_db
def test_run_python_code_cross_org_rejected(client_member, org_b):
    # Code visible only to org_b; an org_a member must not be able to run it.
    code = _code_in_org(org_b)
    resp = client_member.post(
        "/api/run-python-code/",
        {"python_code_id": code.id, "variables": {}},
        format="json",
    )
    assert resp.status_code == 400
    assert "does not exist" in str(resp.data)


@pytest.mark.django_db
def test_run_python_code_denied_without_tools_update(django_user_model, org_a):
    # Viewer has TOOLS read only -> blocked before any execution.
    viewer = _viewer(django_user_model, org_a, "viewer@example.com")
    client = _client(viewer, org_a)
    code = _code_in_org(org_a)
    resp = client.post(
        "/api/run-python-code/",
        {"python_code_id": code.id, "variables": {}},
        format="json",
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_run_python_code_allowed_for_member_own_org(client_member, org_a):
    code = _code_in_org(org_a)
    with patch(
        "tables.views.views.run_python_code_service.run_code",
        return_value="exec-123",
    ) as run_code:
        resp = client_member.post(
            "/api/run-python-code/",
            {"python_code_id": code.id, "variables": {}},
            format="json",
        )
    assert resp.status_code == 200, resp.data
    assert resp.data["execution_id"] == "exec-123"
    run_code.assert_called_once()
