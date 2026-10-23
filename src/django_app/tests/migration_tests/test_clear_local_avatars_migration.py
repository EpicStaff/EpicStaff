"""The local-avatar cleanup migration clears every avatar column and deletes the local files it can.

The migration's function is called directly with the live app registry: it only
reads fields that exist before and after it (makemigrations --check covers its place
in the migration graph).
"""

from importlib import import_module

import pytest
from django.apps import apps

from tables.models.user import User

migration = import_module("tables.migrations.0277_clear_local_avatars")


@pytest.fixture
def media_root(settings, tmp_path_factory):
    # tests/conftest.py replaces `tmp_path` with one directory shared by every test.
    root = tmp_path_factory.mktemp("media")
    settings.MEDIA_ROOT = str(root)
    return root


def _user_with_avatar(django_user_model, email, avatar):
    user = django_user_model.objects.create_user(email=email, password="StrongPass123!")
    User.objects.filter(pk=user.pk).update(avatar=avatar)
    return user


def _local_file(root, name):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"old-avatar")
    return path


@pytest.mark.django_db
def test_every_avatar_is_cleared_and_its_local_file_deleted(media_root, django_user_model):
    local_path = _local_file(media_root, "avatars/1/old.png")
    users = [
        _user_with_avatar(django_user_model, "local-file@example.com", "avatars/1/old.png"),
        _user_with_avatar(django_user_model, "file-gone@example.com", "avatars/2/vanished.png"),
    ]

    migration.clear_local_avatars(apps, None)

    assert not local_path.exists()
    assert User.objects.filter(pk__in=[user.pk for user in users], avatar__isnull=False).count() == 0


@pytest.mark.django_db
def test_a_file_that_cannot_be_deleted_does_not_fail_the_migration(media_root, django_user_model):
    # A non-empty directory under the avatar's name: deleting it raises OSError.
    blocker = _local_file(media_root, "avatars/1/stuck.png/inner")
    stuck = _user_with_avatar(django_user_model, "stuck@example.com", "avatars/1/stuck.png")

    migration.clear_local_avatars(apps, None)

    assert blocker.exists()
    stuck.refresh_from_db()
    assert not stuck.avatar
