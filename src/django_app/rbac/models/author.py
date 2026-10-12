from typing import ClassVar

from django.conf import settings
from django.db import models

from rbac.exceptions import AuthorChangeForbiddenError

_AUTHOR_FIELD_NAMES = frozenset({"created_by", "created_by_id"})


class AuthorModel(models.Model):
    """Abstract model recording the author of a resource that has no org column of its own.

    `author_org_lookup` is the ORM lookup from a row to its owning organization id;
    concrete subclasses must set it so authorship can be released per organization.
    Once set, the author may be cleared but never replaced by another user.
    """

    author_org_lookup: ClassVar[str | None] = None

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        abstract = True

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._remember_loaded_author()
        return instance

    def refresh_from_db(self, using=None, fields=None, from_queryset=None):
        super().refresh_from_db(using=using, fields=fields, from_queryset=from_queryset)
        if fields is None or _AUTHOR_FIELD_NAMES.intersection(fields):
            self._remember_loaded_author()

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        persists_author = update_fields is None or _AUTHOR_FIELD_NAMES.intersection(update_fields)
        if persists_author:
            self._assert_author_unchanged()
        super().save(*args, **kwargs)
        if persists_author:
            self._remember_loaded_author()

    def _remember_loaded_author(self) -> None:
        # A deferred author is not in __dict__; reading it here would issue a query.
        if "created_by_id" in self.__dict__:
            self._loaded_created_by_id = self.created_by_id

    def _assert_author_unchanged(self) -> None:
        if self._state.adding or self.pk is None:
            return
        loaded_author_id = getattr(self, "_loaded_created_by_id", None)
        if loaded_author_id is None:
            return
        if self.created_by_id not in (None, loaded_author_id):
            raise AuthorChangeForbiddenError(
                f"{type(self).__name__} {self.pk}: author {loaded_author_id} cannot be "
                f"replaced by {self.created_by_id}."
            )
