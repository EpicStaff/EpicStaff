import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models import Organization
from tables.models.realtime_models import (
    ConversationRecording,
    OpenAIRealtimeConfig,
    RealtimeAgent,
    RealtimeAgentChat,
)
from tests.fixtures import *  # noqa: F401,F403
from tests.voice_recording_files import wav_upload


def _make_realtime_agent(agent, org):
    """Mirrors realtime_agent_chat_end_test.py's helper."""
    config = OpenAIRealtimeConfig.objects.create(custom_name="test-openai", org=org)
    return RealtimeAgent.objects.create(agent=agent, openai_config=config)


def _make_chat(rt_agent, connection_key="conn-under-test"):
    return RealtimeAgentChat.objects.create(
        rt_agent=rt_agent, connection_key=connection_key
    )


@pytest.mark.django_db
class TestConversationRecordingCreateSystemKey:
    """`create` (POST /conversation-recordings/) serves only the realtime
    service's `voice_call_service._post_recording`, which authenticates with
    the env-seeded SYSTEM API key and never sends `X-Organization-Id`: it
    knows its chat only by the opaque `connection_key`. The SYSTEM key is the
    authorization check, mirroring `RealtimeAgentChatViewSet.end`; any other
    key gets 403, so a USER key cannot attach a recording to any chat."""

    @pytest.fixture(autouse=True)
    def media_root(self, settings, tmp_path_factory):
        # The test transaction's rollback does not remove a stored recording file.
        settings.MEDIA_ROOT = str(tmp_path_factory.mktemp("media"))

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
                "file": wav_upload(),
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
                "file": wav_upload(),
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert ConversationRecording.objects.filter(rt_agent_chat=chat).exists()

    @pytest.mark.parametrize("chat_in_own_org", [True, False], ids=["own-org", "other-org"])
    def test_user_scoped_api_key_is_refused(
        self, wikipedia_agent, default_org, api_client, user_api_key, chat_in_own_org
    ):
        """A self-issued key_type=USER API key, which any org member can
        create, cannot create a recording even for its own org's chat."""
        chat_org = (
            default_org
            if chat_in_own_org
            else Organization.objects.create(name="Some Other Org")
        )
        rt_agent = _make_realtime_agent(wikipedia_agent, chat_org)
        chat = _make_chat(rt_agent, connection_key="conn-user-key")
        raw_key, _key = user_api_key
        api_client.credentials(
            HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(default_org.id)
        )

        response = api_client.post(
            self._url(),
            data={
                "connection_key": chat.connection_key,
                "recording_type": ConversationRecording.RecordingType.INBOUND,
                "file": wav_upload(),
            },
            format="multipart",
        )

        assert response.status_code == status.HTTP_403_FORBIDDEN, response.json()
        assert not ConversationRecording.objects.filter(rt_agent_chat=chat).exists()
