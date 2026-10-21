"""The `.esplugin` package format: fixed paths, caps, `CONTENTS.json`, and the archive reader.

One implementation of every package rule. `epicstaff-plugin validate` and `pack` use it, and
EpicStaff reads every upload through `read_package` (passing its own extraction guard).

A package is a zip holding `manifest.json`, `CONTENTS.json`, an optional
`CONTENTS.json.minisig`, the icon the manifest names, and -- per manifest section -- `spa/`,
`backend/` and `database/migrations/`. `CONTENTS.json` lists every other file with its size
and SHA-256, so signing that one file covers the whole package.
"""

import hashlib
import re
import stat
import zipfile
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, BinaryIO, Literal, Protocol
from xml.etree import ElementTree

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from epicstaff_plugin.contracts.manifest import MANIFEST_FILE_NAME, PluginManifest, parse_manifest
from epicstaff_plugin.json_documents import canonical_json, load_json_object
from epicstaff_plugin.paths import path_problem
from epicstaff_plugin.problems import (
    CONTENTS_LOC,
    MANIFEST_LOC,
    PACKAGE_LOC,
    SIGNATURE_LOC,
    PackageProblemsError,
    Problem,
    archive_file_loc,
    format_loc,
)
from epicstaff_plugin.requirements_lock import (
    MAX_REQUIREMENTS_LOCK_BYTES,
    REQUIREMENTS_LOCK_PATH,
    backend_lock_problems,
)
from epicstaff_plugin.signing import SignatureFile, SignatureFormatError

PACKAGE_EXTENSION = ".esplugin"
CONTENTS_FILE_NAME = "CONTENTS.json"
SIGNATURE_FILE_NAME = "CONTENTS.json.minisig"
CONTENTS_FORMAT = 1
ICON_MEDIA_TYPES = {"icon.svg": "image/svg+xml", "icon.png": "image/png"}

SPA_DIRECTORY = "spa/"
BACKEND_DIRECTORY = "backend/"
BACKEND_SOURCE_DIRECTORY = "backend/src/"
BACKEND_WHEELS_DIRECTORY = "backend/wheels/"
BACKEND_REQUIREMENTS = REQUIREMENTS_LOCK_PATH
DATABASE_DIRECTORY = "database/"
MIGRATION_PATTERN = re.compile(r"^database/migrations/([0-9]{3})_[a-z0-9][a-z0-9_]*\.sql$")

MAX_ENTRIES = 10_000
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
# Smaller files may compress better than that (text, padding); the uncompressed byte budget
# still bounds what they can expand to.
MIN_RATIO_CHECKED_BYTES = 1024 * 1024
MAX_SPA_FILES = 2000
MAX_SPA_BYTES = 50 * 1024 * 1024
# The plugin node holds a package's migrations in memory while it runs them.
MAX_MIGRATIONS_TOTAL_BYTES = 64 * 1024 * 1024
MAX_ICON_BYTES = 64 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
MAX_CONTENTS_BYTES = 16 * 1024 * 1024
MAX_SIGNATURE_BYTES = 4096

# Files read into memory while the archive streams, with the most each may hold.
_KEPT_FILE_LIMITS = {
    MANIFEST_FILE_NAME: MAX_MANIFEST_BYTES,
    CONTENTS_FILE_NAME: MAX_CONTENTS_BYTES,
    SIGNATURE_FILE_NAME: MAX_SIGNATURE_BYTES,
    BACKEND_REQUIREMENTS: MAX_REQUIREMENTS_LOCK_BYTES,
    **dict.fromkeys(ICON_MEDIA_TYPES, MAX_ICON_BYTES),
}
_UNLISTED_FILES = frozenset({CONTENTS_FILE_NAME, SIGNATURE_FILE_NAME})
_ALLOWED_COMPRESSION = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_UTF8_NAME_FLAG = 0x800
_ENCRYPTED_FLAG = 0x1
_UNIX_CREATOR = 3
_READ_CHUNK_BYTES = 1024 * 1024
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_XML_ENCODING_DECLARATION = re.compile(
    r"^\s*<\?xml[^>]*\bencoding\s*=\s*[\"']([^\"']+)", re.IGNORECASE
)
_CSS_URL = re.compile(r"url\(\s*[\"']?\s*([^\"')\s]*)", re.IGNORECASE)
# Errors zipfile raises for a damaged, encrypted or oddly compressed archive.
_ZIP_READ_ERRORS = (
    zipfile.BadZipFile,
    zlib.error,
    EOFError,
    NotImplementedError,
    RuntimeError,
    ValueError,
    OSError,
)


