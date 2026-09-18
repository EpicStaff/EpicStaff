#!/usr/bin/env python3
"""Evaluate and record CLA signatures for a pull request.

Triggered by cla.yml on `pull_request_target` (opened/closed/synchronize) and on
`issue_comment` (created) for PR comments. Records a signature in Google Drive
when the commenter posts the sign phrase, then always re-evaluates the CLA
status of every commit author on the PR, posts/updates a single tracking
comment, and sets a `CLA` commit status on the PR head SHA.

Always exits 0 — the commit status carries the actual verdict, `pr.yml` is what
enforces it.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
from typing import Any

import requests

sys.path.insert(0, os.path.dirname(__file__))

from cla_common import (  # noqa: E402
    cla_sha256,
    drive_service,
    get_or_create_version_folder,
    get_signature,
    list_signature_filenames,
    parse_cla_version,
    put_signature,
    resolve_pr_authors,
    signature_filename,
)

GH = "https://api.github.com"
SIGN_PHRASE = "I have read the CLA Document and I hereby sign the CLA"
RECHECK_PHRASE = "recheck"
COMMENT_MARKER = "<!-- cla-bot -->"


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }


def get_pr_head_sha(repo: str, pr_no: int, token: str) -> str:
    """Fetch the current head SHA of a PR by number."""
    response = requests.get(
        f"{GH}/repos/{repo}/pulls/{pr_no}",
        headers=_github_headers(token),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["head"]["sha"]


def find_bot_comment_id(
    repo: str, pr_no: int, token: str
) -> tuple[int | None, str | None]:
    """Return (comment_id, html_url) of our tracking comment on the PR, if any."""
    page = 1
    while True:
        response = requests.get(
            f"{GH}/repos/{repo}/issues/{pr_no}/comments",
            headers=_github_headers(token),
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        comments = response.json()
        if not comments:
            return None, None

        for comment in comments:
            if COMMENT_MARKER in comment.get("body", ""):
                return comment["id"], comment["html_url"]

        page += 1


def upsert_pr_comment(repo: str, pr_no: int, token: str, body: str) -> str:
    """Create or update the CLA tracking comment on the PR. Returns its html_url."""
    comment_id, existing_url = find_bot_comment_id(repo, pr_no, token)
    full_body = f"{body}\n\n{COMMENT_MARKER}"

    if comment_id is not None:
        response = requests.patch(
            f"{GH}/repos/{repo}/issues/comments/{comment_id}",
            headers=_github_headers(token),
            json={"body": full_body},
            timeout=30,
        )
        response.raise_for_status()
        return response.json().get("html_url", existing_url)

    response = requests.post(
        f"{GH}/repos/{repo}/issues/{pr_no}/comments",
        headers=_github_headers(token),
        json={"body": full_body},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["html_url"]


def set_commit_status(
    repo: str,
    sha: str,
    token: str,
    state: str,
    description: str,
    target_url: str | None,
) -> None:
    """Set the `CLA` commit status on the given SHA."""
    payload: dict[str, Any] = {
        "context": "CLA",
        "state": state,
        "description": description[:140],
    }
    if target_url:
        payload["target_url"] = target_url

    response = requests.post(
        f"{GH}/repos/{repo}/statuses/{sha}",
        headers=_github_headers(token),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()


def build_comment_body(
    version: str, unsigned: list[dict[str, Any]], unresolved: list[str]
) -> str:
    """Build the tracking-comment markdown for the current CLA status."""
    if not unsigned and not unresolved:
        return f"All contributors have signed CLA v{version}. ✅"

    lines = [
        "Thank you for your submission, we appreciate it. EpicStaff is a "
        "source-available project maintained by HYS Enterprise B.V. and "
        "distributed under the PolyForm Perimeter License 1.0.0. Before we can "
        "accept your contribution, we ask that you read and sign our Individual "
        "Contributor License Agreement (CLA). You can sign the CLA by posting a "
        "Pull Request comment in the same format as below.",
        "",
        f"`{SIGN_PHRASE}`",
    ]

    if unsigned:
        lines.append("")
        lines.append("The following contributors still need to sign:")
        for author in unsigned:
            lines.append(f"- @{author['login']}")

    if unresolved:
        lines.append("")
        lines.append(
            "Some commits on this PR have an author that could not be linked to a "
            "GitHub account. Please set your commit email to one associated with "
            "your GitHub account and force-push:"
        )
        for git_author in unresolved:
            lines.append(f"- {git_author}")

    return "\n".join(lines)


def evaluate_signatures(
    drive_svc,
    folder_id: str,
    sha: str,
    authors: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the subset of authors who have not signed the current CLA sha."""
    existing_filenames = list_signature_filenames(drive_svc, folder_id)
    unsigned: list[dict[str, Any]] = []

    for author in authors:
        filename = signature_filename(author["login"], author["id"])
        if filename not in existing_filenames:
            unsigned.append(author)
            continue

        signature = get_signature(drive_svc, folder_id, filename)
        if signature is None or signature.get("cla_sha256") != sha:
            unsigned.append(author)

    return unsigned


