import json

from manager.domain.enums import VenvBuildErrorKind, VenvStatus, WheelStatus
from manager.domain.models import CustomLibrary, Library, Venv, Wheel
from manager.infrastructure.database.venvs.tables import (
    CustomLibraryTable,
    VenvTable,
    WheelTable,
)


class VenvMapper:
    @staticmethod
    def to_domain(row: VenvTable) -> Venv:
        raw_libs = row.libs if isinstance(row.libs, list) else json.loads(row.libs or "[]")
        return Venv(
            id=row.id,
            name=row.name,
            libs=[Library(**lib) for lib in raw_libs],
            hash=row.hash,
            status=VenvStatus(row.status),
            error=row.error,
            error_kind=VenvBuildErrorKind(row.error_kind) if row.error_kind is not None else None,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def dump_libs(libs: list[Library]) -> list[dict]:
        return [lib.model_dump() for lib in libs]


class CustomLibraryMapper:
    @staticmethod
    def to_domain(row: CustomLibraryTable) -> CustomLibrary:
        return CustomLibrary(
            id=row.id,
            name=row.name,
            is_deleted=row.is_deleted,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class WheelMapper:
    @staticmethod
    def to_domain(row: WheelTable) -> Wheel:
        return Wheel(
            id=row.id,
            library_id=row.library,
            source_filename=row.source_filename,
            wheel_filename=row.wheel_filename,
            upload_sha256=row.upload_sha256,
            version=row.version,
            status=WheelStatus(row.status),
            error=row.error,
            is_deleted=row.is_deleted,
            created_at=row.created_at,
        )
