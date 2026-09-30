from abc import ABC, abstractmethod

from django.db import models


class BaseCopyService(ABC):
    """Base class for all entity copy services.

    Subclasses must implement the ``copy`` method which duplicates
    the given entity and returns the new persisted instance.
    """

    @abstractmethod
    def copy(
        self,
        entity: models.Model,
        name: str | None = None,
        org_id: int | None = None,
        user=None,
    ) -> models.Model:
        """Duplicate `entity` and return the new row.

        `user` is the acting user; services that re-bind permission-gated references
        check it, the rest ignore it.
        """
