import re
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID

from foundation.base import Entity, ValueObject
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name
from pydantic import Field, field_validator, model_validator

from manager.domain.enums import JobStatus, VenvStatus, WheelStatus
from manager.domain.types import LibraryString

__all__ = [
    "DEFAULT_SYSTEM_KEY",
    "SOURCE_ARCHIVE_SUFFIXES",
    "SYSTEM_VENV_LIBS",
    "WHEEL_SUFFIX",
    "CustomLibrary",
    "Job",
    "Library",
    "LibraryBuildState",
    "StorageCredentials",
    "Venv",
    "Wheel",
]

WHEEL_SUFFIX = ".whl"
SOURCE_ARCHIVE_SUFFIXES = (".tar.gz", ".tgz", ".zip")
DISTRIBUTION_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
DISTRIBUTION_NAME_PATTERN = rf"^{DISTRIBUTION_NAME}$"
# A distribution name, optionally followed by extras that are distribution names
# themselves: `requests`, `requests[socks]`, `requests[socks,security]`. Used with
# `fullmatch`, never anchored with `$`, which also matches before a trailing newline.
LIBRARY_NAME_RE = re.compile(
    rf"{DISTRIBUTION_NAME}(?:\[{DISTRIBUTION_NAME}(?:,{DISTRIBUTION_NAME})*\])?"
)
VERSION_PATTERN = r"^([1-9][0-9]*!)?(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*))*((a|b|rc)(0|[1-9][0-9]*))?(\.post(0|[1-9][0-9]*))?(\.dev(0|[1-9][0-9]*))?(\+[a-z0-9]+([-_\.][a-z0-9]+)*)?$"


class Library(ValueObject):
    """A package a venv declares, resolved from the index or from a custom library.

    `requirement` becomes one line of the requirements `uv pip compile` reads on
    stdin, so neither `name` nor `specification` may carry anything uv would read as
    a second line, an option (`-i`, `-r`, `-e`) or a path: `name` is a distribution
    name with optional extras, without markers, a specifier or a URL.
    """

    name: str
    description: str | None = None
    specification: str = ""
    version: str | None = Field(default=None, pattern=VERSION_PATTERN)
    is_custom: bool = False

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        # Checked before canonicalizing, so the refusal names what was sent. A regex,
        # not `canonicalize_name(validate=True)`: packaging 24 lets that accept a name
        # followed by a newline.
        if LIBRARY_NAME_RE.fullmatch(value) is None:
            raise ValueError(
                f"Library name {value!r} is not a package name. Use letters, digits and "
                "'.', '_' or '-' between them, optionally followed by extras in brackets, "
                "for example 'requests' or 'requests[socks,security]'; put a version in "
                "the specification."
            )
        return canonicalize_name(value)

    @field_validator("specification")
    @classmethod
    def validate_version_specification(cls, value: str) -> str:
        # `SpecifierSet` reads any whitespace around an operator as padding, a line
        # break included, so the break would reach uv inside the requirement line.
        if any(character.isspace() and character != " " for character in value):
            raise ValueError(
                f"Version specification {value!r} must not contain whitespace other than "
                "plain spaces: no line breaks, tabs or other space characters."
            )
        try:
            specifiers = SpecifierSet(value)
        except InvalidSpecifier as e:
            raise ValueError(f"Invalid version specification: '{value}'") from e
        # packaging skips an empty clause. uv refuses a leading or doubled comma, which
        # would only surface as a failed build, and accepts a trailing one; all three are
        # refused here so the rule stays one rule and the error comes at declaration.
        if value.strip() and any(not clause.strip() for clause in value.split(",")):
            raise ValueError(
                f"Version specification {value!r} has an empty clause: remove the leading, "
                "trailing or doubled comma, for example '>=1,<2'."
            )
        # Arbitrary equality takes any token as its version, `===/etc` and `=== -r/x`
        # included, so the requirement line would hand uv whatever follows it.
        if any(specifier.operator == "===" for specifier in specifiers):
            raise ValueError(
                f"Version specification {value!r} uses arbitrary equality ('==='); "
                "use '==' to pin a version, for example '==1.0'."
            )
        return value

    @model_validator(mode="after")
    def reject_extras_on_a_custom_library(self) -> "Library":
        """Refuse extras on a stored library.

        A stored library is looked up, guarded against deletion and pinned by its
        bare name, so `acme[extra]` would name a library nothing stores.

        Raises:
            ValueError: A custom library carries extras.
        """
        if self.is_custom and self.distribution_name != self.name:
            raise ValueError(
                f"Custom library {self.name!r} cannot take extras; "
                f"declare it as {self.distribution_name!r}."
            )
        return self

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
    def distribution_name(self) -> str:
        """The package itself, without extras: what uv resolves and pins."""
        return self.name.partition("[")[0]

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


