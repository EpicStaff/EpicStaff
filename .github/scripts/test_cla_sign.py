#!/usr/bin/env python3
"""Minimal standalone tests for cla_sign.py.

No pytest dependency — run directly:
    python .github/scripts/test_cla_sign.py

Only `requests` must be installed. The Google client libraries are stubbed in
`sys.modules` when they are missing, because the Drive helpers are replaced by
an in-memory signature store anyway.

Each test runs `cla_sign.main()` end to end against a fake GitHub API (served
through patched `requests.get/post/patch`) and an in-memory Drive signature
folder, then asserts on the `CLA` commit status the script posts, on the
tracking comment it writes and on the signatures stored.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))


def _stub_google_libraries() -> None:
    """Register empty Google client modules so cla_common imports without them."""
    try:
        import google.oauth2.service_account  # noqa: F401
        import googleapiclient.discovery
        import googleapiclient.http  # noqa: F401

        return
    except ImportError:
        pass

    stub_attributes = {
        "google": {},
        "google.oauth2": {},
        "google.oauth2.service_account": {"Credentials": object},
        "googleapiclient": {},
        "googleapiclient.discovery": {"build": None},
        "googleapiclient.http": {
            "MediaInMemoryUpload": object,
            "MediaIoBaseDownload": object,
        },
    }
    for module_name, attributes in stub_attributes.items():
        module = types.ModuleType(module_name)
        for attribute_name, value in attributes.items():
            setattr(module, attribute_name, value)
        sys.modules[module_name] = module


_stub_google_libraries()

import cla_sign

REPO = "EpicStaff/EpicStaff"
PR_NUMBER = 42
HEAD_SHA = "abc123head"
CLA_VERSION = "1.0.0"
CLA_HASH = "f" * 64
GITHUB_API = "https://api.github.com"

COMMENT_URL = f"https://github.com/{REPO}/pull/{PR_NUMBER}#issuecomment-99"

SIGNER = {"login": "alice", "id": 1001, "type": "User"}
OTHER_SIGNER = {"login": "bob", "id": 1002, "type": "User"}
OUTSIDER = {"login": "mallory", "id": 6666, "type": "User"}
CO_AUTHOR = {"login": "carol", "id": 1003, "type": "User"}
DEPENDABOT = {"login": "dependabot[bot]", "id": 49699333, "type": "Bot"}
RENOVATE = {"login": "renovate[bot]", "id": 29139614, "type": "Bot"}
EVIL_BOT = {"login": "evil[bot]", "id": 7777, "type": "Bot"}
USER_NAMED_LIKE_DEPENDABOT = {"login": "dependabot[bot]", "id": 8888, "type": "User"}


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


class FakeGitHub:
    """In-memory stand-in for the GitHub REST endpoints cla_sign.py calls."""

    def __init__(self, opener: dict[str, Any], commits: list[dict[str, Any]]) -> None:
        self.opener = opener
        self.commits = commits
        self.comments: list[dict[str, Any]] = []
        self.statuses: list[dict[str, Any]] = []

    def get(self, url: str, headers=None, params=None, timeout=None) -> FakeResponse:
        page = (params or {}).get("page", 1)
        if url == f"{GITHUB_API}/repos/{REPO}/pulls/{PR_NUMBER}":
            return FakeResponse({"head": {"sha": HEAD_SHA}, "user": self.opener})
        if url == f"{GITHUB_API}/repos/{REPO}/pulls/{PR_NUMBER}/commits":
            return FakeResponse(self.commits if page == 1 else [])
        if url == f"{GITHUB_API}/repos/{REPO}/issues/{PR_NUMBER}/comments":
            return FakeResponse(self.comments if page == 1 else [])
        raise AssertionError(f"Unexpected GET {url}")

    def post(self, url: str, headers=None, json=None, timeout=None) -> FakeResponse:
        if url == f"{GITHUB_API}/repos/{REPO}/statuses/{HEAD_SHA}":
            self.statuses.append(json)
            return FakeResponse({})
        if url == f"{GITHUB_API}/repos/{REPO}/issues/{PR_NUMBER}/comments":
            comment = {
                "id": len(self.comments) + 1,
                "body": json["body"],
                "html_url": f"https://github.com/{REPO}/pull/{PR_NUMBER}#issuecomment-1",
            }
            self.comments.append(comment)
            return FakeResponse(comment)
        raise AssertionError(f"Unexpected POST {url}")

    def patch(self, url: str, headers=None, json=None, timeout=None) -> FakeResponse:
        for comment in self.comments:
            if url == f"{GITHUB_API}/repos/{REPO}/issues/comments/{comment['id']}":
                comment["body"] = json["body"]
                return FakeResponse(comment)
        raise AssertionError(f"Unexpected PATCH {url}")


class FakeSignatureFolder:
    """In-memory stand-in for the Drive folder of the current CLA version."""

    def __init__(self, signed_users: list[dict[str, Any]]) -> None:
        self.signatures = {
            f"{user['login']}_{user['id']}.json": {"cla_sha256": CLA_HASH} for user in signed_users
        }

    def list_signature_filenames(self, service, folder_id: str) -> set[str]:
        return set(self.signatures)

    def get_signature(self, service, folder_id: str, filename: str) -> dict[str, Any] | None:
        return self.signatures.get(filename)

    def put_signature(self, service, folder_id: str, filename: str, payload: dict) -> None:
        self.signatures[filename] = payload


class RunResult:
    def __init__(self, exit_code: int, github: FakeGitHub, folder: FakeSignatureFolder) -> None:
        self.exit_code = exit_code
        self.signature_filenames = set(folder.signatures)
        self.state = github.statuses[-1]["state"]
        self.description = github.statuses[-1]["description"]
        self.comment = github.comments[-1]["body"]


def commit_by(author: dict[str, Any]) -> dict[str, Any]:
    """Return a PR commit whose git author email GitHub linked to `author`."""
    return {
        "author": author,
        "commit": {"author": {"name": author["login"], "email": "x@example.com"}},
    }


def run_cla_sign(
    *,
    opener: dict[str, Any],
    commit_authors: list[dict[str, Any]],
    signed_users: list[dict[str, Any]],
    allowlist: str | None = None,
    extra_commits: list[dict[str, Any]] | None = None,
    sign_comment_by: dict[str, Any] | None = None,
) -> RunResult:
    """Run cla_sign.main() for one event and return its verdict.

    By default the event is `pull_request_target`. With `sign_comment_by` it is
    an `issue_comment` in which that user posts the sign phrase.
    """
    commits = [commit_by(author) for author in commit_authors] + (extra_commits or [])
    github = FakeGitHub(opener, commits)
    folder = FakeSignatureFolder(signed_users)

    if sign_comment_by is None:
        event_name = "pull_request_target"
        event: dict[str, Any] = {"pull_request": {"number": PR_NUMBER, "user": opener}}
    else:
        event_name = "issue_comment"
        event = {
            "issue": {"number": PR_NUMBER, "pull_request": {}},
            "comment": {
                "body": cla_sign.SIGN_PHRASE,
                "user": sign_comment_by,
                "html_url": COMMENT_URL,
            },
        }

    with tempfile.TemporaryDirectory() as tmp:
        event_path = Path(tmp) / "event.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")

        environment = {
            "GITHUB_TOKEN": "test-token",
            "GITHUB_REPOSITORY": REPO,
            "GITHUB_EVENT_NAME": event_name,
            "GITHUB_EVENT_PATH": str(event_path),
            "CLA_GDRIVE_ROOT_ID": "root-folder",
        }
        if allowlist is not None:
            environment["CLA_ALLOWLIST"] = allowlist

        with (
            mock.patch.dict(os.environ, environment),
            mock.patch("requests.get", github.get),
            mock.patch("requests.post", github.post),
            mock.patch("requests.patch", github.patch),
            mock.patch.object(cla_sign, "parse_cla_version", return_value=CLA_VERSION),
            mock.patch.object(cla_sign, "cla_sha256", return_value=CLA_HASH),
            mock.patch.object(cla_sign, "drive_service", return_value=object()),
            mock.patch.object(cla_sign, "get_or_create_version_folder", return_value="folder"),
            mock.patch.object(
                cla_sign, "list_signature_filenames", folder.list_signature_filenames
            ),
            mock.patch.object(cla_sign, "get_signature", folder.get_signature),
            mock.patch.object(cla_sign, "put_signature", folder.put_signature),
        ):
            if allowlist is None:
                os.environ.pop("CLA_ALLOWLIST", None)
            exit_code = cla_sign.main()

    return RunResult(exit_code, github, folder)


class ClaSignTests(unittest.TestCase):
    def test_forged_dependabot_commit_from_unsigned_opener_fails(self) -> None:
        result = run_cla_sign(opener=OUTSIDER, commit_authors=[DEPENDABOT], signed_users=[SIGNER])

        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.state, "failure")
        self.assertIn("- @mallory", result.comment)

    def test_commits_attributed_to_signer_from_unsigned_opener_fails(self) -> None:
        result = run_cla_sign(opener=OUTSIDER, commit_authors=[SIGNER], signed_users=[SIGNER])

        self.assertEqual(result.state, "failure")
        self.assertIn("- @mallory", result.comment)
        self.assertNotIn("@alice", result.comment)

    def test_unsigned_co_author_fails_and_is_listed(self) -> None:
        result = run_cla_sign(
            opener=SIGNER, commit_authors=[SIGNER, CO_AUTHOR], signed_users=[SIGNER]
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("- @carol", result.comment)
        self.assertNotIn("@alice", result.comment)

    def test_bot_outside_allowlist_is_treated_as_author_and_fails(self) -> None:
        result = run_cla_sign(opener=SIGNER, commit_authors=[EVIL_BOT], signed_users=[SIGNER])

        self.assertEqual(result.state, "failure")
        self.assertIn("- @evil[bot]", result.comment)

    def test_dependabot_pull_request_passes(self) -> None:
        result = run_cla_sign(opener=DEPENDABOT, commit_authors=[DEPENDABOT], signed_users=[])

        self.assertEqual(result.state, "success")

    def test_signed_opener_and_signed_authors_pass(self) -> None:
        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[SIGNER, OTHER_SIGNER],
            signed_users=[SIGNER, OTHER_SIGNER],
        )

        self.assertEqual(result.state, "success")

    def test_unsigned_opener_who_is_also_author_is_listed_once(self) -> None:
        result = run_cla_sign(opener=OUTSIDER, commit_authors=[OUTSIDER], signed_users=[])

        self.assertEqual(result.state, "failure")
        self.assertEqual(result.comment.count("@mallory"), 1)

    def test_allowlist_env_override_exempts_listed_bot(self) -> None:
        result = run_cla_sign(
            opener=RENOVATE,
            commit_authors=[RENOVATE],
            signed_users=[],
            allowlist="renovate[bot]",
        )

        self.assertEqual(result.state, "success")

    def test_allowlist_env_override_replaces_default(self) -> None:
        result = run_cla_sign(
            opener=DEPENDABOT,
            commit_authors=[DEPENDABOT],
            signed_users=[],
            allowlist="renovate[bot]",
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("- @dependabot[bot]", result.comment)

    def test_empty_allowlist_env_falls_back_to_default(self) -> None:
        result = run_cla_sign(
            opener=DEPENDABOT, commit_authors=[DEPENDABOT], signed_users=[], allowlist="  "
        )

        self.assertEqual(result.state, "success")

    def test_allowlist_env_of_only_commas_falls_back_to_default(self) -> None:
        result = run_cla_sign(
            opener=DEPENDABOT, commit_authors=[DEPENDABOT], signed_users=[], allowlist=" , ,"
        )

        self.assertEqual(result.state, "success")

    def test_unresolved_commit_fails_even_with_allowlisted_opener(self) -> None:
        unlinked_commit = {
            "author": None,
            "commit": {"author": {"name": "ghost", "email": "g@example.com"}},
        }

        result = run_cla_sign(
            opener=DEPENDABOT,
            commit_authors=[DEPENDABOT],
            signed_users=[],
            extra_commits=[unlinked_commit],
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("ghost <g@example.com>", result.comment)

    def test_opener_signing_by_comment_records_signature_and_passes(self) -> None:
        result = run_cla_sign(
            opener=OUTSIDER,
            commit_authors=[OUTSIDER],
            signed_users=[],
            sign_comment_by=OUTSIDER,
        )

        self.assertEqual(result.state, "success")
        self.assertIn("mallory_6666.json", result.signature_filenames)

    def test_user_account_with_allowlisted_login_is_not_skipped(self) -> None:
        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[USER_NAMED_LIKE_DEPENDABOT],
            signed_users=[SIGNER],
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("- @dependabot[bot]", result.comment)

    def test_user_opener_with_allowlisted_login_must_sign(self) -> None:
        result = run_cla_sign(
            opener=USER_NAMED_LIKE_DEPENDABOT,
            commit_authors=[DEPENDABOT],
            signed_users=[],
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("- @dependabot[bot]", result.comment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