class ExtractionGuard(Protocol):
    """Bounds one archive read. Both methods raise `ValueError` once a cap is passed."""

    def account_entry(self) -> None: ...

    def account_bytes(self, n: int, name: str) -> None: ...


class ExtractionBudget:
    """The package caps on entries and uncompressed bytes, counted as the archive streams."""

    def __init__(
        self, *, max_entries: int = MAX_ENTRIES, max_total_bytes: int = MAX_UNCOMPRESSED_BYTES
    ):
        self.max_entries = max_entries
        self.max_total_bytes = max_total_bytes
        self.entries_seen = 0
        self.bytes_read = 0

    def account_entry(self) -> None:
        self.entries_seen += 1
        if self.entries_seen > self.max_entries:
            raise ValueError(f"the package has more than {self.max_entries} entries")

    def account_bytes(self, n: int, name: str) -> None:
        self.bytes_read += n
        if self.bytes_read > self.max_total_bytes:
            raise ValueError(
                f"'{name}' takes the package past {self.max_total_bytes} uncompressed bytes"
            )


@dataclass(frozen=True)
class PackageFile:
    """One file of a package, as `CONTENTS.json` describes it."""

    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ContentsSummary:
    """Counts shown when a SuperAdmin reviews a package."""

    spa_file_count: int
    spa_bytes: int
    wheel_count: int
    migration_count: int


@dataclass(frozen=True)
class PackageArchive:
    """A package that passed every rule of the format."""

    manifest: PluginManifest
    contents: bytes
    signature: str | None
    icon: bytes
    files: tuple[PackageFile, ...]
    summary: ContentsSummary

    @property
    def icon_media_type(self) -> str:
        return ICON_MEDIA_TYPES[self.manifest.icon]

    @property
    def spa_files(self) -> tuple[PackageFile, ...]:
        return tuple(file for file in self.files if file.path.startswith(SPA_DIRECTORY))


class _ContentsPart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class ContentsEntry(_ContentsPart):
    path: str
    sha256: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
    size: Annotated[int, Field(ge=0)]


class ContentsDocument(_ContentsPart):
    """The parsed `CONTENTS.json`."""

    format: Literal[1]
    plugin_id: Annotated[str, StringConstraints(max_length=64)]
    version: Annotated[str, StringConstraints(max_length=64)]
    files: list[ContentsEntry]


def build_contents(plugin_id: str, version: str, files: Iterable[PackageFile]) -> bytes:
    """Return the canonical `CONTENTS.json` bytes for a package's files."""
    return canonical_json(
        {
            "files": [
                {"path": file.path, "sha256": file.sha256, "size": file.size}
                for file in sorted(files, key=lambda file: file.path)
            ],
            "format": CONTENTS_FORMAT,
            "plugin_id": plugin_id,
            "version": version,
        }
    )