# The venv code runs in when it names no venv: the shared fallback.
DEFAULT_SYSTEM_KEY = "default"

# The venvs the sandbox builds and owns itself, by the key producers send as
# `system_venv`. Exact pins: a built-in node's code is written against these versions,
# and nobody can change a system venv's libraries through the API.
SYSTEM_VENV_LIBS: dict[str, list[Library]] = {
    DEFAULT_SYSTEM_KEY: [],
    "file_extractor": [
        Library(name="pdfplumber", specification="==0.11.10"),
        Library(name="python-docx", specification="==1.2.0"),
    ],
    "audio_transcription": [
        Library(name="faster-whisper", specification="==1.2.1"),
        Library(name="pydub", specification="==0.25.1"),
        # faster-whisper up to 1.2.1 calls av.open(metadata_errors=...), a keyword
        # PyAV 19 removed.
        Library(name="av", specification="==18.1.1"),
    ],
    # Every library the built-in tools in shared/tools import: they all run here. A tool
    # that needs a new library gets it added to this list.
    "builtin_tools": [
        Library(name="beautifulsoup4", specification="==4.15.0"),
        Library(name="charset-normalizer", specification="==3.5.3"),
        Library(name="couchbase", specification="==4.7.0"),
        Library(name="httpx", specification="==0.28.1"),
        Library(name="hyperbrowser", specification="==1.15.6"),
        Library(name="jsonschema", specification="==4.26.0"),
        Library(name="langchain", specification="==1.5.2"),
        Library(name="langchain-community", specification="==0.4.2"),
        Library(name="langchain-litellm", specification="==0.10.0"),
        Library(name="litellm", specification="==1.100.5"),
        Library(name="markdownify", specification="==1.2.4"),
        Library(name="openai", specification="==2.54.0"),
        Library(name="psycopg[binary]", specification="==3.3.4"),
        Library(name="psycopg2-binary", specification="==2.9.13"),
        Library(name="pydantic", specification="==2.13.4"),
        Library(name="pymongo", specification="==4.20.1"),
        Library(name="pymysql", specification="==1.2.4"),
        # trafilatura imports urllib3's SOCKS support, which without PySocks warns on
        # stderr, and the agent reads any stderr as a failed tool call.
        Library(name="pysocks", specification="==1.7.1"),
        Library(name="qdrant-client", specification="==1.20.0"),
        Library(name="requests", specification="==2.34.2"),
        Library(name="scrapfly-sdk", specification="==1.0.0"),
        Library(name="sqlalchemy", specification="==2.1.8"),
        Library(name="sqlparse", specification="==0.6.0"),
        Library(name="trafilatura", specification="==2.4.0"),
    ],
}


