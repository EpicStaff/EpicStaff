from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class FileListItem:
    """Single entry returned by list_(): a file or folder."""

    name: str
    type: Literal["file", "folder"]
    size: int
    modified: str | None
    is_empty: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileInfo:
    """Metadata returned by info()."""

    name: str
    path: str
    size: int
    content_type: str
    modified: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FolderInfo:
    """Metadata returned by info() for folders."""

    name: str
    path: str
    modified: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class UploadResult:
    """Raw result from a backend upload() call."""

    path: str
    size: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class FileUploadResult:
    """Result of uploading a single file (non-archive)."""

    type: Literal["file"]
    path: str
    size: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ArchiveUploadResult:
    """Result of uploading and extracting an archive."""

    type: Literal["archive"]
    extracted: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


UploadFileResult = FileUploadResult | ArchiveUploadResult


@dataclass(frozen=True, slots=True)
class TreeNode:
    name: str
    path: str
    type: Literal["file", "folder"]
    size: int
    modified: str | None
    children: (
        list["TreeNode"] | None
    )  # None for files, list for folders (possibly empty)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "type": self.type,
            "size": self.size,
            "modified": self.modified,
            "children": (
                [child.to_dict() for child in self.children]
                if self.children is not None
                else None
            ),
        }
