from __future__ import annotations

import builtins

from piccolo.querystring import QueryString

from manager.domain.enums import VenvOrder, VenvStatus
from manager.domain.models import DEFAULT_VENV_NAME, Venv
from manager.domain.ports import AbstractVenvRepository
from manager.infrastructure.database.venvs.mappers import VenvMapper
from manager.infrastructure.database.venvs.tables import VenvTable

LIKE_WILDCARDS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})

ORDER_BY = {
    VenvOrder.DEFAULT: (VenvTable.id, True),
    VenvOrder.NAME_ASC: (QueryString('LOWER("name")'), True),
    VenvOrder.NAME_DESC: (QueryString('LOWER("name")'), False),
}


class PiccoloVenvRepository(AbstractVenvRepository):
    async def list(
        self,
        *,
        ids: builtins.list[int] | None = None,
        name_contains: str | None = None,
        order: VenvOrder = VenvOrder.DEFAULT,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[builtins.list[Venv], int]:
        if ids is not None and not ids:
            return [], 0

        conditions = []
        if ids is not None:
            conditions.append(VenvTable.id.is_in(ids))
        if name_contains:
            pattern = name_contains.translate(LIKE_WILDCARDS)
            conditions.append(VenvTable.name.ilike(f"%{pattern}%"))

        rows_query = VenvTable.objects()
        count_query = VenvTable.count()
        for condition in conditions:
            rows_query = rows_query.where(condition)
            count_query = count_query.where(condition)

        total = await count_query
        column, ascending = ORDER_BY[order]
        rows_query = rows_query.order_by(column, ascending=ascending)
        if offset is not None:
            rows_query = rows_query.offset(offset)
        if limit is not None:
            rows_query = rows_query.limit(limit)
        rows = await rows_query
        return [VenvMapper.to_domain(row) for row in rows], total

    async def list_by_status(self, status: VenvStatus) -> builtins.list[Venv]:
        rows: list[VenvTable] = await VenvTable.objects().where(VenvTable.status == status)
        return [VenvMapper.to_domain(row) for row in rows]

    async def list_by_hashes(self, hashes: set[str]) -> builtins.list[Venv]:
        if not hashes:
            return []
        rows = await VenvTable.objects().where(VenvTable.hash.is_in(list(hashes)))
        return [VenvMapper.to_domain(row) for row in rows]

    async def retrieve(self, id: int) -> Venv | None:
        row = await VenvTable.objects().get(VenvTable.id == id)
        return VenvMapper.to_domain(row) if row is not None else None

    async def retrieve_by_name(self, name: str) -> Venv | None:
        row = await VenvTable.objects().get(VenvTable.name == name)
        return VenvMapper.to_domain(row) if row is not None else None

    async def retrieve_default(self) -> Venv | None:
        return await self.retrieve_by_name(DEFAULT_VENV_NAME)

    async def create(self, obj: Venv) -> Venv:
        row = VenvTable(
            name=obj.name,
            libs=VenvMapper.dump_libs(obj.libs),
            hash=obj.hash,
            status=obj.status,
            error=obj.error,
        )
        await row.save()
        return VenvMapper.to_domain(row)

    async def update(self, obj: Venv) -> Venv:
        rows = (
            await VenvTable.update(
                {
                    VenvTable.name: obj.name,
                    VenvTable.libs: VenvMapper.dump_libs(obj.libs),
                    VenvTable.hash: obj.hash,
                    VenvTable.status: obj.status,
                    VenvTable.error: obj.error,
                }
            )
            .where(VenvTable.id == obj.id)
            .returning(*VenvTable.all_columns())
        )
        return VenvMapper.to_domain(VenvTable(**rows[0]))

    async def remove(self, obj: Venv) -> None:
        await VenvTable.delete().where(VenvTable.id == obj.id)
