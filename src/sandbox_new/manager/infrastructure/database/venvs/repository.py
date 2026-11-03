from __future__ import annotations

import builtins
import json

from piccolo.querystring import QueryString

from manager.domain.enums import VenvOrder, VenvStatus, WheelStatus
from manager.domain.models import DEFAULT_VENV_NAME, CustomLibrary, Venv, Wheel
from manager.domain.ports import (
    AbstractCustomLibraryRepository,
    AbstractVenvRepository,
    AbstractWheelRepository,
)
from manager.infrastructure.database.venvs.mappers import (
    CustomLibraryMapper,
    VenvMapper,
    WheelMapper,
)
from manager.infrastructure.database.venvs.tables import (
    CustomLibraryTable,
    VenvTable,
    WheelTable,
)

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

    async def list_by_status(self, *statuses: VenvStatus) -> builtins.list[Venv]:
        if not statuses:
            return []
        rows: list[VenvTable] = await VenvTable.objects().where(
            VenvTable.status.is_in(list(statuses))
        )
        return [VenvMapper.to_domain(row) for row in rows]

    async def list_by_hashes(self, hashes: set[str]) -> builtins.list[Venv]:
        if not hashes:
            return []
        rows = await VenvTable.objects().where(VenvTable.hash.is_in(list(hashes)))
        return [VenvMapper.to_domain(row) for row in rows]

    async def list_using_custom_library(self, name: str) -> builtins.list[Venv]:
        """Every venv whose `libs` holds an entry with this name marked custom.

        `@>` asks Postgres whether the JSONB array contains an element with these
        fields, so the whole venv table never crosses the wire. Raw SQL because
        Piccolo has no containment operator of its own.
        """
        rows = await VenvTable.raw(
            "SELECT * FROM venv WHERE libs @> {}",
            json.dumps([{"name": name, "is_custom": True}]),
        )
        return [VenvMapper.to_domain(VenvTable(**row)) for row in rows]

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


