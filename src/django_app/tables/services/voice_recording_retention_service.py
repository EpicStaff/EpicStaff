from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from tables.models.realtime_models import ConversationRecording

# Recordings loaded and deleted per transaction, so a large backlog is never loaded at once.
_DELETE_CHUNK_SIZE = 500


class VoiceRecordingRetentionService:
    @staticmethod
    def delete_expired(now: datetime | None = None) -> int:
        """Delete every voice-call recording older than VOICE_RECORDING_RETENTION_DAYS.

        Instance-wide on purpose: the retention is one setting for every organization.
        Only the recording rows go; their RealtimeAgentChat stays. Each chunk is deleted
        through the ORM in its own transaction, so every row sends post_delete and its
        audio file is removed when that chunk commits, while at most _DELETE_CHUNK_SIZE
        rows are loaded at once.

        Returns:
            Recordings deleted.
        """
        cutoff = (now or timezone.now()) - timedelta(days=settings.VOICE_RECORDING_RETENTION_DAYS)
        expired = ConversationRecording.objects.filter(created_at__lt=cutoff)
        deleted = 0
        while chunk := list(
            expired.order_by("pk").values_list("pk", flat=True)[:_DELETE_CHUNK_SIZE]
        ):
            with transaction.atomic():
                count, _per_model = ConversationRecording.objects.filter(pk__in=chunk).delete()
            deleted += count
        return deleted