def parse_contents(raw: bytes) -> ContentsDocument:
    """Parse `CONTENTS.json`, which must be in canonical form with its files sorted by path.

    Raises:
        PackageProblemsError: Every problem found, located under `contents`.
    """
    if len(raw) > MAX_CONTENTS_BYTES:
        raise PackageProblemsError(
            [Problem(CONTENTS_LOC, f"is larger than {MAX_CONTENTS_BYTES} bytes")]
        )
    document = load_json_object(raw, CONTENTS_LOC, CONTENTS_FILE_NAME)
    try:
        contents = ContentsDocument.model_validate(document)
    except ValidationError as error:
        raise PackageProblemsError(
            Problem(format_loc(CONTENTS_LOC, detail["loc"]), detail["msg"])
            for detail in error.errors(include_url=False)
        ) from None
    problems = []
    if canonical_json(document) != raw:
        problems.append(
            Problem(CONTENTS_LOC, "is not in canonical form (sorted keys, no whitespace, UTF-8)")
        )
    paths = [entry.path for entry in contents.files]
    for index, path in enumerate(paths):
        loc = f"{CONTENTS_LOC}.files[{index}].path"
        if problem := path_problem(path):
            problems.append(Problem(loc, f"path {problem}"))
        elif path in _UNLISTED_FILES:
            problems.append(Problem(loc, f"{path} is never listed in CONTENTS.json"))
    if paths != sorted(paths):
        problems.append(Problem(f"{CONTENTS_LOC}.files", "are not sorted by path"))
    if len(set(paths)) != len(paths):
        problems.append(Problem(f"{CONTENTS_LOC}.files", "list a path more than once"))
    if problems:
        raise PackageProblemsError(problems)
    return contents


class PackagePaths:
    """The package paths seen so far, reporting each one that clashes with an earlier one.

    Two paths clash when they differ only in case, or when one is a folder of the other
    (`spa/a` and `spa/a/b.js`): no file system can hold both, so publishing would fail.
    Paths are compared without case, as a case-insensitive file system compares them.
    """

    def __init__(self):
        self._files: dict[str, str] = {}
        self._folders: dict[str, str] = {}

    def add(self, path: str) -> str | None:
        """Record `path` and return why it clashes with an earlier path, or None."""
        folded = path.casefold()
        if folded in self._files:
            return f"has the same name as {self._files[folded]!r} when case is ignored"
        if folded in self._folders:
            return f"is a file, but {self._folders[folded]!r} needs it to be a folder"
        segments = folded.split("/")
        folders = ["/".join(segments[:depth]) for depth in range(1, len(segments))]
        for folder in folders:
            if folder in self._files:
                return f"is inside {self._files[folder]!r}, which is a file"
        self._files[folded] = path
        for folder in folders:
            self._folders.setdefault(folder, path)
        return None


def path_set_problems(paths: Iterable[str]) -> list[Problem]:
    """Check each path's form and that no path clashes with another (see `PackagePaths`)."""
    problems = []
    seen = PackagePaths()
    for path in paths:
        if problem := path_problem(path):
            problems.append(Problem(PACKAGE_LOC, f"the path {path!r} {problem}"))
        elif clash := seen.add(path):
            problems.append(Problem(archive_file_loc(path), clash))
    return problems


def size_problems(files: Iterable[PackageFile]) -> list[Problem]:
    """Check the per-file, total and entry-count caps for files about to be packed."""
    problems = []
    files = list(files)
    if len(files) + len(_UNLISTED_FILES) > MAX_ENTRIES:
        problems.append(Problem(PACKAGE_LOC, f"would have more than {MAX_ENTRIES} entries"))
    for file in files:
        if file.size > MAX_FILE_BYTES:
            problems.append(
                Problem(archive_file_loc(file.path), f"is larger than {MAX_FILE_BYTES} bytes")
            )
    if sum(file.size for file in files) > MAX_UNCOMPRESSED_BYTES:
        problems.append(
            Problem(
                PACKAGE_LOC, f"would hold more than {MAX_UNCOMPRESSED_BYTES} bytes uncompressed"
            )
        )
    return problems