class PiccoloCustomLibraryRepository(AbstractCustomLibraryRepository):
    async def list(
        self,
        *,
        ids: builtins.list[int] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[builtins.list[CustomLibrary], int]:
        if ids is not None and not ids:
            return [], 0

        conditions = [CustomLibraryTable.is_deleted.eq(False)]
        if ids is not None:
            conditions.append(CustomLibraryTable.id.is_in(ids))

        rows_query = CustomLibraryTable.objects()
        count_query = CustomLibraryTable.count()
        for condition in conditions:
            rows_query = rows_query.where(condition)
            count_query = count_query.where(condition)

        total = await count_query
        rows_query = rows_query.order_by(CustomLibraryTable.id)
        if offset is not None:
            rows_query = rows_query.offset(offset)
        if limit is not None:
            rows_query = rows_query.limit(limit)
        rows = await rows_query
        return [CustomLibraryMapper.to_domain(row) for row in rows], total

    async def retrieve(self, id: int) -> CustomLibrary | None:
        row = await CustomLibraryTable.objects().get(
            (CustomLibraryTable.id == id) & (CustomLibraryTable.is_deleted.eq(False))
        )
        return CustomLibraryMapper.to_domain(row) if row is not None else None

    async def retrieve_by_name(self, name: str) -> CustomLibrary | None:
        row = await CustomLibraryTable.objects().get(
            (CustomLibraryTable.name == name) & (CustomLibraryTable.is_deleted.eq(False))
        )
        return CustomLibraryMapper.to_domain(row) if row is not None else None

    async def list_by_names(self, names: builtins.list[str]) -> builtins.list[CustomLibrary]:
        # Guarded: an empty `IN ()` would be dropped and the query would answer with
        # every library rather than none.
        if not names:
            return []
        rows = await CustomLibraryTable.objects().where(
            CustomLibraryTable.name.is_in(names) & CustomLibraryTable.is_deleted.eq(False)
        )
        return [CustomLibraryMapper.to_domain(row) for row in rows]

    async def create(self, obj: CustomLibrary) -> CustomLibrary:
        row = CustomLibraryTable(name=obj.name, is_deleted=obj.is_deleted)
        await row.save()
        return CustomLibraryMapper.to_domain(row)

    async def update(self, obj: CustomLibrary) -> CustomLibrary:
        # `updated_at` is left out: the `custom_library_set_updated_at` trigger owns it.
        rows = (
            await CustomLibraryTable.update(
                {
                    CustomLibraryTable.name: obj.name,
                    CustomLibraryTable.is_deleted: obj.is_deleted,
                }
            )
            .where(CustomLibraryTable.id == obj.id)
            .returning(*CustomLibraryTable.all_columns())
        )
        return CustomLibraryMapper.to_domain(CustomLibraryTable(**rows[0]))

    async def remove(self, obj: CustomLibrary) -> None:
        await CustomLibraryTable.delete().where(CustomLibraryTable.id == obj.id)

    async def list_deleted(self) -> builtins.list[CustomLibrary]:
        rows = (
            await CustomLibraryTable.objects()
            .where(CustomLibraryTable.is_deleted.eq(True))
            .order_by(CustomLibraryTable.created_at)
        )
        return [CustomLibraryMapper.to_domain(row) for row in rows]


class PiccoloWheelRepository(AbstractWheelRepository):
    async def list(self, library_id: int) -> builtins.list[Wheel]:
        rows = (
            await WheelTable.objects()
            .where((WheelTable.library == library_id) & (WheelTable.is_deleted.eq(False)))
            .order_by(WheelTable.id)
        )
        return [WheelMapper.to_domain(row) for row in rows]

    async def retrieve(self, library_id: int, id: int) -> Wheel | None:
        return await self._retrieve_where(WheelTable.id == id, library_id)

    async def retrieve_by_version(self, library_id: int, version: str) -> Wheel | None:
        return await self._retrieve_where(WheelTable.version == version, library_id)

    async def retrieve_by_sha256(self, library_id: int, sha256: str) -> Wheel | None:
        return await self._retrieve_where(WheelTable.upload_sha256 == sha256, library_id)

    @staticmethod
    async def _retrieve_where(condition, library_id: int) -> Wheel | None:
        """Return the one live wheel of `library_id` matching `condition`.

        A wheel is addressed through its library, so the library is part of every
        lookup: an id belonging to another one must not answer.
        """
        row = await WheelTable.objects().get(
            condition & (WheelTable.library == library_id) & (WheelTable.is_deleted.eq(False))
        )
        return WheelMapper.to_domain(row) if row is not None else None

    async def create(self, obj: Wheel) -> Wheel:
        row = WheelTable(
            library=obj.library_id,
            source_filename=obj.source_filename,
            wheel_filename=obj.wheel_filename,
            upload_sha256=obj.upload_sha256,
            version=obj.version,
            status=obj.status,
            error=obj.error,
            is_deleted=obj.is_deleted,
        )
        await row.save()
        return WheelMapper.to_domain(row)

    async def update(self, obj: Wheel) -> Wheel:
        rows = (
            await WheelTable.update(
                {
                    WheelTable.source_filename: obj.source_filename,
                    WheelTable.wheel_filename: obj.wheel_filename,
                    WheelTable.upload_sha256: obj.upload_sha256,
                    WheelTable.version: obj.version,
                    WheelTable.status: obj.status,
                    WheelTable.error: obj.error,
                    WheelTable.is_deleted: obj.is_deleted,
                }
            )
            .where(WheelTable.id == obj.id)
            .returning(*WheelTable.all_columns())
        )
        return WheelMapper.to_domain(WheelTable(**rows[0]))

    async def remove(self, obj: Wheel) -> None:
        await WheelTable.delete().where(WheelTable.id == obj.id)

    async def list_by_library_ids(self, ids: builtins.list[int]) -> builtins.list[Wheel]:
        if not ids:
            return []
        rows = await WheelTable.objects().where(
            WheelTable.library.is_in(ids) & WheelTable.is_deleted.eq(False)
        )
        return [WheelMapper.to_domain(row) for row in rows]

    async def list_by_status(self, status: WheelStatus) -> builtins.list[Wheel]:
        rows = await WheelTable.objects().where(
            (WheelTable.status == status) & (WheelTable.is_deleted.eq(False))
        )
        return [WheelMapper.to_domain(row) for row in rows]

    async def list_deleted(self) -> builtins.list[Wheel]:
        rows = (
            await WheelTable.objects()
            .where(WheelTable.is_deleted.eq(True))
            .order_by(WheelTable.created_at)
        )
        return [WheelMapper.to_domain(row) for row in rows]

    async def count_by_library(self, library_id: int) -> int:
        # No is_deleted filter on purpose: a wheel still waiting to be reaped counts.
        return await WheelTable.count().where(WheelTable.library == library_id)
