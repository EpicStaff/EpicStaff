from django.db import transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver


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
    # robust: a file that cannot be removed is logged, not raised into a committed deletion.
    transaction.on_commit(lambda: storage.delete(name), robust=True)
