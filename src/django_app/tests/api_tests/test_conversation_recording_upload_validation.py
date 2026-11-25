"""The checks on a voice-call recording realtime uploads with the SYSTEM key.

Only a WAV file of at most MAX_VOICE_RECORDING_SIZE bytes, header included, for a known chat
is stored. Anything else is refused with a 400, and neither a row nor a file is stored.
"""

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APIClient

from agents.models import AgentDefinition
from rbac.models import Organization
from tables.models.realtime_models import (
    ConversationRecording,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
)
from tests.voice_recording_files import WAV_HEADER_BYTES, wav_upload

URL = "/api/conversation-recordings/"
LIMIT = 100

pytestmark = pytest.mark.usefixtures("media_root")


@pytest.fixture(autouse=True)
def small_limit(settings):
    settings.MAX_VOICE_RECORDING_SIZE = LIMIT


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
def system_key_client(env_api_key):
    """realtime's client: the SYSTEM key, no org header."""
    raw_key, _key = env_api_key
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key)
    return client


def _post_recording(client, chat_reference, file):
    return client.post(
        URL,
        data={
            **chat_reference,
            "recording_type": ConversationRecording.RecordingType.INBOUND,
            "file": file,
        },
        format="multipart",
    )


@pytest.fixture
def upload(system_key_client, chat):
    def _upload(file):
        return _post_recording(system_key_client, {"connection_key": chat.connection_key}, file)

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
@pytest.mark.parametrize(
    "chat_reference",
    [lambda chat: {}, lambda chat: {"connection_key": ""}, lambda chat: {"rt_agent_chat": chat.id}],
    ids=["no-key", "empty-key", "chat-id-only"],
)
def test_a_recording_without_a_connection_key_is_refused_before_its_file_is_stored(
    system_key_client, chat, media_root, chat_reference
):
    """A file stored without a row is never deleted. A chat id is not accepted in its place."""
    response = _post_recording(system_key_client, chat_reference(chat), wav_upload())

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["message"].startswith("connection_key: ")
    assert not ConversationRecording.objects.exists()
    assert _stored_files(media_root) == []


@pytest.mark.django_db
def test_a_recording_for_an_unknown_connection_key_is_refused_before_its_file_is_stored(
    system_key_client, chat, media_root
):
    response = _post_recording(
        system_key_client, {"connection_key": "no-such-connection"}, wav_upload()
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json()["message"] == "connection_key: No matching RealtimeAgentChat found"
    assert not ConversationRecording.objects.exists()
    assert _stored_files(media_root) == []


@pytest.mark.django_db
def test_a_recording_by_connection_key_is_stored_for_that_chat(upload, chat, media_root):
    file = wav_upload()

    response = upload(file)

    assert response.status_code == status.HTTP_201_CREATED, response.data
    recording = ConversationRecording.objects.get()
    assert recording.rt_agent_chat_id == chat.id
    assert recording.file_size == file.size
    assert recording.audio_format == "wav"
