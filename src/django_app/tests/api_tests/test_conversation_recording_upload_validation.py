"""Every caller that uploads a voice-call recording gets the same file checks.

realtime uploads with the SYSTEM key and an organization admin can upload through the
API; both may store only a WAV file of at most MAX_RECORDING_BYTES, header included, and
only for a chat. Anything else is refused with a 400, and neither a row nor a file is stored.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
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
from tests.voice_recording_files import WAV_HEADER_BYTES, wav_upload

URL = "/api/conversation-recordings/"
LIMIT = 100


@pytest.fixture(autouse=True)
def small_limit(settings):
    settings.MAX_RECORDING_BYTES = LIMIT


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path_factory):
    # tests/conftest.py makes tmp_path one directory shared by every test.
    media_root = tmp_path_factory.mktemp("media")
    settings.MEDIA_ROOT = str(media_root)
    return media_root


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Recording Upload Org")


@pytest.fixture
def chat(organization):
    agent_definition = AgentDefinition.objects.create(org=organization, name="voice-agent")
    rt_definition = RealtimeAgentDefinition.objects.create(agent_definition=agent_definition)
    return RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_definition, connection_key="upload-conn"
    )


@pytest.fixture
def system_key_upload(env_api_key, chat):
    """realtime's upload: the SYSTEM key, no org header, the chat named by connection_key."""
    raw_key, _key = env_api_key
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)
    return client, {"connection_key": chat.connection_key}


@pytest.fixture
def org_admin_upload(django_user_model, organization, chat):
    """An organization admin's upload through the API, the chat named by id."""
    role = Role.objects.get(name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True)
    user = django_user_model.objects.create_user(
        email="recording-admin@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=organization, role=role)
    client = APIClient()
    client.force_authenticate(user=user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(organization.id))
    return client, {"rt_agent_chat": chat.id}


@pytest.fixture(params=["system_key_upload", "org_admin_upload"], ids=["system-key", "org-admin"])
def upload(request):
    client, chat_reference = request.getfixturevalue(request.param)

    def _upload(file):
        return client.post(
            URL,
            data={
                **chat_reference,
                "recording_type": ConversationRecording.RecordingType.INBOUND,
                "file": file,
            },
            format="multipart",
        )

    return _upload


def _stored_files(media_root):
    return [path for path in media_root.rglob("*") if path.is_file()]


@pytest.mark.django_db
def test_a_wav_file_of_exactly_the_limit_is_stored_whole(upload, media_root):
    file = wav_upload(b"\x01" * (LIMIT - WAV_HEADER_BYTES))
    uploaded = file.read()
    file.seek(0)

    response = upload(file)

    assert response.status_code == status.HTTP_201_CREATED, response.data
    (recording,) = ConversationRecording.objects.all()
    # The type check reads the header first; the stored file must still start at byte 0.
    assert recording.file.read() == uploaded


@pytest.mark.django_db
def test_a_wav_file_one_byte_over_the_limit_is_refused(upload, media_root):
    response = upload(wav_upload(b"\x01" * (LIMIT - WAV_HEADER_BYTES + 1)))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["message"] == f"file: A recording may be at most {LIMIT} bytes."
    assert not ConversationRecording.objects.exists()
    assert _stored_files(media_root) == []


@pytest.mark.django_db
@pytest.mark.parametrize(
    "content",
    [
        b"fake-audio-bytes",
        b"<html><script>alert(1)</script></html>",
        b"ID3\x04\x00\x00\x00\x00\x00\x00 an mp3",
        # RIFF is also the container of AVI; only RIFF/WAVE is a WAV file.
        b"RIFF\x24\x00\x00\x00AVI LIST",
        # Too short to hold a WAV header at all.
        b"RIFF",
    ],
    ids=["text", "html", "mp3", "riff-avi", "truncated-header"],
)
def test_a_file_that_is_not_wav_is_refused(upload, media_root, content):
    response = upload(SimpleUploadedFile("clip.wav", content, content_type="audio/wav"))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["message"] == "file: A recording must be a WAV file."
    assert not ConversationRecording.objects.exists()
    assert _stored_files(media_root) == []


@pytest.mark.django_db
@pytest.mark.parametrize("chat_reference", [{}, {"rt_agent_chat": ""}], ids=["no-chat", "empty-chat"])
def test_a_recording_without_a_chat_is_refused_before_its_file_is_stored(
    org_admin_upload, media_root, chat_reference
):
    """A file stored without a row is never deleted: no post_delete, no retention."""
    client, _chat_reference = org_admin_upload

    response = client.post(
        URL,
        data={
            **chat_reference,
            "recording_type": ConversationRecording.RecordingType.INBOUND,
            "file": wav_upload(),
        },
        format="multipart",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["message"] == (
        "rt_agent_chat: A recording needs its chat: rt_agent_chat or connection_key."
    )
    assert not ConversationRecording.objects.exists()
    assert _stored_files(media_root) == []
