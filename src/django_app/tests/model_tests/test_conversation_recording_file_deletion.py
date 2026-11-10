"""A voice recording's audio file lives exactly as long as its row.

Deleting the row, directly or through its chat, removes the file once the deletion
commits; a deletion that rolls back keeps the file its row still points to, and the
files of other recordings are never touched.
"""

from pathlib import Path

import pytest
from django.db import transaction

from agents.models import AgentDefinition
from rbac.models import Organization
from tables.models.realtime_models import (
    ConversationRecording,
    RealtimeAgentChat,
    RealtimeAgentDefinition,
)
from tests.voice_recording_files import wav_upload

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path_factory):
    # tests/conftest.py makes tmp_path one directory shared by every test.
    media_root = tmp_path_factory.mktemp("media")
    settings.MEDIA_ROOT = str(media_root)
    return media_root


def _chat(connection_key):
    organization = Organization.objects.create(name=f"org-{connection_key}")
    agent_definition = AgentDefinition.objects.create(org=organization, name="voice-agent")
    rt_definition = RealtimeAgentDefinition.objects.create(agent_definition=agent_definition)
    return RealtimeAgentChat.objects.create(
        rt_agent_definition=rt_definition, connection_key=connection_key
    )


def _recording(chat):
    return ConversationRecording.objects.create(
        rt_agent_chat=chat,
        recording_type=ConversationRecording.RecordingType.INBOUND,
        file=wav_upload(),
    )


def _file_path(media_root, recording) -> Path:
    path = media_root / recording.file.name
    assert path.is_file(), "the fixture failed to write the recording file"
    return path


def _delete_recording(recording):
    recording.delete()


def _delete_recordings_by_queryset(recording):
    ConversationRecording.objects.filter(pk=recording.pk).delete()


def _delete_chat(recording):
    recording.rt_agent_chat.delete()


@pytest.mark.parametrize(
    "delete",
    [_delete_recording, _delete_recordings_by_queryset, _delete_chat],
    ids=["recording", "recording-queryset", "chat-cascade"],
)
def test_deleting_a_recording_removes_its_file_after_commit(
    media_root, django_capture_on_commit_callbacks, delete
):
    deleted = _recording(_chat("deleted"))
    kept = _recording(_chat("kept"))
    deleted_path, kept_path = _file_path(media_root, deleted), _file_path(media_root, kept)
    # delete() clears the instance's pk.
    deleted_pk = deleted.pk

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        delete(deleted)
        assert deleted_path.is_file(), "the file must outlive the uncommitted deletion"
    for callback in callbacks:
        callback()

    assert not ConversationRecording.objects.filter(pk=deleted_pk).exists()
    assert not deleted_path.exists()
    assert kept_path.is_file()


def test_a_rolled_back_deletion_keeps_the_file(media_root, django_capture_on_commit_callbacks):
    recording = _recording(_chat("rolled-back"))
    path = _file_path(media_root, recording)
    # delete() clears the instance's pk, even when its transaction then rolls back.
    recording_pk = recording.pk

    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError), transaction.atomic():
            recording.delete()
            raise RuntimeError("the deletion fails after the row is gone")

    assert ConversationRecording.objects.filter(pk=recording_pk).exists()
    assert path.is_file()
