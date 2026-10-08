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
import re
import uuid

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models

DISPLAY_NAME_MAX_LENGTH = 255

_DIGITS = re.compile(r"\d")

# Any character that is not a letter or an apostrophe starts a new word.
_WORD_SEPARATORS = re.compile(r"[^\w']|_")

# "JohnSmith" / "johnSmith": letters, then one or more capitalized lowercase runs.
_CAMEL_CASE_WORD = re.compile(r"[A-Za-z][a-z]+(?:[A-Z][a-z]+)+")

_CAMEL_CASE_PART = re.compile(r"[A-Z]?[a-z]+")

_REPEATED_LETTER_RUN = re.compile(r"(.)\1{5,}")

_MAX_REPEATED_LETTERS = 5


def display_name_from_email(email: str) -> str:
    """Derive a display name from an email: "john.smith@acme.com" -> "John Smith".

    Digits are dropped, any symbol but an apostrophe splits words, camelCase is split, a
    letter repeated more than 5 times is cut to 5 and each word is recased ("JOHN" -> "John").
    With no letters left, the raw local part is kept ("=2+5").
    """
    local_part = email.rpartition("@")[0] if "@" in email else email
    pieces = _WORD_SEPARATORS.split(_DIGITS.sub("", local_part))
    words = []
    for piece in filter(None, (piece.strip("'") for piece in pieces)):
        words.extend(
            _CAMEL_CASE_PART.findall(piece) if _CAMEL_CASE_WORD.fullmatch(piece) else [piece]
        )
    display_name = " ".join(
        _REPEATED_LETTER_RUN.sub(
            lambda run: run.group(1) * _MAX_REPEATED_LETTERS, word.lower()
        ).capitalize()
        for word in words
    )
    if not display_name:
        display_name = local_part.strip() or email.strip()
    return display_name[:DISPLAY_NAME_MAX_LENGTH].rstrip()


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")
        email = self.normalize_email(email)
        # Every user is created here, so this guarantees a display name; a non-blank
        # caller value is kept as given (trimming is the validators' job).
        display_name = extra_fields.get("display_name")
        if display_name is None or not display_name.strip():
            extra_fields["display_name"] = display_name_from_email(email)
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
    display_name = models.CharField(max_length=DISPLAY_NAME_MAX_LENGTH, blank=True, null=True)
    avatar = models.ImageField(upload_to=_avatar_upload_path, blank=True, null=True)
    is_superadmin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    quickstart_tour_completed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the user finished or skipped the Quick Start tour; null means not completed or skipped yet.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "rbac_user"

    def __str__(self) -> str:
        return self.email
