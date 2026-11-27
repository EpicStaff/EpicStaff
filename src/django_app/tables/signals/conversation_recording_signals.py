from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from loguru import logger


@receiver(post_delete, sender="tables.ConversationRecording")
def delete_recording_file(sender, instance, **kwargs):
    """Remove a deleted recording's audio file once the deletion commits.

    Runs for a recording deleted directly and for one removed by a cascade (its chat's,
    or an organization deletion's). After commit, so a rolled-back deletion keeps the file
    its row still points to. A file already gone is no error: FileSystemStorage.delete
    ignores a missing file.
    """
    if not instance.file:
        return
    storage = instance.file.storage
    name = instance.file.name

    def delete_file() -> None:
        # Logged, not raised: the deletion has committed, and the name tells an operator
        # which file was left behind.
        try:
            storage.delete(name)
        except Exception as error:
            logger.error(
                "Voice recording file was not deleted name={name} error={error}",
                name=name,
                error=error,
            )

    transaction.on_commit(delete_file)
