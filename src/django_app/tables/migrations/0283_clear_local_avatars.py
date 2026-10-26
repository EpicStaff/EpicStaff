"""Clear every avatar that was stored on local disk.

Avatars now live in object storage, where none of the old files exist, so each old
avatar would render as a broken image; users upload theirs again. The local file is
deleted where it still exists, never failing the migration. Reversing restores nothing.
"""

from django.conf import settings
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
        except OSError as error:
            logger.warning("Could not delete local avatar file {}: {}", name, error)
    with_avatar.update(avatar=None)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0282_alter_user_avatar"),
    ]

    operations = [
        migrations.RunPython(clear_local_avatars, migrations.RunPython.noop),
    ]