class Venv(Entity):
    id: int | None = Field(default=None, frozen=True)
    # At most the 255 characters of its column, so a longer name is refused as invalid
    # instead of failing at the database.
    name: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9 _-]+$")
    libs: list[Library] = Field(default_factory=list)
    hash: str | None = None
    status: VenvStatus = VenvStatus.DECLARED
    error: str | None = None
    # Set on a venv the sandbox builds and owns itself, and None on one a client declared
    # for its tools or nodes. Found by this key, never by name: a name is something any
    # tenant can type.
    system_key: str | None = Field(default=None, frozen=True)
    # The namespace the venv's custom libraries are looked up in: the gateway passes an
    # opaque value per tenant, the sandbox only compares it. None for a system venv.
    scope: str | None = Field(default=None, min_length=1, max_length=255)
    # Assigned by the database, never by the domain: unset until the venv is stored.
    created_at: datetime | None = Field(default=None, frozen=True)
    updated_at: datetime | None = Field(default=None, frozen=True)

    @field_validator("libs")
    @classmethod
    def reject_repeated_libraries(cls, value: list[Library]) -> list[Library]:
        """Reject a library declared twice, whatever spelling each entry used.

        One entry per package: a build stamps the version it installed by package
        name, so two entries would leave it unclear which one holds it, and each
        would carry its own specification for the same package. Names reach here
        canonicalized, so `Pydantic` and `pydantic` count as the same package.
        Extras do not make another package: `requests` next to `requests[socks]` is
        refused, and the two are declared as one entry, `requests[socks]`.

        Raises:
            ValueError: Some package is declared more than once.
        """
        seen: set[str] = set()
        for library in value:
            if library.distribution_name in seen:
                raise ValueError(
                    f"Library '{library.distribution_name}' is declared more than once."
                )
            seen.add(library.distribution_name)
        return value

    def rename(self, value: str, /):
        self.name = value

    def set_libs(self, value: list[Library], /):
        self.libs = value
        self.mark_as_declared()

    def set_scope(self, value: str, /):
        self.scope = value

    def apply_resolved_versions(self, versions: dict[str, str], /):
        """Record what the build installed, keyed by canonical name.

        `versions` also carries the transitive packages uv resolved; only declared
        libraries are stamped, and one the build did not resolve is left as declared.
        A lock pins the package, not its extras, so `requests[socks]` is looked up as
        `requests`.
        """
        self.libs = [
            library.with_resolved_version(versions[library.distribution_name])
            if library.distribution_name in versions
            else library
            for library in self.libs
        ]

    def uses_custom_library(self, name: str, /) -> bool:
        """Whether this venv names that stored library at all.

        What keeps the library itself from being deleted: the venv would otherwise
        name a library that is gone, and fail on its next build over a change its
        author never made. An entry carrying the same name without the marking is a
        package index lookup and says nothing about the stored library.

        Args:
            name: The library's name as stored, which is already canonical.
        """
        return any(library.is_custom and library.name == name for library in self.libs)

    def pins_custom_library(self, name: str, version: str, /) -> bool:
        """Whether this venv holds that exact version of that stored library.

        Only a built venv pins anything: the version is written onto the entry by the
        build. Until then the entry carries a specification, which is a range the build
        has not yet chosen from, and so claims no single version.

        Args:
            name: The library's name as stored, which is already canonical.
            version: The exact version to ask about.
        """
        return any(
            library.is_custom and library.name == name and library.version == version
            for library in self.libs
        )

    def mark_as_declared(self):
        self.error = None
        self.status = VenvStatus.DECLARED

    def mark_as_waiting(self):
        self.error = None
        self.status = VenvStatus.WAITING

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
    # Actions allowed on the allowed paths outside `own_paths`; None means not narrowed.
    shared_actions: list[str] | None = None
    # The run's own folders, where every action is allowed.
    own_paths: list[str] = Field(default_factory=list)


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
    # Wall-clock seconds when the job was handed to the worker queue; never set while
    # it is held.
    queued_at: float | None = None


