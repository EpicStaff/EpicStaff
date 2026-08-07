#!/usr/bin/env python3
"""Gate a PR build on the `CLA` commit status set by cla_sign.py.

Invoked by pr.yml's `check-cla` job. Polls the commit statuses of the PR head
SHA for a status with context "CLA", retrying briefly to absorb the race
between the `pull_request` event (this workflow) and the asynchronous
`pull_request_target` / `issue_comment` event that runs cla.yml. Exits 0 if the
CLA status is "success", exits 1 otherwise (including if it never appears).
"""

from __future__ import annotations

import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))

GH = "https://api.github.com"
CLA_CONTEXT = "CLA"
MAX_ATTEMPTS = 10
RETRY_DELAY_SECONDS = 6


def find_cla_status(repo: str, sha: str, token: str) -> dict | None:
    """Return the latest `CLA` context status for the given SHA, or None."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    response = requests.get(
        f"{GH}/repos/{repo}/commits/{sha}/statuses",
        headers=headers,
        params={"per_page": 100},
        timeout=30,
    )
    response.raise_for_status()

    for status in response.json():
        if status.get("context") == CLA_CONTEXT:
            return status

    return None


def main() -> int:
    token = os.environ["GITHUB_TOKEN"]
    repo = os.environ["GITHUB_REPOSITORY"]
    sha = os.environ["CLA_HEAD_SHA"]

    status = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        status = find_cla_status(repo, sha, token)
        if status is not None:
            break

        print(
            f"CLA status not found yet for {sha} (attempt {attempt}/{MAX_ATTEMPTS}), retrying..."
        )
        time.sleep(RETRY_DELAY_SECONDS)

    if status is None:
        print(
            f"::error::No CLA status found for {sha} after {MAX_ATTEMPTS} attempts. Treating as not signed."
        )
        return 1

    state = status.get("state")
    if state == "success":
        print(f"CLA status is 'success' for {sha}: {status.get('description')}")
        return 0

    print(f"::error::CLA status is {state!r} for {sha}: {status.get('description')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
