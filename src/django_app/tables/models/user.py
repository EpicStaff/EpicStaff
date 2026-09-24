"""The custom AUTH_USER_MODEL.

Lives in `tables`, not `rbac`, deliberately. `settings.AUTH_USER_MODEL` is
re-resolved every time Django builds the migration graph, so pointing it at
`rbac.User` would retroactively change the dependencies of 17 already-applied
migrations and abort `migrate` on every existing database with
InconsistentMigrationHistory. See
docs/superpowers/specs/2026-09-21-rbac-app-extraction-design.md §2.

Everything else RBAC lives in the `rbac` app.
"""

import pathlib
import uuid

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_superadmin", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_superadmin", True)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_superadmin") is not True:
            raise ValueError("Superuser must have is_superadmin=True")
        return self._create_user(email, password, **extra_fields)


def _avatar_upload_path(instance, filename):
    """Compute the storage path for a user's avatar upload.

    Discards the original filename to remove a filename-injection surface
    and to avoid leaking what the uploader called the file. The random
    uuid prevents collisions when the same user re-uploads after a delete
    while the on_commit cleanup of the previous file is still pending.
    """
    ext = pathlib.Path(filename).suffix.lower() or ".bin"
    return f"avatars/{instance.id}/{uuid.uuid4().hex}{ext}"


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=255, blank=True, null=True)
    avatar = models.ImageField(upload_to=_avatar_upload_path, blank=True, null=True)
    is_superadmin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "rbac_user"

    def __str__(self) -> str:
        return self.email
