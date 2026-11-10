"""The daily retention deletes voice recordings older than VOICE_RECORDING_RETENTION_DAYS.

It applies to every organization at once. An expired recording goes with its audio file;
a recording exactly at the cutoff or younger stays, and so does every chat.
"""

from datetime import datetime, timedelta, timezone

import pytest

from agents.models import AgentDefinition
from rbac.models import Organization
from tables.models.realtime_models import (
    ConversationRecording,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
)
from tables.services import voice_recording_retention_service
from tables.services.voice_recording_retention_service import VoiceRecordingRetentionService
from tests.voice_recording_files import wav_upload

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 6, 1, 3, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def thirty_day_retention(settings):
    settings.VOICE_RECORDING_RETENTION_DAYS = 30


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path_factory):
    # tests/conftest.py makes tmp_path one directory shared by every test.
    media_root = tmp_path_factory.mktemp("media")
    settings.MEDIA_ROOT = str(media_root)
    return media_root


def _chat(organization_name):
    organization = Organization.objects.create(name=organization_name)
    agent_definition = AgentDefinition.objects.create(org=organization, name="voice-agent")
    rt_definition = RealtimeAgentDefinition.objects.create(agent_definition=agent_definition)
    return RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_definition, connection_key=organization_name
    )


def _recording(chat, created_at):
    recording = ConversationRecording.objects.create(
        rt_agent_chat=chat,
        recording_type=ConversationRecording.RecordingType.INBOUND,
        file=wav_upload(),
    )
    # created_at is auto_now_add, so the age is set after the insert.
    ConversationRecording.objects.filter(pk=recording.pk).update(created_at=created_at)
    return recording


def _delete_expired(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        return VoiceRecordingRetentionService.delete_expired(now=NOW)


def test_only_recordings_older_than_the_retention_are_deleted_with_their_files(
    media_root, django_capture_on_commit_callbacks
):
    first_chat, second_chat = _chat("org-one"), _chat("org-two")
    expired = [
        _recording(first_chat, NOW - timedelta(days=30, seconds=1)),
        _recording(second_chat, NOW - timedelta(days=400)),
    ]
    kept = [
        _recording(first_chat, NOW - timedelta(days=30)),
        _recording(second_chat, NOW - timedelta(days=1)),
    ]
    expired_paths = [media_root / recording.file.name for recording in expired]
    kept_paths = [media_root / recording.file.name for recording in kept]

    deleted = _delete_expired(django_capture_on_commit_callbacks)

    assert deleted == 2
    assert set(ConversationRecording.objects.values_list("pk", flat=True)) == {
        recording.pk for recording in kept
    }
    assert [path.exists() for path in expired_paths] == [False, False]
    assert [path.is_file() for path in kept_paths] == [True, True]
    assert RealtimeAgentChat.objects.filter(pk__in=[first_chat.pk, second_chat.pk]).count() == 2


def test_a_backlog_larger_than_one_chunk_is_deleted_entirely(
    monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setattr(voice_recording_retention_service, "_DELETE_CHUNK_SIZE", 2)
    chat = _chat("backlog")
    for days in range(31, 36):
        _recording(chat, NOW - timedelta(days=days))

    assert _delete_expired(django_capture_on_commit_callbacks) == 5
    assert not ConversationRecording.objects.exists()


def test_nothing_expired_deletes_nothing(django_capture_on_commit_callbacks):
    recording = _recording(_chat("fresh"), NOW - timedelta(days=29))

    assert _delete_expired(django_capture_on_commit_callbacks) == 0
    assert ConversationRecording.objects.filter(pk=recording.pk).exists()
