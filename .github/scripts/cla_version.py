"""Dependency-free helpers for reading the CLA version and document hash.

Split out of cla_common.py on purpose: cla_common imports ``requests``, the
Google auth libraries and the Drive client at module level, and the version
guard (check_cla_version.py) must be able to read one line of CLA.md without
installing any of that. Everything here is standard library only.

Why the version matters: signatures live in a per-version Google Drive folder
(``v1.0.0``) and each stored signature records a ``cla_sha256`` of the document
text. cla_sign.py rejects a signature whose stored hash no longer matches
CLA.md, so editing CLA.md without bumping the version silently invalidates
every existing signature -- and each contributor's re-signature overwrites
their old file in the SAME version folder, destroying the record of what they
originally agreed to. Bumping the version is what keeps one version folder
holding exactly one document.
"""

from __future__ import annotations

import hashlib
import re

_VERSION_RE = re.compile(r"VERSION\s+(\d+\.\d+\.\d+)")


def parse_version_from_text(text: str, source: str = "CLA.md") -> str:
    """Extract the CLA version (e.g. "1.0.0") from the first line of `text`.

    Takes the document contents rather than a path so callers can parse a
    revision read out of git (``git show BASE:CLA.md``) as well as a file on
    disk. `source` only names the origin in the error message.
    """
    first_line = text.split("\n", 1)[0]

    match = _VERSION_RE.search(first_line)
    if not match:
        raise ValueError(
            f"Could not find CLA version in first line of {source!r}: {first_line!r}"
        )

    return match.group(1)


def parse_cla_version(path: str = "CLA.md") -> str:
    """Extract the CLA version (e.g. "1.0.0") from the CLA.md heading."""
    with open(path, "r", encoding="utf-8") as cla_file:
        first_line = cla_file.readline()

    return parse_version_from_text(first_line, source=path)


def version_tuple(version: str) -> tuple[int, int, int]:
    """Turn "1.2.3" into (1, 2, 3) so two versions can be compared."""
    major, minor, patch = version.split(".")

    return (int(major), int(minor), int(patch))


def cla_sha256(path: str = "CLA.md") -> str:
    """Return the sha256 hex digest of CLA.md with line endings normalized to \\n."""
    with open(path, "rb") as cla_file:
        raw_bytes = cla_file.read()

    text = raw_bytes.decode("utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
