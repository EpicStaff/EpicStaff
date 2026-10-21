"""Clear every avatar that was stored on local disk.

Avatars now live in object storage, and the avatar field reads from there. The
files uploaded before the move sat in the container's local media directory,
which was not kept across rebuilds, so most of them are already gone and none of
them can be served any more. Each user just uploads their avatar again.

The local file is deleted where it still exists; a file that cannot be deleted is
logged and left behind, never failing the migration. Object storage is not
touched. Reversing restores nothing: the files are gone.
"""

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import FileSystemStorage
from django.db import migrations
from loguru import logger


def clear_local_avatars(apps, schema_editor):
    User = apps.get_model("tables", "User")
    with_avatar = User.objects.exclude(avatar__isnull=True).exclude(avatar="")
    local_media = FileSystemStorage(location=settings.MEDIA_ROOT)
    for name in with_avatar.values_list("avatar", flat=True).iterator():
        try:
            local_media.delete(name)
        except (OSError, SuspiciousFileOperation) as error:
            logger.warning("Could not delete local avatar file {}: {}", name, error)
    cleared = with_avatar.update(avatar=None)
    logger.info("Cleared {} local avatars", cleared)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0276_alter_user_avatar"),
    ]

    operations = [
        migrations.RunPython(clear_local_avatars, migrations.RunPython.noop),
    ]
