"""Problems found in a plugin package, each tied to the part of the package it concerns."""

from collections.abc import Iterable
from dataclasses import dataclass

PACKAGE_LOC = "package"
CONTENTS_LOC = "contents"
SIGNATURE_LOC = "signature"
MANIFEST_LOC = "manifest"


@dataclass(frozen=True)
class Problem:
    """One rule a package breaks.

    `loc` says where: a dotted path with list indexes, prefixed by the part of the package
    it refers to -- `package`, `contents`, `signature` or `manifest` (for example
    `manifest.user_permissions[1].action`). A problem with one archive file uses
    `package.<path inside the archive>`.
    """

    loc: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"loc": self.loc, "message": self.message}


class PackageProblemsError(Exception):
    """Raised when a package or manifest breaks one or more rules; `problems` lists each one."""

    def __init__(self, problems: Iterable[Problem]):
        self.problems = tuple(problems)
        super().__init__(
            "; ".join(f"{problem.loc}: {problem.message}" for problem in self.problems)
        )


def format_loc(prefix: str, parts: Iterable[str | int]) -> str:
    """Join `prefix` and a validation location into `prefix.field[index].field` form."""
    loc = prefix
    for part in parts:
        loc += f"[{part}]" if isinstance(part, int) else f".{part}"
    return loc


def archive_file_loc(path: str) -> str:
    """Location of one file inside the package archive."""
    return f"{PACKAGE_LOC}.{path}"
