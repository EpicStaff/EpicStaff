"""RBAC regression tests for EST-3962.

`RealtimeAgentChatViewSet` and `ConversationRecordingViewSet` both declared
`rbac_resource_type = ResourceType.VOICE` but only wired
`IsAuthenticatedOrApiKey` into `permission_classes` — a permission class that
does zero role/bitmask checking. `OrgScopedChildViewSetMixin` only filters
`get_queryset` by org; it relies on `HasOrgPermission` for the role-axis
check, which these two viewsets never added. Result: any authenticated org
member (Member or Viewer, both seeded read-only on VOICE per
`0210_seed_voice_role_permissions.py`) or any self-issued API key holder
could update/delete conversation recordings and delete realtime agent chat
history within their own org.

Fixed by adding `HasOrgPermission` to both viewsets' `permission_classes`,
matching the majority pattern used elsewhere in `model_view_sets.py`.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.models.realtime_models import (
    ConversationRecording,
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
)


# ---- roles / org / users ----


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_viewer(db):
    return Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)


@pytest.fixture
def voice_org(db):
    return Organization.objects.create(name="Voice RBAC Test Org")


def _make_user(email, org, role, django_user_model):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


@pytest.fixture
def org_admin_user(db, django_user_model, voice_org, role_org_admin):
    return _make_user("voice-admin@example.com", voice_org, role_org_admin, django_user_model)


@pytest.fixture
def member_user(db, django_user_model, voice_org, role_member):
    return _make_user("voice-member@example.com", voice_org, role_member, django_user_model)


@pytest.fixture
def viewer_user(db, django_user_model, voice_org, role_viewer):
    return _make_user("voice-viewer@example.com", voice_org, role_viewer, django_user_model)


@pytest.fixture
def client_for():
    def _make(user, org):
        client = APIClient()
        client.force_authenticate(user=user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    return _make


# ---- realtime agent / chat / recording fixtures ----


@pytest.fixture
def voice_agent(db, voice_org):
    from tables.models import Agent

    agent = Agent.objects.create(
        org=voice_org, role="voice-rbac-agent", goal="goal", backstory="backstory"
    )
    config = OpenAIRealtimeConfig.objects.create(custom_name="voice-rbac-cfg", org=voice_org)
    return RealtimeAgent.objects.create(agent=agent, openai_config=config)


@pytest.fixture
def voice_chat(db, voice_agent):
    return RealtimeAgentChat.objects.create(
        rt_agent=voice_agent, connection_key="voice-rbac-conn"
    )


@pytest.fixture
def voice_recording(db, voice_chat):
    return ConversationRecording.objects.create(
        rt_agent_chat=voice_chat,
        file=SimpleUploadedFile("clip.wav", b"fake-audio-bytes"),
        recording_type=ConversationRecording.RecordingType.INBOUND,
    )


def _chat_url(pk=None):
    return (
        reverse("realtimeagentchat-detail", args=[pk])
        if pk is not None
        else reverse("realtimeagentchat-list")
    )


def _recording_url(pk=None):
    return (
        reverse("conversationrecording-detail", args=[pk])
        if pk is not None
        else reverse("conversationrecording-list")
    )


# ---- RealtimeAgentChatViewSet: destroy ----


@pytest.mark.django_db
class TestRealtimeAgentChatRbac:
    def test_viewer_cannot_delete_chat(self, client_for, viewer_user, voice_org, voice_chat):
        response = client_for(viewer_user, voice_org).delete(_chat_url(voice_chat.id))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert RealtimeAgentChat.objects.filter(id=voice_chat.id).exists()

    def test_member_cannot_delete_chat(self, client_for, member_user, voice_org, voice_chat):
        response = client_for(member_user, voice_org).delete(_chat_url(voice_chat.id))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert RealtimeAgentChat.objects.filter(id=voice_chat.id).exists()

    def test_org_admin_can_delete_chat(self, client_for, org_admin_user, voice_org, voice_chat):
        response = client_for(org_admin_user, voice_org).delete(_chat_url(voice_chat.id))
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not RealtimeAgentChat.objects.filter(id=voice_chat.id).exists()

    def test_viewer_can_read_chat_list(self, client_for, viewer_user, voice_org, voice_chat):
        response = client_for(viewer_user, voice_org).get(_chat_url())
        assert response.status_code == status.HTTP_200_OK

    def test_member_can_read_chat_detail(self, client_for, member_user, voice_org, voice_chat):
        response = client_for(member_user, voice_org).get(_chat_url(voice_chat.id))
        assert response.status_code == status.HTTP_200_OK


# ---- ConversationRecordingViewSet: destroy / update ----


@pytest.mark.django_db
class TestConversationRecordingRbac:
    def test_viewer_cannot_delete_recording(
        self, client_for, viewer_user, voice_org, voice_recording
    ):
        response = client_for(viewer_user, voice_org).delete(_recording_url(voice_recording.id))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert ConversationRecording.objects.filter(id=voice_recording.id).exists()

    def test_member_cannot_delete_recording(
        self, client_for, member_user, voice_org, voice_recording
    ):
        response = client_for(member_user, voice_org).delete(_recording_url(voice_recording.id))
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert ConversationRecording.objects.filter(id=voice_recording.id).exists()

    def test_org_admin_can_delete_recording(
        self, client_for, org_admin_user, voice_org, voice_recording
    ):
        response = client_for(org_admin_user, voice_org).delete(
            _recording_url(voice_recording.id)
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert not ConversationRecording.objects.filter(id=voice_recording.id).exists()

    def test_viewer_cannot_update_recording(
        self, client_for, viewer_user, voice_org, voice_recording
    ):
        response = client_for(viewer_user, voice_org).patch(
            _recording_url(voice_recording.id),
            data={"recording_type": ConversationRecording.RecordingType.OUTBOUND},
            format="json",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_member_cannot_create_recording(
        self, client_for, member_user, voice_org, voice_chat
    ):
        response = client_for(member_user, voice_org).post(
            _recording_url(),
            data={
                "rt_agent_chat": voice_chat.id,
                "recording_type": ConversationRecording.RecordingType.INBOUND,
                "file": SimpleUploadedFile("clip2.wav", b"more-fake-audio"),
            },
            format="multipart",
        )
        assert response.status_code == status.HTTP_403_FORBIDDEN

    def test_viewer_can_read_recording_list(
        self, client_for, viewer_user, voice_org, voice_recording
    ):
        response = client_for(viewer_user, voice_org).get(_recording_url())
        assert response.status_code == status.HTTP_200_OK

    def test_member_can_read_recording_detail(
        self, client_for, member_user, voice_org, voice_recording
    ):
        response = client_for(member_user, voice_org).get(_recording_url(voice_recording.id))
        assert response.status_code == status.HTTP_200_OK