def layout_problems(
    manifest: PluginManifest,
    files: Mapping[str, PackageFile],
    icon: bytes | None,
    *,
    requirements_lock: bytes | None = None,
    check_spa: bool = True,
    require_sdk_pin: bool = True,
) -> list[Problem]:
    """Check that the files fit the fixed layout the manifest implies.

    `files` maps each path to its file, without `CONTENTS.json` and its signature. `icon` and
    `requirements_lock` are the contents of the icon the manifest names and of
    `backend/requirements.lock`, when present. `check_spa=False` skips the SPA checks, for a
    source directory validated without its built SPA; `require_sdk_pin=False` accepts a lock
    without `epicstaff-plugin`, for a source directory packed with `--local-wheel`.
    """
    problems = [
        Problem(archive_file_loc(path), problem)
        for path in sorted(files)
        if (problem := _placement_problem(path, manifest))
    ]
    if manifest.icon not in files:
        problems.append(
            Problem(f"{MANIFEST_LOC}.icon", f"names {manifest.icon}, which is not in the package")
        )
    elif icon is not None and (problem := icon_problem(manifest.icon, icon)):
        problems.append(Problem(archive_file_loc(manifest.icon), problem))
    if manifest.spa is not None and check_spa:
        problems.extend(_spa_problems(manifest, files))
    if manifest.backend is not None:
        problems.extend(_backend_problems(manifest, files))
        if requirements_lock is not None:
            problems.extend(
                backend_lock_problems(
                    requirements_lock,
                    [path for path in files if _is_wheel(path)],
                    require_sdk_pin=require_sdk_pin,
                )
            )
    if manifest.database is not None:
        problems.extend(_migration_problems(files))
    return problems


def summarize(files: Iterable[PackageFile]) -> ContentsSummary:
    files = list(files)
    spa_files = [file for file in files if file.path.startswith(SPA_DIRECTORY)]
    return ContentsSummary(
        spa_file_count=len(spa_files),
        spa_bytes=sum(file.size for file in spa_files),
        wheel_count=sum(1 for file in files if _is_wheel(file.path)),
        migration_count=sum(1 for file in files if MIGRATION_PATTERN.match(file.path)),
    )


def _placement_problem(path: str, manifest: PluginManifest) -> str | None:
    if path == MANIFEST_FILE_NAME:
        return None
    if path in ICON_MEDIA_TYPES:
        if path == manifest.icon:
            return None
        return f"is not the icon the manifest names ({manifest.icon})"
    if path.startswith(SPA_DIRECTORY):
        return (
            None
            if manifest.spa is not None
            else "is under spa/, but the manifest has no spa section"
        )
    if path.startswith(BACKEND_DIRECTORY):
        if manifest.backend is None:
            return "is under backend/, but the manifest has no backend section"
        if (
            path == BACKEND_REQUIREMENTS
            or path.startswith(BACKEND_SOURCE_DIRECTORY)
            or _is_wheel(path)
        ):
            return None
        return "is not backend/requirements.lock, a file under backend/src/ or a wheel in backend/wheels/"
    if path.startswith(DATABASE_DIRECTORY):
        if manifest.database is None:
            return "is under database/, but the manifest has no database section"
        if MIGRATION_PATTERN.match(path):
            return None
        return "is not a migration named database/migrations/NNN_<name>.sql"
    return "is not a file a plugin package may hold"


def _is_wheel(path: str) -> bool:
    name = path.removeprefix(BACKEND_WHEELS_DIRECTORY)
    return name != path and "/" not in name and name.endswith(".whl")


def _spa_problems(manifest: PluginManifest, files: Mapping[str, PackageFile]) -> list[Problem]:
    problems = []
    entry = SPA_DIRECTORY + manifest.spa.entry
    if entry not in files:
        problems.append(
            Problem(f"{MANIFEST_LOC}.spa.entry", f"names {entry}, which is not in the package")
        )
    spa_files = [file for path, file in files.items() if path.startswith(SPA_DIRECTORY)]
    if len(spa_files) > MAX_SPA_FILES:
        problems.append(Problem(f"{PACKAGE_LOC}.spa", f"holds more than {MAX_SPA_FILES} files"))
    if sum(file.size for file in spa_files) > MAX_SPA_BYTES:
        problems.append(Problem(f"{PACKAGE_LOC}.spa", f"holds more than {MAX_SPA_BYTES} bytes"))
    return problems


