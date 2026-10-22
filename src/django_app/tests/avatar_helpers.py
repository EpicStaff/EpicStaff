"""Image builders and stored-avatar helpers shared by the avatar tests.

Avatars are written to the in-memory `avatars` storage that tests/settings.py
installs, so a test can read back exactly what the upload service stored.
"""

import io

from django.core.files.base import ContentFile
from PIL import Image

from tables.models.user import User


def image_bytes(format_name: str, size=(64, 48), mode="RGB", color=(200, 100, 50), **save_options) -> bytes:
    buffer = io.BytesIO()
    Image.new(mode, size, color).save(buffer, format=format_name, **save_options)
    return buffer.getvalue()


def avatar_storage():
    """The storage instance the avatar field writes to."""
    return User._meta.get_field("avatar").storage


def store_avatar(user, content: bytes, version: str, extension: str = ".png") -> str:
    """Put `content` in storage under the key an upload of `version` gets, and point the user at it."""
    name = f"avatars/{user.id}/{version}{extension}"
    stored_name = avatar_storage().save(name, ContentFile(content))
    assert stored_name == name, "the avatar key is already taken in the in-memory storage"
    User.objects.filter(pk=user.pk).update(avatar=name)
    user.refresh_from_db()
    return name


def point_avatar_at(user, name: str) -> None:
    """Make the user's avatar column name `name` without storing any object."""
    User.objects.filter(pk=user.pk).update(avatar=name)
    user.refresh_from_db()


def read_stored_avatar(user) -> bytes:
    user.refresh_from_db()
    with avatar_storage().open(user.avatar.name, "rb") as stored:
        return stored.read()
