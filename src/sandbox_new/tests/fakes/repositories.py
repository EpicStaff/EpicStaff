"""In-memory stand-ins for the repositories.

Each subclasses the real port, so a change to one of them breaks this at
import time instead of drifting away from it silently. Every read hands out a copy and
every write stores a copy, so a caller that mutates what it read without calling
``update`` does not change the stored row -- a real repository would behave the same way.

Inserting fills ``created_at``/``updated_at`` the way the database does, and updating
bumps ``updated_at`` the way the `venv_set_updated_at` trigger does, then hands back the
stored row -- the Piccolo repository reads the row back for the same reason.
"""

from __future__ import annotations

from datetime import UTC, datetime

from manager.domain.enums import VenvOrder, VenvStatus, WheelStatus
from manager.domain.models import DEFAULT_VENV_NAME, CustomLibrary, Venv, Wheel
from manager.domain.ports import (
    AbstractCustomLibraryRepository,
    AbstractVenvRepository,
    AbstractWheelRepository,
)

__all__ = ["FakeCustomLibraryRepository", "FakeVenvRepository", "FakeWheelRepository"]


class FakeVenvRepository(AbstractVenvRepository):
    def __init__(self) -> None:
        self.rows: dict[int, Venv] = {}
        self._next_id = 1

    def seed(self, *venvs: Venv) -> list[Venv]:
        """Insert rows directly, bypassing ``create``. Returns the stored copies."""
        stored = []
        for venv in venvs:
            if venv.id is None:
                stored.append(self._insert(venv))
            else:
                self.rows[venv.id] = venv.model_copy(
                    deep=True, update=self._stored_timestamps(venv)
                )
                self._next_id = max(self._next_id, venv.id + 1)
                stored.append(self.rows[venv.id].model_copy(deep=True))
        return stored

    @staticmethod
    def _stored_timestamps(venv: Venv) -> dict[str, datetime]:
        moment = datetime.now(UTC)
        return {
            "created_at": venv.created_at or moment,
            "updated_at": venv.updated_at or moment,
        }

    def _insert(self, venv: Venv) -> Venv:
        stored = venv.model_copy(
            deep=True, update={"id": self._next_id, **self._stored_timestamps(venv)}
        )
        self.rows[self._next_id] = stored
        self._next_id += 1
        return stored.model_copy(deep=True)

    async def list(
        self,
        *,
        ids=None,
        name_contains=None,
        order=VenvOrder.DEFAULT,
        limit=None,
        offset=None,
    ) -> tuple[list[Venv], int]:
        if ids is not None and not ids:
            return [], 0

        rows = list(self.rows.values())
        if ids is not None:
            rows = [row for row in rows if row.id in ids]
        if name_contains:
            # A plain substring, the way the escaped ILIKE pattern of the real repository
            # matches: what the caller typed as `%` or `_` is that character, not a wildcard.
            term = name_contains.lower()
            rows = [row for row in rows if term in row.name.lower()]

        total = len(rows)
        if order is VenvOrder.DEFAULT:
            rows.sort(key=lambda row: row.id)
        else:
            rows.sort(key=lambda row: row.name.lower(), reverse=order is VenvOrder.NAME_DESC)
        if offset is not None:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return [row.model_copy(deep=True) for row in rows], total

    async def list_by_status(self, status: VenvStatus) -> list[Venv]:
        return [row.model_copy(deep=True) for row in self.rows.values() if row.status is status]

    async def list_by_hashes(self, hashes: set[str]) -> list[Venv]:
        if not hashes:
            return []
        return [row.model_copy(deep=True) for row in self.rows.values() if row.hash in hashes]

    async def retrieve(self, id: int) -> Venv | None:
        row = self.rows.get(id)
        return row.model_copy(deep=True) if row is not None else None

    async def retrieve_by_name(self, name: str) -> Venv | None:
        row = next((row for row in self.rows.values() if row.name == name), None)
        return row.model_copy(deep=True) if row is not None else None

    async def retrieve_default(self) -> Venv | None:
        return await self.retrieve_by_name(DEFAULT_VENV_NAME)

    async def create(self, obj: Venv) -> Venv:
        return self._insert(obj)

    async def update(self, obj: Venv) -> Venv:
        # The trigger bumps `updated_at` and the update statement never touches
        # `created_at`, so neither is taken from the caller's copy.
        self.rows[obj.id] = obj.model_copy(
            deep=True,
            update={
                "created_at": self.rows[obj.id].created_at,
                "updated_at": datetime.now(UTC),
            },
        )
        return self.rows[obj.id].model_copy(deep=True)

    async def remove(self, obj: Venv) -> None:
        self.rows.pop(obj.id, None)


