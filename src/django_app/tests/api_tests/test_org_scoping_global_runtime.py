"""Plan 5 — global singletons (superadmin write-lockdown), VoiceSettings/Twilio
(superadmin), and reachable runtime models (RealtimeAgentChat)."""

import pytest
from rest_framework.test import APIClient

from tables.models import Agent
from tables.models.realtime_models import RealtimeAgent, RealtimeAgentChat
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
