"""The local-avatar cleanup migration clears every avatar left on local disk and
never touches object storage.

Each user's avatar column is nulled. The local file is deleted where it still
exists; a file that is already gone, cannot be deleted, or whose name points
outside the media directory never fails the migration. Objects in the avatar
storage -- the bucket -- are left alone even when they share the column's name.

The migration's function is called directly with the live app registry: it only
reads fields that exist before and after it, so this pins what it does, not its
place in the migration graph (makemigrations --check covers that).
"""

from importlib import import_module

import pytest
from django.apps import apps
from django.core.files.base import ContentFile

from tables.models.user import User
from tests.avatar_helpers import avatar_storage, point_avatar_at

migration = import_module("tables.migrations.0277_clear_local_avatars")


@pytest.fixture
def media_root(settings, tmp_path_factory):
    # tests/conftest.py replaces `tmp_path` with one directory shared by every test.
    root = tmp_path_factory.mktemp("media")
    settings.MEDIA_ROOT = str(root)
    return root


@pytest.fixture
def make_user(db, django_user_model):
    def _make(email):
        return django_user_model.objects.create_user(email=email, password="StrongPass123!")

    return _make


def _local_file(media_root, name, content=b"old-avatar"):
    path = media_root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _run_migration():
    migration.clear_local_avatars(apps, None)


def _avatar_column(user):
    return User.objects.values_list("avatar", flat=True).get(pk=user.pk)


@pytest.mark.django_db
def test_local_files_are_deleted_and_every_avatar_is_cleared(media_root, make_user):
    with_file = make_user("local-file@example.com")
    file_gone = make_user("file-gone@example.com")
    local_path = _local_file(media_root, f"avatars/{with_file.id}/old.png")
    point_avatar_at(with_file, f"avatars/{with_file.id}/old.png")
    point_avatar_at(file_gone, f"avatars/{file_gone.id}/vanished.png")

    _run_migration()

    assert not local_path.exists()
    assert _avatar_column(with_file) is None
    assert _avatar_column(file_gone) is None


@pytest.mark.django_db
def test_users_without_an_avatar_and_unreferenced_files_are_left_alone(media_root, make_user):
    blank_avatar = make_user("blank-avatar@example.com")
    point_avatar_at(blank_avatar, "")
    null_avatar = make_user("null-avatar@example.com")
    User.objects.filter(pk=null_avatar.pk).update(avatar=None)
    unreferenced = _local_file(media_root, "recordings/keep.wav")

    _run_migration()

    assert _avatar_column(blank_avatar) == ""
    assert _avatar_column(null_avatar) is None
    assert unreferenced.exists()


@pytest.mark.django_db
def test_object_storage_is_not_touched(media_root, make_user):
    user = make_user("bucket-avatar@example.com")
    name = f"avatars/{user.id}/in-bucket.png"
    avatar_storage().save(name, ContentFile(b"bucket-bytes"))
    point_avatar_at(user, name)

    _run_migration()

    assert avatar_storage().exists(name)
    assert _avatar_column(user) is None


@pytest.mark.django_db
def test_a_file_that_cannot_be_deleted_does_not_fail_the_migration(media_root, make_user):
    undeletable = make_user("undeletable@example.com")
    outside = make_user("outside@example.com")
    after_them = make_user("after-them@example.com")
    # A non-empty directory under the avatar's name: deleting it raises OSError.
    blocker = _local_file(media_root, f"avatars/{undeletable.id}/stuck.png/inner")
    point_avatar_at(undeletable, f"avatars/{undeletable.id}/stuck.png")
    # A name escaping the media root raises SuspiciousFileOperation, and must not delete there.
    escaped = _local_file(media_root.parent, "escaped.png")
    point_avatar_at(outside, f"../{escaped.name}")
    after_path = _local_file(media_root, f"avatars/{after_them.id}/fine.png")
    point_avatar_at(after_them, f"avatars/{after_them.id}/fine.png")

    _run_migration()

    assert blocker.exists()
    assert escaped.exists()
    assert not after_path.exists()
    assert [_avatar_column(user) for user in (undeletable, outside, after_them)] == [None, None, None]
