"""In-memory stand-in for the venv repository.

Subclasses the real port, so a change to ``AbstractVenvRepository`` breaks this at
import time instead of drifting away from it silently. Every read hands out a copy and
every write stores a copy, so a caller that mutates what it read without calling
``update`` does not change the stored row -- a real repository would behave the same way.
"""

from __future__ import annotations

from manager.domain.enums import VenvStatus
from manager.domain.models import DEFAULT_VENV_NAME, Venv
from manager.domain.ports import AbstractVenvRepository

__all__ = ["FakeVenvRepository"]


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
                self.rows[venv.id] = venv.model_copy(deep=True)
                self._next_id = max(self._next_id, venv.id + 1)
                stored.append(self.rows[venv.id].model_copy(deep=True))
        return stored

    def _insert(self, venv: Venv) -> Venv:
        stored = venv.model_copy(deep=True, update={"id": self._next_id})
        self.rows[self._next_id] = stored
        self._next_id += 1
        return stored.model_copy(deep=True)

    async def list(self, *, ids=None, limit=None, offset=None) -> tuple[list[Venv], int]:
        if ids is not None and not ids:
            return [], 0

        rows = list(self.rows.values())
        if ids is not None:
            rows = [row for row in rows if row.id in ids]

        total = len(rows)
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
        self.rows[obj.id] = obj.model_copy(deep=True)
        return obj

    async def remove(self, obj: Venv) -> None:
        self.rows.pop(obj.id, None)