def _backend_problems(manifest: PluginManifest, files: Mapping[str, PackageFile]) -> list[Problem]:
    problems = []
    if BACKEND_REQUIREMENTS not in files:
        problems.append(Problem(archive_file_loc(BACKEND_REQUIREMENTS), "is missing"))
    module_path = manifest.backend.entrypoint.partition(":")[0].replace(".", "/")
    candidates = (
        f"{BACKEND_SOURCE_DIRECTORY}{module_path}.py",
        f"{BACKEND_SOURCE_DIRECTORY}{module_path}/__init__.py",
    )
    if not any(candidate in files for candidate in candidates):
        problems.append(
            Problem(
                f"{MANIFEST_LOC}.backend.entrypoint",
                f"names a module that is neither {candidates[0]} nor {candidates[1]}",
            )
        )
    return problems


def _migration_problems(files: Mapping[str, PackageFile]) -> list[Problem]:
    problems = []
    numbers: dict[str, str] = {}
    total_bytes = 0
    for path in sorted(files):
        if not (match := MIGRATION_PATTERN.match(path)):
            continue
        total_bytes += files[path].size
        number = match.group(1)
        if number in numbers:
            problems.append(
                Problem(archive_file_loc(path), f"has the same number as {numbers[number]}")
            )
        numbers[number] = path
    if total_bytes > MAX_MIGRATIONS_TOTAL_BYTES:
        problems.append(
            Problem(
                f"{PACKAGE_LOC}.database",
                f"holds more than {MAX_MIGRATIONS_TOTAL_BYTES} bytes of migrations",
            )
        )
    return problems


def icon_problem(name: str, data: bytes) -> str | None:
    """Return why an icon may not be used, or None. An SVG must be inert when rendered."""
    if len(data) > MAX_ICON_BYTES:
        return f"is larger than {MAX_ICON_BYTES} bytes"
    if name == "icon.png":
        return None if data.startswith(_PNG_SIGNATURE) else "is not a PNG image"
    return _svg_problem(data)


def _svg_problem(data: bytes) -> str | None:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "is not UTF-8"
    declared = _XML_ENCODING_DECLARATION.match(text)
    if declared and declared.group(1).lower().replace("_", "-") not in ("utf-8", "utf8"):
        return "declares an encoding other than UTF-8"
    lowered = text.lower()
    # Refused before parsing, so no entity can expand and no DTD is fetched.
    if "<!doctype" in lowered or "<!entity" in lowered:
        return "must not contain a DOCTYPE or entity declaration"
    if "<?xml-stylesheet" in lowered:
        return "must not reference a stylesheet"
    try:
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError as error:
        return f"is not well-formed XML ({error})"
    if root.tag not in ("svg", f"{{{_SVG_NAMESPACE}}}svg"):
        return "does not have an <svg> root element"
    for element in root.iter():
        tag = _local_name(element.tag).lower()
        if tag in ("script", "foreignobject"):
            return f"contains a <{_local_name(element.tag)}> element"
        if tag == "style" and _references_outside(element.text or ""):
            return "has a style that references an outside resource"
        for attribute, value in element.attrib.items():
            name = _local_name(attribute).lower()
            if name.startswith("on"):
                return f"has an event handler attribute ({_local_name(attribute)})"
            if name in ("href", "src") and not value.strip().startswith("#"):
                return f"references an outside resource ({_local_name(attribute)})"
            if _references_outside(value):
                return f"references an outside resource ({_local_name(attribute)})"
    return None


def _local_name(name: str) -> str:
    return name.rpartition("}")[2]


def _references_outside(css: str) -> bool:
    if "@import" in css.lower():
        return True
    return any(not target.startswith("#") for target in _CSS_URL.findall(css))


def read_package_file(
    file: str | Path | BinaryIO,
    guard: ExtractionGuard | None = None,
    *,
    ignore_signature: bool = False,
) -> PackageArchive:
    """Open a package file and check it with `read_package`.

    Raises:
        PackageProblemsError: The file is not a zip archive, or breaks a package rule.
    """
    try:
        archive = zipfile.ZipFile(file)
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        raise PackageProblemsError([Problem(PACKAGE_LOC, "is not a zip archive")]) from None
    with archive:
        return read_package(archive, guard, ignore_signature=ignore_signature)


