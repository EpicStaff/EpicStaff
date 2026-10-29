"""RBAC regression tests for VOICE chat-recording permissions.

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

from agents.models import AgentDefinition
from rbac.models import Organization, OrganizationUser, Role
from rbac.models.enums import BuiltInRole
from tables.models.realtime_models import (
    ConversationRecording,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
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
def voice_agent_definition(db, voice_org):
    agent_definition = AgentDefinition.objects.create(
        org=voice_org, name="voice-rbac-agent"
    )
    return RealtimeAgentDefinition.objects.create(agent_definition=agent_definition)


@pytest.fixture
def voice_chat(db, voice_agent_definition):
    return RealtimeAgentChat.objects.create(
        rt_agent_definition=voice_agent_definition, connection_key="voice-rbac-conn"
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


# ---- The matrix: everyone in the org reads VOICE, only Org Admin deletes ----


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("resource", "model", "url"),
    [("voice_chat", RealtimeAgentChat, _chat_url), ("voice_recording", ConversationRecording, _recording_url)],
    ids=["chat", "recording"],
)
@pytest.mark.parametrize(
    ("caller", "can_delete"),
    [("viewer_user", False), ("member_user", False), ("org_admin_user", True)],
    ids=["viewer", "member", "org-admin"],
)
def test_voice_history_is_readable_by_members_but_deletable_only_by_org_admins(
    request, client_for, voice_org, resource, model, url, caller, can_delete
):
    target = request.getfixturevalue(resource)
    client = client_for(request.getfixturevalue(caller), voice_org)

    assert client.get(url()).status_code == status.HTTP_200_OK
    assert client.get(url(target.id)).status_code == status.HTTP_200_OK
    response = client.delete(url(target.id))

    assert response.status_code == (status.HTTP_204_NO_CONTENT if can_delete else status.HTTP_403_FORBIDDEN)
    assert model.objects.filter(id=target.id).exists() is not can_delete


@pytest.mark.django_db
@pytest.mark.parametrize("caller", ["viewer_user", "member_user"])
def test_members_cannot_create_or_change_recordings(request, client_for, voice_org, voice_chat, voice_recording, caller):
    client = client_for(request.getfixturevalue(caller), voice_org)

    created = client.post(
        _recording_url(),
        data={
            "rt_agent_chat": voice_chat.id,
            "recording_type": ConversationRecording.RecordingType.INBOUND,
            "file": SimpleUploadedFile("clip2.wav", b"more-fake-audio"),
        },
        format="multipart",
    )
    updated = client.patch(
        _recording_url(voice_recording.id),
        data={"recording_type": ConversationRecording.RecordingType.OUTBOUND},
        format="json",
    )

    assert (created.status_code, updated.status_code) == (status.HTTP_403_FORBIDDEN, status.HTTP_403_FORBIDDEN)
    voice_recording.refresh_from_db()
    assert voice_recording.recording_type == ConversationRecording.RecordingType.INBOUND
    assert ConversationRecording.objects.count() == 1
