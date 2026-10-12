from __future__ import annotations

import abc
import builtins

from manager.domain.enums import VenvStatus
from manager.domain.models import Venv


class AbstractVenvRepository(abc.ABC):
    @abc.abstractmethod
    async def list(
        self,
        *,
        ids: builtins.list[int] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[builtins.list[Venv], int]:
        """Return a page of venvs and the total matching the filter.

        `ids` restricts the result to those venv ids -- the gateway passes the
        caller organization's ids so one org never sees another's venvs; `None`
        lists all. `limit`/`offset` page the rows; the returned count is the
        total before paging.
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
