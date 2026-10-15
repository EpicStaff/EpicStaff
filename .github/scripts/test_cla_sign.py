#!/usr/bin/env python3
"""Minimal standalone tests for cla_sign.py.

No pytest dependency — run directly:
    python .github/scripts/test_cla_sign.py

Only `requests` must be installed. The Google client libraries are stubbed in
`sys.modules` when they are missing, because the Drive helpers are replaced by
an in-memory signature store anyway.

Each test runs `cla_sign.main()` end to end against a fake GitHub API (served
through patched `requests.get/post/patch`, including the user lookups used for
`Co-authored-by:` trailers) and an in-memory Drive signature folder, then
asserts on the `CLA` commit status the script posts, on the tracking comment it
writes and on the signatures stored.
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

import requests

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

import cla_common
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
RENAMED_USER = {"login": "dave-new", "id": 1004, "type": "User"}

CAROL_NOREPLY = "1003+carol@users.noreply.github.com"


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")


class FakeGitHub:
    """In-memory stand-in for the GitHub REST endpoints cla_sign.py calls."""

    def __init__(
        self,
        opener: dict[str, Any],
        commits: list[dict[str, Any]],
        accounts: list[dict[str, Any]],
        server_error_urls: set[str],
    ) -> None:
        self.opener = opener
        self.commits = commits
        self.accounts = accounts
        self.server_error_urls = server_error_urls
        self.comments: list[dict[str, Any]] = []
        self.statuses: list[dict[str, Any]] = []
        self.requested_urls: list[str] = []

    def get(self, url: str, headers=None, params=None, timeout=None) -> FakeResponse:
        self.requested_urls.append(url)
        page = (params or {}).get("page", 1)
        if url in self.server_error_urls:
            return FakeResponse({"message": "Server Error"}, status_code=500)
        for account in self.accounts:
            # GitHub matches logins case-insensitively.
            if url == f"{GITHUB_API}/user/{account['id']}" or (
                url.lower() == f"{GITHUB_API}/users/{account['login']}".lower()
            ):
                return FakeResponse(account)
        if url.startswith((f"{GITHUB_API}/user/", f"{GITHUB_API}/users/")):
            return FakeResponse({"message": "Not Found"}, status_code=404)
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
    def __init__(
        self,
        exit_code: int | None,
        github: FakeGitHub,
        folder: FakeSignatureFolder,
        error: Exception | None = None,
    ) -> None:
        self.exit_code = exit_code
        self.error = error
        self.signature_filenames = set(folder.signatures)
        self.posted_states = [status["state"] for status in github.statuses]
        self.state = self.posted_states[-1] if self.posted_states else None
        self.comment = github.comments[-1]["body"] if github.comments else None
        self.requested_urls = github.requested_urls

    def user_lookup_urls(self) -> list[str]:
        return [
            url
            for url in self.requested_urls
            if url.startswith((f"{GITHUB_API}/user/", f"{GITHUB_API}/users/"))
        ]


def commit_by(author: dict[str, Any], message: str = "Change something") -> dict[str, Any]:
    """Return a PR commit whose git author email GitHub linked to `author`."""
    return {
        "author": author,
        "commit": {
            "author": {"name": author["login"], "email": "x@example.com"},
            "message": message,
        },
    }


def co_authored_message(*trailer_lines: str) -> str:
    """Return a commit message whose last paragraph holds the given trailer lines."""
    return "Change something\n\nLonger description of the change.\n\n" + "\n".join(trailer_lines)


def run_cla_sign(
    *,
    opener: dict[str, Any],
    commit_authors: list[dict[str, Any]],
    signed_users: list[dict[str, Any]],
    allowlist: str | None = None,
    extra_commits: list[dict[str, Any]] | None = None,
    sign_comment_by: dict[str, Any] | None = None,
    github_accounts: list[dict[str, Any]] | None = None,
    server_error_urls: set[str] | None = None,
    expect_error: bool = False,
) -> RunResult:
    """Run cla_sign.main() for one event and return its verdict.

    By default the event is `pull_request_target`. With `sign_comment_by` it is
    an `issue_comment` in which that user posts the sign phrase. The user
    lookup endpoints answer for `github_accounts` and return 404 for anyone else;
    `server_error_urls` answer 500. With `expect_error` an exception raised by
    main() is returned in the result instead of failing the test.
    """
    commits = [commit_by(author) for author in commit_authors] + (extra_commits or [])
    github = FakeGitHub(opener, commits, github_accounts or [], server_error_urls or set())
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
            try:
                exit_code = cla_sign.main()
            except Exception as error:
                if not expect_error:
                    raise
                return RunResult(None, github, folder, error)

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

    def test_unsigned_second_commit_author_fails_and_is_listed(self) -> None:
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


class CoAuthorTrailerTests(unittest.TestCase):
    def test_unsigned_co_author_fails_and_is_listed(self) -> None:
        commit = commit_by(SIGNER, co_authored_message(f"Co-authored-by: Carol <{CAROL_NOREPLY}>"))

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER],
            github_accounts=[CO_AUTHOR],
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("- @carol", result.comment)
        self.assertNotIn("@alice", result.comment)

    def test_signed_co_author_passes(self) -> None:
        commit = commit_by(SIGNER, co_authored_message(f"Co-authored-by: Carol <{CAROL_NOREPLY}>"))

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER, CO_AUTHOR],
            github_accounts=[CO_AUTHOR],
        )

        self.assertEqual(result.state, "success")

    def test_trailer_key_is_matched_case_insensitively(self) -> None:
        commit = commit_by(SIGNER, co_authored_message(f"Co-Authored-By: Carol <{CAROL_NOREPLY}>"))

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER],
            github_accounts=[CO_AUTHOR],
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("- @carol", result.comment)

    def test_allowlisted_bot_co_author_is_skipped(self) -> None:
        commit = commit_by(
            SIGNER,
            co_authored_message(
                "Co-authored-by: dependabot[bot] "
                "<49699333+dependabot[bot]@users.noreply.github.com>"
            ),
        )

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER],
            github_accounts=[DEPENDABOT],
        )

        self.assertEqual(result.state, "success")

    def test_bot_co_author_outside_allowlist_fails(self) -> None:
        commit = commit_by(
            SIGNER,
            co_authored_message("Co-authored-by: Evil <7777+evil[bot]@users.noreply.github.com>"),
        )

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER],
            github_accounts=[EVIL_BOT],
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("- @evil[bot]", result.comment)

    def test_ai_tool_co_author_email_is_unresolved_and_fails(self) -> None:
        commit = commit_by(
            SIGNER, co_authored_message("Co-Authored-By: Claude <noreply@anthropic.com>")
        )

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER],
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("Claude <noreply@anthropic.com>", result.comment)

    def test_co_author_who_is_also_opener_is_listed_once(self) -> None:
        commit = commit_by(SIGNER, co_authored_message(f"Co-authored-by: Carol <{CAROL_NOREPLY}>"))

        result = run_cla_sign(
            opener=CO_AUTHOR,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER],
            github_accounts=[CO_AUTHOR],
        )

        self.assertEqual(result.state, "failure")
        self.assertEqual(result.comment.count("@carol"), 1)

    def test_older_login_only_noreply_email_is_resolved(self) -> None:
        commit = commit_by(
            SIGNER, co_authored_message("Co-authored-by: Carol <carol@users.noreply.github.com>")
        )

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER, CO_AUTHOR],
            github_accounts=[CO_AUTHOR],
        )

        self.assertEqual(result.state, "success")

    def test_renamed_co_author_is_matched_by_id_to_current_login(self) -> None:
        commit = commit_by(
            SIGNER,
            co_authored_message("Co-authored-by: Dave <1004+dave-old@users.noreply.github.com>"),
        )

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER, RENAMED_USER],
            github_accounts=[RENAMED_USER],
        )

        self.assertEqual(result.state, "success")

    def test_co_authored_by_line_outside_last_paragraph_is_ignored(self) -> None:
        message = (
            "Change something\n\n"
            f"Co-authored-by: Carol <{CAROL_NOREPLY}>\n\n"
            "Signed-off-by: Alice <alice@example.com>"
        )

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit_by(SIGNER, message)],
            signed_users=[SIGNER],
            github_accounts=[CO_AUTHOR],
        )

        self.assertEqual(result.state, "success")
        self.assertNotIn("carol", result.comment.lower())

    def test_co_author_on_many_commits_is_listed_once_and_looked_up_once(self) -> None:
        message = co_authored_message(f"Co-authored-by: Carol <{CAROL_NOREPLY}>")

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit_by(SIGNER, message) for _ in range(3)],
            signed_users=[SIGNER],
            github_accounts=[CO_AUTHOR],
        )

        self.assertEqual(result.state, "failure")
        self.assertEqual(result.comment.count("@carol"), 1)
        lookups = [url for url in result.requested_urls if url == f"{GITHUB_API}/user/1003"]
        self.assertEqual(len(lookups), 1)

    def test_login_only_co_author_in_different_casing_is_looked_up_once(self) -> None:
        commits = [
            commit_by(SIGNER, co_authored_message(f"Co-authored-by: Carol <{email}>"))
            for email in ("carol@users.noreply.github.com", "CAROL@users.noreply.github.com")
        ]

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=commits,
            signed_users=[SIGNER],
            github_accounts=[CO_AUTHOR],
        )

        self.assertEqual(result.comment.count("@carol"), 1)
        self.assertEqual(len(result.user_lookup_urls()), 1)

    def test_co_author_whose_account_is_not_found_is_unresolved_and_fails(self) -> None:
        commit = commit_by(
            SIGNER,
            co_authored_message("Co-authored-by: Ghost <5555+ghost@users.noreply.github.com>"),
        )

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER],
        )

        self.assertEqual(result.state, "failure")
        self.assertIn("Ghost <5555+ghost@users.noreply.github.com>", result.comment)

    def test_unlinked_commit_author_on_many_commits_is_listed_once(self) -> None:
        unlinked_commit = {
            "author": None,
            "commit": {"author": {"name": "ghost", "email": "g@example.com"}, "message": "x"},
        }

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[unlinked_commit, unlinked_commit],
            signed_users=[SIGNER],
        )

        self.assertEqual(result.state, "failure")
        self.assertEqual(result.comment.count("ghost <g@example.com>"), 1)

    def test_co_author_lookup_server_error_raises_and_posts_no_success(self) -> None:
        commit = commit_by(SIGNER, co_authored_message(f"Co-authored-by: Carol <{CAROL_NOREPLY}>"))

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER, CO_AUTHOR],
            github_accounts=[CO_AUTHOR],
            server_error_urls={f"{GITHUB_API}/user/1003"},
            expect_error=True,
        )

        self.assertIsInstance(result.error, requests.HTTPError)
        self.assertNotIn("success", result.posted_states)

    def test_co_author_trailer_variants_are_resolved(self) -> None:
        cases = {
            "CRLF line endings": (
                "Change something\r\n\r\n"
                "Co-authored-by: Claude <noreply@anthropic.com>\r\n\r\n"
                f"Co-authored-by: Carol <{CAROL_NOREPLY}>\r\n"
            ),
            "upper-case noreply domain": co_authored_message(
                "Co-authored-by: Carol <1003+carol@Users.Noreply.GitHub.com>"
            ),
            "no name": co_authored_message(f"Co-authored-by: <{CAROL_NOREPLY}>"),
            "extra spaces, also inside the brackets": co_authored_message(
                f"Co-authored-by:    Carol   <  {CAROL_NOREPLY}  >"
            ),
            "trailing whitespace": co_authored_message(
                f"Co-authored-by: Carol <{CAROL_NOREPLY}> \t "
            ),
            "upper-case login in the login-only form": co_authored_message(
                "Co-authored-by: Carol <CAROL@users.noreply.github.com>"
            ),
            "space before the colon": co_authored_message(
                f"Co-authored-by : Carol <{CAROL_NOREPLY}>"
            ),
            "folded continuation line": co_authored_message(
                "Co-authored-by: Carol", f"  <{CAROL_NOREPLY}>"
            ),
        }

        for case_name, message in cases.items():
            with self.subTest(case_name):
                result = run_cla_sign(
                    opener=SIGNER,
                    commit_authors=[],
                    extra_commits=[commit_by(SIGNER, message)],
                    signed_users=[SIGNER],
                    github_accounts=[CO_AUTHOR],
                )

                self.assertEqual(result.state, "failure")
                self.assertIn("- @carol", result.comment)
                self.assertNotIn("could not be linked", result.comment)

    def test_malformed_co_author_trailer_is_unresolved_and_fails(self) -> None:
        cases = {
            "email without brackets": "a@x.com",
            "text after the email": f"Carol <{CAROL_NOREPLY}> extra",
            "no email": "Carol",
        }

        for case_name, trailer_value in cases.items():
            with self.subTest(case_name):
                result = run_cla_sign(
                    opener=SIGNER,
                    commit_authors=[],
                    extra_commits=[
                        commit_by(SIGNER, co_authored_message(f"Co-authored-by: {trailer_value}"))
                    ],
                    signed_users=[SIGNER, CO_AUTHOR],
                    github_accounts=[CO_AUTHOR],
                )

                self.assertEqual(result.state, "failure")
                self.assertIn(f"`{trailer_value} (Co-authored-by trailer)`", result.comment)

    def test_noreply_email_with_path_characters_is_unresolved_without_lookup(self) -> None:
        for email in (
            "../user/5@users.noreply.github.com",
            "1003+../../user/5@users.noreply.github.com",
            "carol?x=1@users.noreply.github.com",
        ):
            with self.subTest(email):
                result = run_cla_sign(
                    opener=SIGNER,
                    commit_authors=[],
                    extra_commits=[
                        commit_by(SIGNER, co_authored_message(f"Co-authored-by: X <{email}>"))
                    ],
                    signed_users=[SIGNER],
                    github_accounts=[CO_AUTHOR, {"login": "five", "id": 5, "type": "User"}],
                )

                self.assertEqual(result.state, "failure")
                self.assertIn(f"X <{email}>", result.comment)
                self.assertEqual(result.user_lookup_urls(), [])

    def test_unresolved_trailer_is_rendered_as_inline_code(self) -> None:
        cases = {
            "team mention": (
                "@EpicStaff/maintainers <x@y.com>",
                "- `@EpicStaff/maintainers <x@y.com> (Co-authored-by trailer)`",
            ),
            "backtick that would close the code span": (
                "Evil` @EpicStaff/maintainers <x@y.com>",
                "- `Evil' @EpicStaff/maintainers <x@y.com> (Co-authored-by trailer)`",
            ),
        }

        for case_name, (trailer_value, expected_line) in cases.items():
            with self.subTest(case_name):
                result = run_cla_sign(
                    opener=SIGNER,
                    commit_authors=[],
                    extra_commits=[
                        commit_by(SIGNER, co_authored_message(f"Co-authored-by: {trailer_value}"))
                    ],
                    signed_users=[SIGNER],
                )

                self.assertEqual(result.state, "failure")
                self.assertIn(expected_line, result.comment.split("\n"))

    def test_co_authors_beyond_lookup_cap_are_unresolved_without_api_calls(self) -> None:
        lookup_cap = cla_common.MAX_CO_AUTHOR_LOOKUPS_PER_RUN
        accounts = [
            {"login": f"helper{number}", "id": 2000 + number, "type": "User"}
            for number in range(lookup_cap + 5)
        ]
        trailers = [
            f"Co-authored-by: Helper <{account['id']}+{account['login']}@users.noreply.github.com>"
            for account in accounts
        ]

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit_by(SIGNER, co_authored_message(*trailers))],
            signed_users=[SIGNER, *accounts],
            github_accounts=accounts,
        )

        self.assertEqual(result.state, "failure")
        self.assertEqual(len(result.user_lookup_urls()), lookup_cap)
        self.assertIn("2024+helper24@users.noreply.github.com", result.comment)

    def test_noreply_id_longer_than_twenty_digits_is_unresolved_without_lookup(self) -> None:
        email = f"{'1' * 25}+carol@users.noreply.github.com"
        commit = commit_by(SIGNER, co_authored_message(f"Co-authored-by: Carol <{email}>"))

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=[],
            extra_commits=[commit],
            signed_users=[SIGNER, CO_AUTHOR],
            github_accounts=[CO_AUTHOR],
        )

        self.assertEqual(result.state, "failure")
        self.assertIn(email, result.comment)
        self.assertEqual(result.user_lookup_urls(), [])


class CommentSizeTests(unittest.TestCase):
    def test_long_lists_are_truncated_with_a_count_of_the_rest(self) -> None:
        listed_cap = cla_sign.MAX_LISTED_ENTRIES
        unsigned_authors = [
            {"login": f"person{number}", "id": 3000 + number, "type": "User"}
            for number in range(listed_cap + 5)
        ]
        unlinked_commits = [
            {
                "author": None,
                "commit": {
                    "author": {"name": f"ghost{number}", "email": f"g{number}@example.com"},
                    "message": "x",
                },
            }
            for number in range(listed_cap + 7)
        ]

        result = run_cla_sign(
            opener=SIGNER,
            commit_authors=unsigned_authors,
            extra_commits=unlinked_commits,
            signed_users=[SIGNER],
        )

        comment_lines = result.comment.split("\n")
        self.assertEqual(result.state, "failure")
        self.assertEqual(
            len([line for line in comment_lines if line.startswith("- @")]), listed_cap
        )
        self.assertEqual(
            len([line for line in comment_lines if line.startswith("- `")]), listed_cap
        )
        self.assertIn("- and 5 more", comment_lines)
        self.assertIn("- and 7 more", comment_lines)
        self.assertNotIn(f"@person{listed_cap}", result.comment)


if __name__ == "__main__":
    unittest.main(verbosity=2)
