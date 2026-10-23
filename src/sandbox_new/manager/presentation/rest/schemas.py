from datetime import datetime
from typing import Self

from foundation.clients.sandbox import ExecutionRequest, ExecutionStorageCredentials
from foundation.schemas import Schema
from pydantic import Field, model_validator

from manager.domain.enums import ExecutionStatus, VenvStatus
from manager.domain.models import Library, StorageCredentials, Venv

__all__ = [
    "ExecutionAcceptedSchema",
    "ExecutionStatusSchema",
    "ExecutionSubmitSchema",
    "LibraryRetrieveSchema",
    "LibraryWriteSchema",
    "StorageCredentialsSchema",
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


class StorageCredentialsSchema(ExecutionStorageCredentials):
    """Object-store credentials the caller issued for this execution."""

    def to_domain(self) -> StorageCredentials:
        return StorageCredentials(access_key=self.access_key, secret_key=self.secret_key)


class ExecutionSubmitSchema(ExecutionRequest):
    """The submission body; its fields are the producers' `ExecutionRequest` contract."""

    # Re-declared only to parse into the subclass that maps to the domain.
    storage_credentials: StorageCredentialsSchema | None = Field(default=None, repr=False)

    @model_validator(mode="after")
    def require_everything_storage_needs(self) -> Self:
        """Reject a storage submission that is missing its prefix or its credentials.

        Fail closed: the worker cannot reach storage without both, and a job accepted
        here would only fail later, after the caller was told it was accepted.

        Raises:
            ValueError: `use_storage` is set without `storage_org_prefix` or without
                `storage_credentials`. Rendered as 400.
        """
        if not self.use_storage:
            return self
        missing = [
            name
            for name, value in (
                ("storage_org_prefix", self.storage_org_prefix),
                ("storage_credentials", self.storage_credentials),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"use_storage requires {' and '.join(missing)}")
        return self


class ExecutionAcceptedSchema(Schema):
    execution_id: str
    status: ExecutionStatus


class ExecutionStatusSchema(Schema):
    execution_id: str
    status: ExecutionStatus
