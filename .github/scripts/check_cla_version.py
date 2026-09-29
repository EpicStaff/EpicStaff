#!/usr/bin/env python3
"""Fail a pull request that edits CLA.md without raising the version on line 1.

Signatures live in a per-version Google Drive folder (``v1.0.0``) and each
stored signature records a ``cla_sha256`` of the document text. cla_sign.py
rejects a signature whose stored hash no longer matches CLA.md, so editing
CLA.md without bumping the version does not merely leave stale signatures -- it
silently invalidates every existing one, and each contributor's re-signature
OVERWRITES their old file in the SAME version folder. The record of what they
originally agreed to is destroyed, and two contributors filed under "v1.0.0"
can have agreed to different text. The version bump is what keeps one version
folder holding exactly one document.

Standard library only, so the workflow needs no pip install step.

Reads two env vars:
    CLA_BASE_SHA  -- the pull request base commit
    CLA_HEAD_SHA  -- the pull request head commit

Exits 0 when CLA.md is untouched, when CLA.md is newly added, or when the head
version is strictly greater than the base version. Exits 1 otherwise.
"""

from __future__ import annotations

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(__file__))

from cla_version import parse_version_from_text, version_tuple  # noqa: E402

CLA_PATH = "CLA.md"


def run_git(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
    )


def cla_changed(base_sha: str, head_sha: str) -> bool:
    """True if this pull request itself touched CLA.md.

    Three dots, not two: diff from the merge base, so a CLA.md change that
    arrived via a merge from main is not attributed to this pull request.
    """
    result = run_git(
        ["diff", "--name-only", f"{base_sha}...{head_sha}", "--", CLA_PATH]
    )
    if result.returncode != 0:
        print(
            f"::error::git diff {base_sha}...{head_sha} failed: "
            f"{result.stderr.strip()}",
            file=sys.stderr,
        )
        raise SystemExit(1)

    return bool(result.stdout.strip())


def base_cla_text(base_sha: str) -> str | None:
    """CLA.md as it existed at the base commit, or None if it did not exist there.

    Only a path that `git ls-tree` confirms is absent from the base commit
    returns None. Any other `git show` failure -- an unreadable object, a base
    commit that is not in the clone -- is reported and exits 1. A guard that
    silently passes on an unexplained git failure is worse than no guard.
    """
    result = run_git(["show", f"{base_sha}:{CLA_PATH}"])
    if result.returncode == 0:
        return result.stdout

    listed = run_git(["ls-tree", "--name-only", base_sha, "--", CLA_PATH])
    if listed.returncode == 0 and not listed.stdout.strip():
        return None

    print(
        f"::error::Could not read {CLA_PATH} at the base commit {base_sha}, and "
        f"could not confirm that it is simply absent there, so this check "
        f"cannot tell whether the CLA version was bumped. Refusing to pass. "
        f"git show said: {result.stderr.strip()}",
        file=sys.stderr,
    )
    if listed.returncode != 0:
        print(
            f"::error::git ls-tree {base_sha} also failed: {listed.stderr.strip()}",
            file=sys.stderr,
        )
    raise SystemExit(1)


def report_failure(base_version: str, head_version: str, lowered: bool) -> None:
    print(
        f"::error::CLA.md changed in this pull request but its version was not "
        f"raised. Line 1 still has to move above VERSION {base_version}.",
        file=sys.stderr,
    )
    if lowered:
        print(
            f"::error::Line 1 points at VERSION {head_version}, which is LOWER "
            f"than the base version {base_version}. That reuses a Drive folder "
            f"(v{head_version}) that already holds signatures for a different "
            f"document.",
            file=sys.stderr,
        )
    else:
        print(
            f"::error::Line 1 of CLA.md still says VERSION {head_version}, the "
            f"same version the base commit has.",
            file=sys.stderr,
        )
    print(
        "::error::Raise the version on line 1 of CLA.md (e.g. VERSION "
        f"{next_patch(base_version)}). Signatures are stored in a Drive folder "
        f"named after the version (v{base_version}), and each one records a "
        "sha256 of the document text. Changing the text without bumping the "
        "version silently invalidates every existing signature, and each "
        "contributor's re-signature overwrites their old file in that same "
        "folder -- destroying the record of what they originally agreed to and "
        "leaving one version folder holding two different documents. Bumping "
        "the version is what makes everyone re-sign and what keeps each "
        "version folder holding exactly one document.",
        file=sys.stderr,
    )


def next_patch(version: str) -> str:
    major, minor, patch = version_tuple(version)

    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    base_sha = os.environ.get("CLA_BASE_SHA")
    head_sha = os.environ.get("CLA_HEAD_SHA")

    missing = [
        name
        for name, value in (("CLA_BASE_SHA", base_sha), ("CLA_HEAD_SHA", head_sha))
        if not value
    ]
    if missing:
        print(
            f"::error::{', '.join(missing)} env var(s) not set. This script needs "
            "the pull request base and head commits to tell whether CLA.md "
            "changed.",
            file=sys.stderr,
        )
        return 1

    assert base_sha and head_sha  # for type checkers; `missing` already guarded

    if not cla_changed(base_sha, head_sha):
        print(f"{CLA_PATH} unchanged in this pull request, nothing to check.")
        return 0

    base_text = base_cla_text(base_sha)
    if base_text is None:
        print(
            f"{CLA_PATH} does not exist at the base commit {base_sha} -- it is "
            "new in this pull request, so there is no version to bump from."
        )
        return 0

    base_version = parse_version_from_text(base_text, source=f"{base_sha}:{CLA_PATH}")

    with open(CLA_PATH, "r", encoding="utf-8") as cla_file:
        head_first_line = cla_file.readline()

    head_version = parse_version_from_text(head_first_line, source=CLA_PATH)

    if version_tuple(head_version) > version_tuple(base_version):
        print(
            f"{CLA_PATH} changed and the version was raised: {base_version} -> {head_version}"
        )
        return 0

    report_failure(
        base_version,
        head_version,
        lowered=version_tuple(head_version) < version_tuple(base_version),
    )

    return 1


if __name__ == "__main__":
    sys.exit(main())
