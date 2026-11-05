import tarfile
import zipfile
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Self

from foundation.schemas import Schema
from litestar.datastructures import UploadFile
from pydantic import ConfigDict, Field, field_validator, model_validator

from manager.domain.enums import JobStatus, VenvStatus, WheelStatus
from manager.domain.models import (
    SOURCE_ARCHIVE_SUFFIXES,
    WHEEL_SUFFIX,
    CustomLibrary,
    Library,
    StorageCredentials,
    Venv,
    Wheel,
)

__all__ = [
    "CustomLibraryCreateSchema",
    "CustomLibraryListSchema",
    "CustomLibraryRetrieveSchema",
    "ExecutionAcceptedSchema",
    "ExecutionSubmitSchema",
    "LibraryRetrieveSchema",
    "LibraryWriteSchema",
    "StorageCredentialsSchema",
    "VenvCreateSchema",
    "VenvListSchema",
    "VenvRetrieveSchema",
    "VenvUpdateSchema",
    "WheelRetrieveSchema",
    "WheelUploadSchema",
]


class LibraryWriteSchema(Schema):
    """A library as a client declares it."""

    name: str
    description: str | None = None
    specification: str = ""
    version: str | None = None
    is_custom: bool = False

    def to_domain(self) -> Library:
        return Library(
            name=self.name,
            description=self.description,
            specification=self.specification,
            version=self.version,
            is_custom=self.is_custom,
        )


class LibraryRetrieveSchema(Schema):
    name: str
    description: str | None = None
    specification: str
    version: str | None = None
    is_custom: bool = False

    @classmethod
    def from_domain(cls, library: Library) -> Self:
        return cls(
            name=library.name,
            description=library.description,
            specification=library.specification,
            version=library.version,
            is_custom=library.is_custom,
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


class StorageCredentialsSchema(Schema):
    """Object-store credentials the caller issued for this execution."""

    # Non-empty: a blank key would pass the fail-closed check below (a model is
    # always truthy) and fail against the object store inside the sandbox instead.
    access_key: str = Field(min_length=1)
    secret_key: str = Field(min_length=1)

    def to_domain(self) -> StorageCredentials:
        return StorageCredentials(access_key=self.access_key, secret_key=self.secret_key)


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
    # The sandbox never mints these: the caller issues them and hands them over.
    storage_credentials: StorageCredentialsSchema | None = None
    timeout: float | None = None
    # Asks for the result on crew's private result channel instead of the shared one.
    # A flag, not a channel name: the sandbox derives the name from its own setting, so a
    # caller cannot redirect results at another service's channel.
    reply_to_crew_channel: bool = False

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
    status: JobStatus


class WheelRetrieveSchema(Schema):
    """One version of a custom library, as it currently stands.

    Which of the two filenames is set says how the version got here: a source archive
    was uploaded and built, or a wheel was uploaded ready-made. Both are set once a
    build has run.
    """

    id: int
    # Known only once the version is `completed`: an upload reads it off the wheel's
    # name, a build off what it produced.
    version: str | None = None
    status: WheelStatus
    # Why the upload or the build failed, in the words of whatever refused it.
    error: str | None = None
    source_filename: str | None = None
    wheel_filename: str | None = None
    created_at: datetime

    @classmethod
    def from_domain(cls, wheel: Wheel) -> Self:
        return cls(
            id=wheel.id,
            version=wheel.version,
            status=wheel.status,
            error=wheel.error,
            source_filename=wheel.source_filename,
            wheel_filename=wheel.wheel_filename,
            created_at=wheel.created_at,
        )


class WheelUploadSchema(Schema):
    """A new version of a custom library: a built wheel, or a source archive to build."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    file: UploadFile

    @field_validator("file")
    @classmethod
    def validate_upload(cls, file: UploadFile) -> UploadFile:
        """Hold the upload to the format its name claims to be.

        The name is what decides how the file is treated -- a wheel is taken as
        finished, an archive is unpacked and built -- so a name disagreeing with the
        bytes would have the build read something other than what it was handed. A
        wheel is a zip with a prescribed layout, and only the zip part is checkable
        here; the layout is the build's business.

        Raises:
            ValueError: The name is neither a wheel nor a source archive, or the bytes
                are not the format the name gives.
        """
        name = PurePosixPath(file.filename or "").name.lower()
        if not name.endswith((WHEEL_SUFFIX, *SOURCE_ARCHIVE_SUFFIXES)):
            raise ValueError(
                f"'{file.filename}' is neither a wheel ({WHEEL_SUFFIX}) nor a source "
                f"archive ({', '.join(SOURCE_ARCHIVE_SUFFIXES)})."
            )

        if name.endswith((WHEEL_SUFFIX, ".zip")):
            is_expected_format, expected = zipfile.is_zipfile, "a zip archive"
        else:
            is_expected_format, expected = tarfile.is_tarfile, "a tar archive"

        try:
            file.file.seek(0)
            if not is_expected_format(file.file):
                raise ValueError(f"'{file.filename}' is not {expected}.")
        except (EOFError, OSError, tarfile.TarError, zipfile.BadZipFile) as error:
            # A truncated or corrupt archive makes the check raise rather than answer,
            # and here that is the answer: the bytes are not the format they claim.
            raise ValueError(f"'{file.filename}' is not {expected}.") from error
        finally:
            file.file.seek(0)
        return file


class CustomLibraryListSchema(Schema):
    count: int = Field(ge=0)
    limit: int = Field(ge=0)
    offset: int = Field(ge=0)
    next: str | None = None
    previous: str | None = None
    result: list["CustomLibraryRetrieveSchema"]


class CustomLibraryCreateSchema(WheelUploadSchema):
    """A new custom library, created from its first version.

    A wheel names the library at once; a source archive's distribution is not known
    until it builds, so the library it creates starts unnamed and takes the name its
    first successful build produces. The upload itself is validated exactly like any
    other version's.
    """


class CustomLibraryRetrieveSchema(Schema):
    id: int
    # As stored, which is the canonical spelling of what was sent, not what was sent.
    # Null until a wheel -- uploaded directly, or built from a source archive -- names
    # the library.
    name: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, library: CustomLibrary) -> Self:
        return cls(
            id=library.id,
            name=library.name,
            created_at=library.created_at,
            updated_at=library.updated_at,
        )
