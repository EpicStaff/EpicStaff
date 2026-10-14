from datetime import datetime
from typing import Any, Self

from foundation.schemas import Schema
from pydantic import Field

from manager.domain.enums import JobStatus, VenvStatus
from manager.domain.models import Library, Venv

__all__ = [
    "ExecutionAcceptedSchema",
    "ExecutionSubmitSchema",
    "LibraryRetrieveSchema",
    "LibraryWriteSchema",
    "VenvCreateSchema",
    "VenvListSchema",
    "VenvRetrieveSchema",
    "VenvUpdateSchema",
]


class LibraryWriteSchema(Schema):
    """A library as a client declares it."""

    name: str
    description: str | None = None
    specification: str = ""
    version: str | None = None

    def to_domain(self) -> Library:
        return Library(
            name=self.name,
            description=self.description,
            specification=self.specification,
            version=self.version,
        )


class LibraryRetrieveSchema(Schema):
    name: str
    description: str | None = None
    specification: str
    version: str | None = None

    @classmethod
    def from_domain(cls, library: Library) -> Self:
        return cls(
            name=library.name,
            description=library.description,
            specification=library.specification,
            version=library.version,
        )


class VenvCreateSchema(Schema):
    name: str
    libs: list[LibraryWriteSchema]


class VenvListSchema(Schema):
    count: int = Field(ge=0)
    limit: int = Field(ge=0)
    offset: int = Field(ge=0)
    next: str | None = None
    previous: str | None = None
    result: list["VenvRetrieveSchema"]


class VenvRetrieveSchema(Schema):
    id: int
    name: str
    libs: list[LibraryRetrieveSchema]
    status: VenvStatus
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, venv: Venv) -> Self:
        return cls(
            id=venv.id,
            name=venv.name,
            libs=[LibraryRetrieveSchema.from_domain(lib) for lib in venv.libs],
            status=venv.status,
            error=venv.error,
            created_at=venv.created_at,
            updated_at=venv.updated_at,
        )


class VenvUpdateSchema(Schema):
    # An absent `libs` leaves the declared libraries alone; a list replaces all of them.
    name: str | None = None
    libs: list[LibraryWriteSchema] | None = None


class ExecutionSubmitSchema(Schema):
    execution_id: str
    # Optional: tool paths at session start can submit without a session. Matches
    # ExecutionJobMessage.session_id, which is already int | None.
    session_id: int | None = None
    code: str
    entrypoint: str
    global_kwargs: dict[str, Any] = {}
    func_kwargs: dict[str, Any] = {}
    secrets: dict[str, Any] = {}
    venv_id: int | None = None
    use_storage: bool = False
    storage_allowed_paths: list[str] = []
    storage_org_prefix: str | None = None
    timeout: float | None = None


class ExecutionAcceptedSchema(Schema):
    execution_id: str
    status: JobStatus
