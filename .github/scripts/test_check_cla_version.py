#!/usr/bin/env python3
"""Minimal standalone tests for check_cla_version.py.

No pytest dependency — run directly:
    python .github/scripts/test_check_cla_version.py

Each test builds a real throwaway git repository in a tempdir (base commit on
`main`, a feature branch on top) and runs the script as a subprocess with
CLA_BASE_SHA / CLA_HEAD_SHA pointing at those commits, so the three-dot diff
and the `git show BASE:CLA.md` read are exercised for real.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "check_cla_version.py"

BASE_CLA = """\
# INDIVIDUAL CONTRIBUTOR LICENSE AGREEMENT ("ICLA") - VERSION 1.0.0, 10 June 2026

Effective as of the date of acceptance by the Contributor.
"""


def heading(version: str) -> str:
    return (
        f'# INDIVIDUAL CONTRIBUTOR LICENSE AGREEMENT ("ICLA") - VERSION {version}, '
        "10 June 2026\n"
    )


def git(repo: Path, *args: str) -> str:
    """Run git in `repo` with signing off, raising on failure."""
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed: {result.stderr}")

    return result.stdout.strip()


class ScenarioResult:
    def __init__(self, returncode: int, stdout: str, stderr: str) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_scenario(
    base_cla: str | None,
    head_cla: str | None,
    *,
    set_base_env: bool = True,
    set_head_env: bool = True,
    base_sha_override: str | None = None,
    corrupt_base_blob: bool = False,
) -> ScenarioResult:
    """Build a repo with `base_cla` at base and `head_cla` at head, run the script.

    `None` for either side means CLA.md does not exist at that commit. When
    `head_cla` equals `base_cla` the head commit touches an unrelated file
    instead, which is the "CLA.md untouched" case.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)

        git(repo, "init", "--initial-branch=main", ".")
        git(repo, "config", "user.email", "test@example.com")
        git(repo, "config", "user.name", "CLA Version Test")

        (repo / "README.md").write_text("base\n", encoding="utf-8")
        if base_cla is not None:
            (repo / "CLA.md").write_text(base_cla, encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "base")
        base_sha = git(repo, "rev-parse", "HEAD")

        git(repo, "checkout", "-b", "feature")
        if head_cla is None:
            (repo / "CLA.md").unlink(missing_ok=True)
            (repo / "README.md").write_text("head\n", encoding="utf-8")
        elif head_cla == base_cla:
            (repo / "README.md").write_text("head\n", encoding="utf-8")
        else:
            (repo / "CLA.md").write_text(head_cla, encoding="utf-8")
        git(repo, "add", "-A")
        git(repo, "commit", "-m", "head")
        head_sha = git(repo, "rev-parse", "HEAD")

        if corrupt_base_blob:
            # Delete the loose object holding CLA.md as it was at base. The
            # commit and its tree stay readable -- `git diff --name-only` only
            # needs names and still succeeds -- but `git show BASE:CLA.md` then
            # fails on a path that genuinely exists at base. That is the
            # failure mode the "is it simply absent?" check has to catch.
            blob = git(repo, "rev-parse", f"{base_sha}:CLA.md")
            blob_path = repo / ".git" / "objects" / blob[:2] / blob[2:]
            # git writes loose objects read-only, which Windows enforces on
            # unlink; POSIX only checks the directory, so this is a no-op there.
            blob_path.chmod(stat.S_IWRITE | stat.S_IREAD)
            blob_path.unlink()

        env = dict(os.environ)
        env.pop("CLA_BASE_SHA", None)
        env.pop("CLA_HEAD_SHA", None)
        if set_base_env:
            env["CLA_BASE_SHA"] = base_sha_override or base_sha
        if set_head_env:
            env["CLA_HEAD_SHA"] = head_sha

        result = subprocess.run(
            [sys.executable, str(SCRIPT)],
            cwd=repo,
            env=env,
            capture_output=True,
            text=True,
        )

        return ScenarioResult(result.returncode, result.stdout, result.stderr)


