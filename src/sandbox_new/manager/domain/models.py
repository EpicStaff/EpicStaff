from typing import Any
from uuid import UUID

from foundation.base import Entity, ValueObject
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from pydantic import Field, field_validator

from manager.domain.enums import JobStatus, VenvStatus

__all__ = ["DEFAULT_VENV_NAME", "Job", "Library", "Venv"]

DEFAULT_VENV_NAME = "default"

VERSION_PATTERN = r"^([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*((a|b|rc)(0|[1-9][0-9]*))?(\.post(0|[1-9][0-9]*))?(\.dev(0|[1-9][0-9]*))?$"


class Library(ValueObject):
    name: str = Field(min_length=1)
    specification: str = ""
    version: str | None = Field(default=None, pattern=VERSION_PATTERN)

    @field_validator("specification")
    @classmethod
    def validate_version_specification(cls, value: str) -> str:
        try:
            SpecifierSet(value)
        except InvalidSpecifier as e:
            raise ValueError(f"Invalid version specification: '{value}'") from e
        return value


class Venv(Entity):
    id: int | None = Field(default=None, frozen=True)
    name: str = Field(min_length=1)
    libs: list[Library] = Field(default_factory=list)
    hash: str | None = None
    status: VenvStatus = VenvStatus.DECLARED
    error: str | None = None

    def rename(self, value: str, /):
        self.name = value

    def set_libs(self, value: list[Library], /):
        self.libs = value
        self.mark_as_declared()

    def mark_as_declared(self):
        self.error = None
        self.status = VenvStatus.DECLARED

    def mark_as_processing(self):
        self.status = VenvStatus.PROCESSING

    def mark_as_completed(self):
        self.error = None
        self.status = VenvStatus.COMPLETED

    def mark_as_failed(self, error: Exception):
        self.error = str(error)
        self.status = VenvStatus.FAILED


class Job(Entity):
    id: UUID | None = Field(default=None, frozen=True)
    session_id: int
    execution_id: str
    venv_id: int
    venv_hash: str | None = None
    status: JobStatus = JobStatus.ACCEPTED
    code: str
    result: str
    entrypoint: str
    secrets: dict[str, Any] = Field(default_factory=dict)
    global_kwargs: dict[str, Any] = Field(default_factory=dict)
    func_kwargs: dict[str, Any] = Field(default_factory=dict)
    use_storage: bool = False
    storage_allowed_paths: list[str] = Field(default_factory=list)
    storage_org_prefix: str | None = None
    timeout: float | None = None
    error: str | None = None
