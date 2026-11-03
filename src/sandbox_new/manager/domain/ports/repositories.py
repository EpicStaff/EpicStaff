from __future__ import annotations

import abc
import builtins

from manager.domain.enums import VenvOrder, VenvStatus, WheelStatus
from manager.domain.models import CustomLibrary, Venv, Wheel


class AbstractVenvRepository(abc.ABC):
    @abc.abstractmethod
    async def list(
        self,
        *,
        ids: builtins.list[int] | None = None,
        name_contains: str | None = None,
        order: VenvOrder = VenvOrder.DEFAULT,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[builtins.list[Venv], int]:
        """Return a page of venvs and the total matching the filters.

        `ids` restricts the result to those venv ids -- the gateway passes the
        caller organization's ids so one org never sees another's venvs; `None`
        lists all. `name_contains` keeps the venvs whose name contains it,
        ignoring case. `order` sorts the rows before they are paged.
        `limit`/`offset` page the rows; the returned count is the total matching
        the filters, counted before paging.
        """

    @abc.abstractmethod
    async def list_by_status(self, status: VenvStatus) -> builtins.list[Venv]:
        pass

    @abc.abstractmethod
    async def list_by_hashes(self, hashes: set[str]) -> builtins.list[Venv]:
        pass

    @abc.abstractmethod
    async def retrieve(self, id: int) -> Venv | None:
        pass

    @abc.abstractmethod
    async def retrieve_by_name(self, name: str) -> Venv | None:
        pass

    @abc.abstractmethod
    async def retrieve_default(self) -> Venv | None:
        pass

    @abc.abstractmethod
    async def create(self, obj: Venv) -> Venv:
        pass

    @abc.abstractmethod
    async def update(self, obj: Venv) -> Venv:
        pass

    @abc.abstractmethod
    async def remove(self, obj: Venv):
        pass


class AbstractCustomLibraryRepository(abc.ABC):
    """Custom libraries as they are stored.

    Every method but `list_deleted` sees only libraries that are not marked deleted:
    a marked one is on its way out and must not answer a read any more.
    """

    @abc.abstractmethod
    async def list(
        self,
        *,
        ids: builtins.list[int] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[builtins.list[CustomLibrary], int]:
        """Return a page of libraries and the total matching the filters.

        `ids` restricts the result to those library ids; `None` lists all.
        `limit`/`offset` page the rows; the returned count is the total matching
        the filters, counted before paging.
        """

    @abc.abstractmethod
    async def retrieve(self, id: int) -> CustomLibrary | None:
        pass

    @abc.abstractmethod
    async def retrieve_by_name(self, name: str) -> CustomLibrary | None:
        """Return the library with this canonical name, for the uniqueness check."""

    @abc.abstractmethod
    async def create(self, obj: CustomLibrary) -> CustomLibrary:
        pass

    @abc.abstractmethod
    async def update(self, obj: CustomLibrary) -> CustomLibrary:
        pass

    @abc.abstractmethod
    async def remove(self, obj: CustomLibrary):
        """Delete the row outright. The reaper calls this once the artifacts are gone."""

    @abc.abstractmethod
    async def list_deleted(self) -> builtins.list[CustomLibrary]:
        """Return the libraries marked deleted, oldest first, for the reaper."""


class AbstractWheelRepository(abc.ABC):
    """Wheels as they are stored.

    Every method but `list_deleted` and `count_by_library` sees only wheels that are not
    marked deleted, and every read is scoped to one library: a wheel is addressed through
    its library, so an id belonging to another one answers `None`.
    """

    @abc.abstractmethod
    async def list(self, library_id: int) -> builtins.list[Wheel]:
        """Return every wheel of this library. Not paged: a library holds few versions."""

    @abc.abstractmethod
    async def retrieve(self, library_id: int, id: int) -> Wheel | None:
        pass

    @abc.abstractmethod
    async def retrieve_by_version(self, library_id: int, version: str) -> Wheel | None:
        """Return this library's wheel for that version, for the uniqueness check."""

    @abc.abstractmethod
    async def retrieve_by_sha256(self, library_id: int, sha256: str) -> Wheel | None:
        """Return this library's wheel built from that upload, for the uniqueness check."""

    @abc.abstractmethod
    async def create(self, obj: Wheel) -> Wheel:
        pass

    @abc.abstractmethod
    async def update(self, obj: Wheel) -> Wheel:
        pass

    @abc.abstractmethod
    async def remove(self, obj: Wheel):
        """Delete the row outright. The reaper calls this once the artifacts are gone."""

    @abc.abstractmethod
    async def list_by_status(self, status: WheelStatus) -> builtins.list[Wheel]:
        """Return the wheels in this status, for the background builder."""

    @abc.abstractmethod
    async def list_deleted(self) -> builtins.list[Wheel]:
        """Return the wheels marked deleted, oldest first, for the reaper."""

    @abc.abstractmethod
    async def count_by_library(self, library_id: int) -> int:
        """Return how many rows this library still has, marked deleted or not.

        The exception to the rule above, and the reason it exists: the reaper may only
        drop a library row once nothing points at it. The foreign key cascades, so
        deleting the library while a wheel it could not reap is still stored would take
        that row with it and strand its files in the object store.
        """
