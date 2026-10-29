from datetime import datetime
from typing import Any
from uuid import UUID

from foundation.base import Entity, ValueObject
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from pydantic import Field, field_validator, model_validator

from manager.domain.enums import JobStatus, VenvStatus
from manager.domain.types import LibraryString

__all__ = ["DEFAULT_VENV_NAME", "Job", "Library", "StorageCredentials", "Venv"]

DEFAULT_VENV_NAME = "default"

VERSION_PATTERN = r"^([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*((a|b|rc)(0|[1-9][0-9]*))?(\.post(0|[1-9][0-9]*))?(\.dev(0|[1-9][0-9]*))?(\+[a-z0-9]+([-_\.][a-z0-9]+)*)?$"


class Library(ValueObject):
    name: str = Field(min_length=1)
    description: str | None = None
    specification: str = ""
    version: str | None = Field(default=None, pattern=VERSION_PATTERN)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return canonicalize_name(value)

    @field_validator("specification")
    @classmethod
    def validate_version_specification(cls, value: str) -> str:
        try:
            SpecifierSet(value)
        except InvalidSpecifier as e:
            raise ValueError(f"Invalid version specification: '{value}'") from e
        return value

    @model_validator(mode="after")
    def validate_version_against_specification(self) -> "Library":
        if self.version is None:
            return self
        if not SpecifierSet(self.specification).contains(self.version, prereleases=True):
            raise ValueError(
                f"Version '{self.version}' does not satisfy specification '{self.specification}'"
            )
        return self

    @property
    def requirement(self) -> LibraryString:
        if self.version is not None:
            return f"{self.name}=={self.version}"
        return f"{self.name}{self.specification}"

    def with_resolved_version(self, value: str, /) -> "Library":
        """This library as the build resolved it: the installed version, and a
        specification when the declaration carried none.

        The default `>=<installed>` is what the user is held to from now on: the
        specification is the guard rail the version is validated against, so a
        library declared without one would otherwise accept any version later.
        An explicit specification is the user's, and is left alone.
        """
        specification = self.specification or f">={value}"
        return Library(**{**self.model_dump(), "version": value, "specification": specification})


class Venv(Entity):
    id: int | None = Field(default=None, frozen=True)
    name: str = Field(min_length=1, pattern=r"^[A-Za-z0-9 _-]+$")
    libs: list[Library] = Field(default_factory=list)
    hash: str | None = None
    status: VenvStatus = VenvStatus.DECLARED
    error: str | None = None
    # Assigned by the database, never by the domain: unset until the venv is stored.
    created_at: datetime | None = Field(default=None, frozen=True)
    updated_at: datetime | None = Field(default=None, frozen=True)

    @field_validator("libs")
    @classmethod
    def reject_repeated_libraries(cls, value: list[Library]) -> list[Library]:
        """Reject a library declared twice, whatever spelling each entry used.

        Two entries for one package give the resolver two requirements it cannot both
        honour, and it fails the whole build over it. Names reach here canonicalized,
        so `Pydantic` and `pydantic` count as the same package.

        Raises:
            ValueError: Some package is declared more than once.
        """
        seen: set[str] = set()
        for library in value:
            if library.name in seen:
                raise ValueError(f"Library '{library.name}' is declared more than once.")
            seen.add(library.name)
        return value

    def rename(self, value: str, /):
        self.name = value

    def set_libs(self, value: list[Library], /):
        self.libs = value
        self.mark_as_declared()

    def apply_resolved_versions(self, versions: dict[str, str], /):
        """Record what the build installed, keyed by canonical name.

        `versions` also carries the transitive packages uv resolved; only declared
        libraries are stamped, and one the build did not resolve is left as declared.
        """
        self.libs = [
            library.with_resolved_version(versions[library.name])
            if library.name in versions
            else library
            for library in self.libs
        ]

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


class StorageCredentials(ValueObject):
    """Object-store credentials issued for one job by the service that submitted it.

    Transient: carried to the worker in RAM, never persisted and never logged. The
    sandbox neither mints nor revokes them.
    """

    access_key: str
    secret_key: str


class Job(Entity):
    id: UUID | None = Field(default=None, frozen=True)
    # A tool path at session start submits without a session of its own.
    session_id: int | None = None
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
    # Held jobs are dispatched later, so the manager carries these until then.
    storage_credentials: StorageCredentials | None = None
    timeout: float | None = None
    # Crew subscribes to a channel of its own; this asks for the result to go there
    # instead of the shared one. The channel name is the sandbox's, not the caller's.
    reply_to_crew_channel: bool = False
    error: str | None = None