class CheckClaVersionTests(unittest.TestCase):
    def test_cla_untouched_passes(self) -> None:
        result = run_scenario(BASE_CLA, BASE_CLA)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("unchanged", result.stdout)

    def test_patch_bump_passes(self) -> None:
        head = heading("1.0.1") + "\nNew clause.\n"
        result = run_scenario(BASE_CLA, head)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("1.0.0", result.stdout)
        self.assertIn("1.0.1", result.stdout)

    def test_minor_bump_passes(self) -> None:
        head = heading("1.1.0") + "\nNew clause.\n"
        result = run_scenario(BASE_CLA, head)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("1.1.0", result.stdout)

    def test_major_bump_passes(self) -> None:
        head = heading("2.0.0") + "\nNew clause.\n"
        result = run_scenario(BASE_CLA, head)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("2.0.0", result.stdout)

    def test_same_version_fails(self) -> None:
        head = heading("1.0.0") + "\nSneaky new clause.\n"
        result = run_scenario(BASE_CLA, head)

        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::", result.stderr)
        self.assertIn("1.0.0", result.stderr)
        # The message has to name the file and line the contributor must edit.
        self.assertIn("line 1 of CLA.md", result.stderr)
        # ...and why it matters, so nobody has to go read the script.
        self.assertIn("re-sign", result.stderr)

    def test_lowered_version_fails_with_its_own_message(self) -> None:
        head = heading("0.9.0") + "\nRolled back clause.\n"
        result = run_scenario(BASE_CLA, head)

        self.assertEqual(result.returncode, 1)
        self.assertIn("LOWER", result.stderr)
        self.assertIn("v0.9.0", result.stderr)

    def test_new_cla_file_at_head_passes(self) -> None:
        result = run_scenario(None, BASE_CLA)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("new in this pull request", result.stdout)

    def test_bump_alone_with_no_other_text_change_passes(self) -> None:
        head = BASE_CLA.replace("VERSION 1.0.0", "VERSION 1.0.1")
        result = run_scenario(BASE_CLA, head)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("1.0.1", result.stdout)

    def test_unreachable_base_sha_fails_instead_of_passing(self) -> None:
        """A base SHA that is well-formed but not in the repo must not be
        mistaken for "CLA.md is new in this pull request" and waved through.
        An unexplained git failure has to fail the check, not pass it."""
        result = run_scenario(
            BASE_CLA,
            heading("1.0.0") + "\nSneaky new clause.\n",
            base_sha_override="0" * 40,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("::error::", result.stderr)
        self.assertNotIn("new in this pull request", result.stdout)
        self.assertNotIn("new in this pull request", result.stderr)

    def test_unreadable_base_cla_fails_instead_of_passing(self) -> None:
        """CLA.md exists at base but its object is unreadable. The script must
        not read that `git show` failure as "the file is new in this pull
        request" and exit 0 -- a guard that silently passes is worse than no
        guard."""
        result = run_scenario(
            BASE_CLA,
            heading("1.0.0") + "\nSneaky new clause.\n",
            corrupt_base_blob=True,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("::error::", result.stderr)
        self.assertIn("could not confirm that it is simply absent", result.stderr)
        # git's own reason has to reach the log, not be swallowed.
        self.assertIn("bad object", result.stderr)
        self.assertNotIn("new in this pull request", result.stdout)

    def test_missing_base_env_var_fails_clearly(self) -> None:
        result = run_scenario(BASE_CLA, BASE_CLA, set_base_env=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLA_BASE_SHA", result.stderr)

    def test_missing_head_env_var_fails_clearly(self) -> None:
        result = run_scenario(BASE_CLA, BASE_CLA, set_head_env=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CLA_HEAD_SHA", result.stderr)


if __name__ == "__main__":
    unittest.main()
