import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.rbac_models import Organization
from tables.models.realtime_models import (
    ConversationRecording,
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
)
from tests.fixtures import *  # noqa: F401,F403


def _make_realtime_agent(agent, org):
    """Mirrors realtime_agent_chat_end_test.py's helper."""
    config = OpenAIRealtimeConfig.objects.create(custom_name="test-openai", org=org)
    return RealtimeAgent.objects.create(agent=agent, openai_config=config)


def _make_chat(rt_agent, connection_key="conn-under-test"):
    return RealtimeAgentChat.objects.create(
        rt_agent=rt_agent, connection_key=connection_key
    )


def _fake_audio_file():
    from django.core.files.uploadedfile import SimpleUploadedFile

    return SimpleUploadedFile("clip.wav", b"fake-audio-bytes", content_type="audio/wav")


@pytest.mark.django_db
class TestConversationRecordingCreateSystemKey:
    """Bug fix: `create` (POST /conversation-recordings/) is the only caller
    for the realtime/voice_app services' `voice_call_service._post_recording`,
    which authenticates with the env-seeded SYSTEM API key and never sends
    `X-Organization-Id` (it has no logged-in user/org context — it only knows
    the opaque `connection_key`). Before the fix, `perform_create`
    unconditionally called `_assert_parent_in_active_org`, which requires
    `OrgContextService.resolve` to find an org context; with none available
    the call always raised `OrgContextRequiredError` (400), silently swallowed
    by the caller's fire-and-forget POST (only a `logger.warning`) — so the
    `ConversationRecording` table stayed permanently empty in production.

    Fixed by skipping the org assertion only for verified `key_type=SYSTEM`
    API-key callers, mirroring `RealtimeAgentChatViewSet.end`'s trust model;
    a self-issued USER key still goes through the normal parent-org check."""

    def _url(self):
        return reverse("conversationrecording-list")

    def test_succeeds_with_system_api_key_for_any_org_no_org_header(
        self, wikipedia_agent, default_org, api_client, env_api_key
    ):
        rt_agent = _make_realtime_agent(wikipedia_agent, default_org)
        chat = _make_chat(rt_agent)
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(),
            data={
                "connection_key": chat.connection_key,
                "recording_type": ConversationRecording.RecordingType.INBOUND,
                "duration_seconds": "5.25",
                "file": _fake_audio_file(),
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert ConversationRecording.objects.filter(rt_agent_chat=chat).exists()

    def test_system_api_key_can_save_recording_for_other_orgs_chat(
        self, wikipedia_agent, default_org, api_client, env_api_key
    ):
        """Same accepted cross-org-by-design trust model as
        RealtimeAgentChatViewSet.end / RealtimeChannelViewSet.lookup_by_token:
        the SYSTEM key is the only authorization check for this caller."""
        other_org = Organization.objects.create(name="Some Other Org")
        rt_agent = _make_realtime_agent(wikipedia_agent, other_org)
        chat = _make_chat(rt_agent, connection_key="conn-other-org")
        raw_key, _key = env_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(),
            data={
                "connection_key": chat.connection_key,
                "recording_type": ConversationRecording.RecordingType.OUTBOUND,
                "file": _fake_audio_file(),
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert ConversationRecording.objects.filter(rt_agent_chat=chat).exists()

    def test_user_scoped_api_key_from_another_org_still_rejected(
        self, wikipedia_agent, default_org, api_client, user_api_key
    ):
        """A self-issued key_type=USER API key must not get the SYSTEM-key
        bypass — it still needs a valid org context to create a recording
        under another org's chat."""
        other_org = Organization.objects.create(name="Some Other Org")
        rt_agent = _make_realtime_agent(wikipedia_agent, other_org)
        chat = _make_chat(rt_agent, connection_key="conn-user-key-other-org")
        raw_key, _key = user_api_key
        api_client.credentials(HTTP_X_API_KEY=raw_key)

        response = api_client.post(
            self._url(),
            data={
                "connection_key": chat.connection_key,
                "recording_type": ConversationRecording.RecordingType.INBOUND,
                "file": _fake_audio_file(),
            },
            format="multipart",
        )

        assert response.status_code in (
            status.HTTP_400_BAD_REQUEST,
            status.HTTP_403_FORBIDDEN,
            status.HTTP_404_NOT_FOUND,
        ), response.json()
        assert not ConversationRecording.objects.filter(rt_agent_chat=chat).exists()