def read_package(
    archive: zipfile.ZipFile,
    guard: ExtractionGuard | None = None,
    *,
    ignore_signature: bool = False,
) -> PackageArchive:
    """Check every package rule while streaming the archive once, and return what it holds.

    Each file is hashed as it streams; only the manifest, `CONTENTS.json`, the signature and
    the icon are kept in memory. `guard` bounds the read (default: the package caps).
    `ignore_signature=True` skips the signature file, for re-signing a package.

    Raises:
        PackageProblemsError: Every problem found. A cap passed while streaming, or a damaged
            archive, stops the read at once.
    """
    return _ArchiveReader(archive, guard or ExtractionBudget(), ignore_signature).read()


class _ArchiveReader:
    def __init__(self, archive: zipfile.ZipFile, guard: ExtractionGuard, ignore_signature: bool):
        self._archive = archive
        self._guard = guard
        self._ignore_signature = ignore_signature
        self._problems: list[Problem] = []
        self._files: dict[str, PackageFile] = {}
        self._kept: dict[str, bytes] = {}

    def read(self) -> PackageArchive:
        entries = self._archive.infolist()
        if len(entries) > MAX_ENTRIES:
            raise PackageProblemsError(
                [Problem(PACKAGE_LOC, f"has more than {MAX_ENTRIES} entries")]
            )
        seen = PackagePaths()
        for entry in entries:
            self._read_entry(entry, seen)
        if self._problems:
            raise PackageProblemsError(self._problems)

        manifest = self._parsed(MANIFEST_FILE_NAME, parse_manifest)
        contents = self._parsed(CONTENTS_FILE_NAME, parse_contents)
        signature = None if self._ignore_signature else self._signature_text()
        listed_files = {
            path: file for path, file in self._files.items() if path not in _UNLISTED_FILES
        }
        if contents is not None:
            self._problems.extend(_listing_problems(contents, listed_files))
        if manifest is not None and contents is not None:
            self._problems.extend(_identity_problems(contents, manifest))
        if manifest is not None:
            self._problems.extend(
                layout_problems(
                    manifest,
                    listed_files,
                    self._kept.get(manifest.icon),
                    requirements_lock=self._kept.get(BACKEND_REQUIREMENTS),
                )
            )
        if self._problems:
            raise PackageProblemsError(self._problems)
        return PackageArchive(
            manifest=manifest,
            contents=self._kept[CONTENTS_FILE_NAME],
            signature=signature,
            icon=self._kept[manifest.icon],
            files=tuple(listed_files[entry.path] for entry in contents.files),
            summary=summarize(listed_files.values()),
        )

    def _read_entry(self, entry: zipfile.ZipInfo, seen: PackagePaths) -> None:
        self._account(self._guard.account_entry)
        name = entry.filename
        if not name.isascii() and not entry.flag_bits & _UTF8_NAME_FLAG:
            self._problems.append(
                Problem(PACKAGE_LOC, f"the entry name {name!r} is not marked as UTF-8")
            )
            return
        if name.endswith("/"):
            return
        if problem := path_problem(name):
            self._problems.append(Problem(PACKAGE_LOC, f"the path {name!r} {problem}"))
            return
        loc = archive_file_loc(name)
        if clash := seen.add(name):
            self._problems.append(Problem(loc, clash))
            return
        if problem := _entry_problem(entry):
            self._problems.append(Problem(loc, problem))
            return
        keep_limit = _KEPT_FILE_LIMITS.get(name)
        if keep_limit is not None and entry.file_size > keep_limit:
            self._problems.append(Problem(loc, f"is larger than {keep_limit} bytes"))
            return
        self._stream(entry, keep=keep_limit is not None)

    def _stream(self, entry: zipfile.ZipInfo, *, keep: bool) -> None:
        digest = hashlib.sha256()
        size = 0
        chunks: list[bytes] = []
        try:
            with self._archive.open(entry) as member:
                while chunk := member.read(_READ_CHUNK_BYTES):
                    self._account(self._guard.account_bytes, len(chunk), entry.filename)
                    digest.update(chunk)
                    size += len(chunk)
                    if keep:
                        chunks.append(chunk)
        except PackageProblemsError:
            raise
        except _ZIP_READ_ERRORS as error:
            raise PackageProblemsError(
                [Problem(archive_file_loc(entry.filename), f"could not be read: {error}")]
            ) from None
        self._files[entry.filename] = PackageFile(
            path=entry.filename, size=size, sha256=digest.hexdigest()
        )
        if keep:
            self._kept[entry.filename] = b"".join(chunks)

    @staticmethod
    def _account(method, *arguments) -> None:
        try:
            method(*arguments)
        except ValueError as error:
            raise PackageProblemsError([Problem(PACKAGE_LOC, str(error))]) from None

    def _parsed(self, name: str, parse):
        raw = self._kept.get(name)
        if raw is None:
            self._problems.append(Problem(PACKAGE_LOC, f"{name} is missing"))
            return None
        try:
            return parse(raw)
        except PackageProblemsError as error:
            self._problems.extend(error.problems)
            return None

    def _signature_text(self) -> str | None:
        raw = self._kept.get(SIGNATURE_FILE_NAME)
        if raw is None:
            return None
        try:
            text = raw.decode("utf-8")
            SignatureFile.from_text(text)
        except UnicodeDecodeError:
            self._problems.append(Problem(SIGNATURE_LOC, f"{SIGNATURE_FILE_NAME} is not UTF-8"))
            return None
        except SignatureFormatError as error:
            self._problems.append(Problem(SIGNATURE_LOC, f"{SIGNATURE_FILE_NAME}: {error}"))
            return None
        return text