def record_signature(
    drive_svc,
    folder_id: str,
    version: str,
    sha: str,
    login: str,
    gid: int,
    comment_body: str,
    comment_url: str,
    pr_no: int,
) -> None:
    """Write a signature JSON for the commenter to Drive."""
    payload = {
        "github_login": login,
        "github_id": gid,
        "cla_version": version,
        "cla_sha256": sha,
        "comment_text": comment_body,
        "comment_url": comment_url,
        "pull_request_no": pr_no,
        "signed_at": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
    }
    put_signature(drive_svc, folder_id, signature_filename(login, gid), payload)


def main() -> int:
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    event_name = os.environ["GITHUB_EVENT_NAME"]
    event_path = os.environ["GITHUB_EVENT_PATH"]
    root_id = os.environ["CLA_GDRIVE_ROOT_ID"]

    with open(event_path, "r", encoding="utf-8") as event_file:
        event = json.load(event_file)

    if event_name == "pull_request_target":
        pr_no = event["pull_request"]["number"]
    elif event_name == "issue_comment":
        if "pull_request" not in event["issue"]:
            print("Comment is not on a pull request, nothing to do.")
            return 0
        pr_no = event["issue"]["number"]
    else:
        print(f"Unsupported event {event_name!r}, nothing to do.")
        return 0

    version = parse_cla_version()
    sha = cla_sha256()
    drive_svc = drive_service()
    folder_id = get_or_create_version_folder(drive_svc, root_id, version)

    if event_name == "issue_comment":
        comment_body = event["comment"]["body"].strip()
        commenter_login = event["comment"]["user"]["login"]
        commenter_id = event["comment"]["user"]["id"]
        comment_url = event["comment"]["html_url"]

        if comment_body == SIGN_PHRASE:
            record_signature(
                drive_svc,
                folder_id,
                version,
                sha,
                commenter_login,
                commenter_id,
                comment_body,
                comment_url,
                pr_no,
            )
            print(f"Recorded CLA v{version} signature for {commenter_login}.")
        elif comment_body == RECHECK_PHRASE:
            print("Recheck requested, re-evaluating CLA status.")
        else:
            print("Comment is neither the sign phrase nor 'recheck', nothing to do.")
            return 0

    head_sha = get_pr_head_sha(repo, pr_no, token)
    authors, unresolved = resolve_pr_authors(repo, pr_no, token)
    unsigned = evaluate_signatures(drive_svc, folder_id, sha, authors)

    comment_body_out = build_comment_body(version, unsigned, unresolved)
    comment_url = upsert_pr_comment(repo, pr_no, token, comment_body_out)

    is_signed = not unsigned and not unresolved
    set_commit_status(
        repo,
        head_sha,
        token,
        state="success" if is_signed else "failure",
        description=f"CLA v{version} signed by all contributors"
        if is_signed
        else "CLA not signed by all contributors",
        target_url=comment_url,
    )

    print(
        f"CLA v{version}: unsigned={[a['login'] for a in unsigned]} unresolved={unresolved}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