class FakeCustomLibraryRepository(AbstractCustomLibraryRepository):
    def __init__(self) -> None:
        self.rows: dict[int, CustomLibrary] = {}
        self._next_id = 1

    def seed(self, *libraries: CustomLibrary) -> list[CustomLibrary]:
        """Insert rows directly, bypassing ``create``. Returns the stored copies."""
        return [self._insert(library) for library in libraries]

    def _insert(self, library: CustomLibrary) -> CustomLibrary:
        moment = datetime.now(UTC)
        stored = library.model_copy(
            deep=True,
            update={
                "id": self._next_id,
                "created_at": library.created_at or moment,
                "updated_at": library.updated_at or moment,
            },
        )
        self.rows[self._next_id] = stored
        self._next_id += 1
        return stored.model_copy(deep=True)

    def _live(self) -> list[CustomLibrary]:
        return [row for row in self.rows.values() if not row.is_deleted]

    async def list(self, *, ids=None, limit=None, offset=None) -> tuple[list[CustomLibrary], int]:
        if ids is not None and not ids:
            return [], 0

        rows = self._live()
        if ids is not None:
            rows = [row for row in rows if row.id in ids]

        total = len(rows)
        rows.sort(key=lambda row: row.id)
        if offset is not None:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return [row.model_copy(deep=True) for row in rows], total

    async def retrieve(self, id: int) -> CustomLibrary | None:
        row = self.rows.get(id)
        if row is None or row.is_deleted:
            return None
        return row.model_copy(deep=True)

    async def retrieve_by_name(self, name: str) -> CustomLibrary | None:
        row = next((row for row in self._live() if row.name == name), None)
        return row.model_copy(deep=True) if row is not None else None

    async def create(self, obj: CustomLibrary) -> CustomLibrary:
        return self._insert(obj)

    async def update(self, obj: CustomLibrary) -> CustomLibrary:
        self.rows[obj.id] = obj.model_copy(
            deep=True,
            update={
                "created_at": self.rows[obj.id].created_at,
                "updated_at": datetime.now(UTC),
            },
        )
        return self.rows[obj.id].model_copy(deep=True)

    async def remove(self, obj: CustomLibrary) -> None:
        self.rows.pop(obj.id, None)

    async def list_deleted(self) -> list[CustomLibrary]:
        rows = [row for row in self.rows.values() if row.is_deleted]
        rows.sort(key=lambda row: row.created_at)
        return [row.model_copy(deep=True) for row in rows]


class FakeWheelRepository(AbstractWheelRepository):
    def __init__(self) -> None:
        self.rows: dict[int, Wheel] = {}
        self._next_id = 1

    def seed(self, *wheels: Wheel) -> list[Wheel]:
        """Insert rows directly, bypassing ``create``. Returns the stored copies."""
        return [self._insert(wheel) for wheel in wheels]

    def _insert(self, wheel: Wheel) -> Wheel:
        stored = wheel.model_copy(
            deep=True,
            update={
                "id": self._next_id,
                "created_at": wheel.created_at or datetime.now(UTC),
            },
        )
        self.rows[self._next_id] = stored
        self._next_id += 1
        return stored.model_copy(deep=True)

    def _live(self, library_id: int) -> list[Wheel]:
        return [
            row
            for row in self.rows.values()
            if row.library_id == library_id and not row.is_deleted
        ]

    async def list(self, library_id: int) -> list[Wheel]:
        rows = sorted(self._live(library_id), key=lambda row: row.id)
        return [row.model_copy(deep=True) for row in rows]

    async def retrieve(self, library_id: int, id: int) -> Wheel | None:
        row = self.rows.get(id)
        if row is None or row.library_id != library_id or row.is_deleted:
            return None
        return row.model_copy(deep=True)

    async def retrieve_by_version(self, library_id: int, version: str) -> Wheel | None:
        row = next((row for row in self._live(library_id) if row.version == version), None)
        return row.model_copy(deep=True) if row is not None else None

    async def retrieve_by_sha256(self, library_id: int, sha256: str) -> Wheel | None:
        row = next((row for row in self._live(library_id) if row.upload_sha256 == sha256), None)
        return row.model_copy(deep=True) if row is not None else None

    async def create(self, obj: Wheel) -> Wheel:
        return self._insert(obj)

    async def update(self, obj: Wheel) -> Wheel:
        self.rows[obj.id] = obj.model_copy(
            deep=True, update={"created_at": self.rows[obj.id].created_at}
        )
        return self.rows[obj.id].model_copy(deep=True)

    async def remove(self, obj: Wheel) -> None:
        self.rows.pop(obj.id, None)

    async def list_by_status(self, status: WheelStatus) -> list[Wheel]:
        rows = [
            row for row in self.rows.values() if row.status is status and not row.is_deleted
        ]
        rows.sort(key=lambda row: row.id)
        return [row.model_copy(deep=True) for row in rows]

    async def list_deleted(self) -> list[Wheel]:
        rows = [row for row in self.rows.values() if row.is_deleted]
        rows.sort(key=lambda row: row.created_at)
        return [row.model_copy(deep=True) for row in rows]

    async def count_by_library(self, library_id: int) -> int:
        # No is_deleted filter on purpose: a wheel still waiting to be reaped counts.
        return sum(1 for row in self.rows.values() if row.library_id == library_id)
