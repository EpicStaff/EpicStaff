import json

from manager.domain.enums import VenvStatus
from manager.domain.models import Library, Venv
from manager.infrastructure.database.venvs.tables import VenvTable


class VenvMapper:
    @staticmethod
    def to_domain(row: VenvTable) -> Venv:
        # JSONB may come back as a str depending on Piccolo config; handle both.
        raw_libs = row.libs if isinstance(row.libs, list) else json.loads(row.libs or "[]")
        return Venv(
            id=row.id,
            name=row.name,
            libs=[Library(**lib) for lib in raw_libs],
            hash=row.hash,
            status=VenvStatus(row.status),
            error=row.error,
        )

    @staticmethod
    def dump_libs(libs: list[Library]) -> list[dict]:
        return [lib.model_dump() for lib in libs]