class CustomLibrary(Entity):
    """A library whose distributions this service stores itself, rather than
    resolving them from a package index.

    Its versions are the `Wheel` rows pointing at it.
    """

    id: int | None = Field(default=None, frozen=True)
    # None until a wheel -- uploaded directly, or built from a source archive -- names
    # the library; `assign_name` is then the only way it ever changes, so a rename can
    # never desync it from the wheels already stored under it. Checked before
    # `normalize_name` runs, so the refusal names what was sent.
    name: str | None = Field(default=None, min_length=1, pattern=DISTRIBUTION_NAME_PATTERN)
    # Deletion is a mark, not a statement: the artifacts in the object store outlive
    # the call, and a background task removes them and the row afterwards.
    is_deleted: bool = False
    # The namespace the name is unique in, the same opaque value a venv carries.
    scope: str | None = Field(default=None, min_length=1, max_length=255)
    # Assigned by the database, never by the domain: unset until the library is stored.
    created_at: datetime | None = Field(default=None, frozen=True)
    updated_at: datetime | None = Field(default=None, frozen=True)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        """Hold the name to the spelling a package index would use, so that `Pydantic`
        and `pydantic` cannot both be stored as separate libraries."""
        return canonicalize_name(value) if value is not None else None

    def assign_name(self, value: str, /):
        """Name the library for the first time, from the wheel that defines it.

        Raises:
            ValueError: The library already has a name.
        """
        if self.name is not None:
            raise ValueError("This library already has a name.")
        self.name = value

    def set_scope(self, value: str, /):
        self.scope = value

    def mark_as_deleted(self):
        self.is_deleted = True


class Wheel(Entity):
    """One version of a `CustomLibrary`, and the files it is built from and into.

    A client uploads either a built wheel, which is complete on arrival, or a source
    archive, which a build turns into one. `source_filename` and `wheel_filename` are
    what the upload and the build were called; the keys they are stored under are
    derived from the ids, never from those names.
    """

    id: int | None = Field(default=None, frozen=True)
    library_id: int
    # The archive a build turns into a wheel. Unset when a built wheel was uploaded.
    source_filename: str | None = None
    # The wheel itself, uploaded or built. Unset until a build produces one.
    wheel_filename: str | None = None
    # Of the uploaded file, whichever of the two it was. The same source must not be
    # uploaded to one library twice, and this is what says two uploads are the same.
    upload_sha256: str
    version: str | None = None
    status: WheelStatus = WheelStatus.DECLARED
    error: str | None = None
    is_deleted: bool = False
    # Assigned by the database, never by the domain: unset until the wheel is stored.
    created_at: datetime | None = Field(default=None, frozen=True)

    @model_validator(mode="after")
    def require_a_file(self) -> "Wheel":
        """Reject a wheel that stands for no file at all.

        Every row exists because something was uploaded, so one of the two names is
        always set; neither being set means the row describes nothing.

        Raises:
            ValueError: Neither a source archive nor a wheel is named.
        """
        if self.source_filename is None and self.wheel_filename is None:
            raise ValueError("A wheel must name a source archive, a wheel file, or both.")
        return self

    @property
    def source_key(self) -> str | None:
        """Where the source archive is stored, or `None` when there is none."""
        return self._key("source", self.source_filename)

    @property
    def wheel_key(self) -> str | None:
        """Where the wheel is stored, or `None` when none has been produced yet."""
        return self._key("wheel", self.wheel_filename)

    def _key(self, kind: str, filename: str | None) -> str | None:
        """Build the object-store key for one of this wheel's files.

        The name a client uploaded is reduced to its last component: it reaches here
        unchecked, and a key is a path, so `../` in it would otherwise address an
        object belonging to another library.
        """
        if filename is None:
            return None
        return f"{self.library_id}/{self.id}/{kind}/{PurePosixPath(filename).name}"

    def mark_as_declared(self):
        self.error = None
        self.status = WheelStatus.DECLARED

    def mark_as_processing(self):
        self.error = None
        self.status = WheelStatus.PROCESSING

    def mark_as_completed(self, version: str, wheel_filename: str):
        self.error = None
        self.wheel_filename = wheel_filename
        self.version = version
        self.status = WheelStatus.COMPLETED

    def mark_as_failed(self, error: Exception):
        self.error = str(error)
        self.status = WheelStatus.FAILED

    def mark_as_deleted(self):
        self.is_deleted = True


class LibraryBuildState(ValueObject):
    """Where a `CustomLibrary`'s versions stand, taken together.

    Derived from its wheels rather than stored: see `summarize_wheels`. No status at
    all means the library holds no version, and `error` belongs to the failed one.
    """

    status: WheelStatus | None = None
    error: str | None = None