def _entry_problem(entry: zipfile.ZipInfo) -> str | None:
    if entry.create_system == _UNIX_CREATOR:
        file_type = stat.S_IFMT(entry.external_attr >> 16)
        if file_type == stat.S_IFLNK:
            return "is a symbolic link"
        if file_type not in (0, stat.S_IFREG):
            return "is not a regular file"
    if entry.flag_bits & _ENCRYPTED_FLAG:
        return "is encrypted"
    if entry.compress_type not in _ALLOWED_COMPRESSION:
        return "uses a compression method other than stored or deflate"
    if entry.file_size > MAX_FILE_BYTES:
        return f"is larger than {MAX_FILE_BYTES} bytes"
    if entry.file_size > MIN_RATIO_CHECKED_BYTES and entry.file_size > (
        MAX_COMPRESSION_RATIO * max(entry.compress_size, 1)
    ):
        return (
            f"is larger than {MIN_RATIO_CHECKED_BYTES} bytes and expands more than "
            f"{MAX_COMPRESSION_RATIO} times when uncompressed"
        )
    return None


def _listing_problems(
    contents: ContentsDocument, files: Mapping[str, PackageFile]
) -> list[Problem]:
    problems = []
    listed = set()
    for index, entry in enumerate(contents.files):
        listed.add(entry.path)
        loc = f"{CONTENTS_LOC}.files[{index}]"
        file = files.get(entry.path)
        if file is None:
            problems.append(Problem(loc, f"lists {entry.path}, which is not in the package"))
            continue
        if file.size != entry.size:
            problems.append(
                Problem(f"{loc}.size", f"is {entry.size}, but {entry.path} has {file.size} bytes")
            )
        if file.sha256 != entry.sha256:
            problems.append(Problem(f"{loc}.sha256", f"does not match {entry.path}"))
    problems.extend(
        Problem(archive_file_loc(path), "is not listed in CONTENTS.json")
        for path in sorted(files)
        if path not in listed
    )
    return problems


def _identity_problems(contents: ContentsDocument, manifest: PluginManifest) -> list[Problem]:
    problems = []
    if contents.plugin_id != manifest.id:
        problems.append(
            Problem(
                f"{CONTENTS_LOC}.plugin_id",
                f"is {contents.plugin_id!r}, but the manifest id is {manifest.id!r}",
            )
        )
    if contents.version != manifest.version:
        problems.append(
            Problem(
                f"{CONTENTS_LOC}.version",
                f"is {contents.version!r}, but the manifest version is {manifest.version!r}",
            )
        )
    return problems
