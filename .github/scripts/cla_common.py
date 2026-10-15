"""Shared helpers for the CLA sign/check GitHub Actions scripts.

Signatures are stored as one JSON file per contributor per CLA version, inside a
Google Drive Shared Drive folder (one subfolder per CLA version, e.g. ``v1.0.0``).
"""

from __future__ import annotations

import io
import json
import os
import sys
from typing import Any

import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

sys.path.insert(0, os.path.dirname(__file__))

# Re-exported so existing callers keep importing these from cla_common. They
# live in cla_version.py because the version guard has to read CLA.md without
# pulling in requests / the Google client libraries.
from cla_version import (  # noqa: F401
    _VERSION_RE,
    cla_sha256,
    parse_cla_version,
    parse_version_from_text,
    version_tuple,
)

GH = "https://api.github.com"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DEFAULT_ALLOWLIST = "dependabot[bot]"


def drive_service():
    """Build an authenticated Google Drive v3 client from the service-account secret."""
    raw_key = os.environ.get("CLA_GDRIVE_SERVICE_ACCOUNT_JSON")
    if not raw_key:
        raise RuntimeError("CLA_GDRIVE_SERVICE_ACCOUNT_JSON env var not set")

    key_info = json.loads(raw_key)
    credentials = Credentials.from_service_account_info(key_info, scopes=DRIVE_SCOPES)

    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def get_or_create_version_folder(svc, root_id: str, version: str) -> str:
    """Return the Drive folder id for the given CLA version, creating it if needed."""
    folder_name = f"v{version}"
    query = (
        f"name = '{folder_name}' and '{root_id}' in parents "
        f"and mimeType = '{FOLDER_MIME_TYPE}' and trashed = false"
    )

    response = (
        svc.files()
        .list(
            q=query,
            fields="files(id, name)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            spaces="drive",
        )
        .execute()
    )

    files = response.get("files", [])
    if files:
        return files[0]["id"]

    created = (
        svc.files()
        .create(
            body={
                "name": folder_name,
                "mimeType": FOLDER_MIME_TYPE,
                "parents": [root_id],
            },
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )

    return created["id"]


def list_signature_filenames(svc, folder_id: str) -> set[str]:
    """Return the set of non-trashed file names inside the given signatures folder."""
    query = f"'{folder_id}' in parents and trashed = false"
    names: set[str] = set()
    page_token = None

    while True:
        response = (
            svc.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name)",
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                spaces="drive",
                pageToken=page_token,
            )
            .execute()
        )

        names.update(entry["name"] for entry in response.get("files", []))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return names


def _find_file_id(svc, folder_id: str, filename: str) -> str | None:
    query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
    response = (
        svc.files()
        .list(
            q=query,
            fields="files(id, name)",
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            spaces="drive",
        )
        .execute()
    )

    files = response.get("files", [])
    if not files:
        return None

    return files[0]["id"]


def get_signature(svc, folder_id: str, filename: str) -> dict[str, Any] | None:
    """Return the parsed signature JSON for filename, or None if it does not exist."""
    file_id = _find_file_id(svc, folder_id, filename)
    if file_id is None:
        return None

    request = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    return json.loads(buffer.getvalue().decode("utf-8"))


def put_signature(svc, folder_id: str, filename: str, payload: dict[str, Any]) -> None:
    """Create or update the signature file `filename` inside folder_id with payload."""
    media = MediaInMemoryUpload(
        json.dumps(payload, indent=2).encode("utf-8"),
        mimetype="application/json",
    )

    existing_file_id = _find_file_id(svc, folder_id, filename)
    if existing_file_id is not None:
        svc.files().update(
            fileId=existing_file_id,
            media_body=media,
            supportsAllDrives=True,
        ).execute()
        return

    svc.files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=media,
        supportsAllDrives=True,
    ).execute()


def signature_filename(login: str, gid: int) -> str:
    """Return the deterministic signature file name for a GitHub user."""
    return f"{login}_{gid}.json"


def load_bot_allowlist() -> set[str]:
    """Return the logins of bots that do not need to sign the CLA.

    Read from the comma-separated ``CLA_ALLOWLIST`` env var. A value with no
    logins in it (unset, empty, whitespace or only commas) falls back to
    ``DEFAULT_ALLOWLIST``: the workflow passes an unset repo variable through as
    an empty string, and that must not turn the allow-list off.
    """
    raw_allowlist = os.environ.get("CLA_ALLOWLIST", "")
    logins = {login.strip() for login in raw_allowlist.split(",") if login.strip()}

    return logins or {DEFAULT_ALLOWLIST}


def is_allowlisted_bot(user: dict[str, Any], allowlist: set[str]) -> bool:
    """Return True only for a GitHub Bot account whose login is in the allow-list.

    Both conditions are required. A ``User`` account with an allow-listed login
    is not a bot, and a bot outside the allow-list has given no licence grant.
    """
    return user.get("type") == "Bot" and user.get("login") in allowlist


def resolve_pr_authors(repo: str, pr_no: int, token: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve the distinct GitHub authors of a PR's commits.

    Returns (authors, unresolved) where authors is a de-duplicated list of
    {"login": str, "id": int} dicts and unresolved is a list of git author
    "name <email>" strings for commits whose author could not be linked to a
    GitHub account.

    Only allow-listed bots (see ``is_allowlisted_bot``) are left out of authors.
    Any other bot is returned as a normal author, so it fails the check because
    it has no signature. The author is linked through the commit's git email,
    which the committer controls, so this list alone does not prove who wrote
    the code — callers must also check the PR opener.
    """
    allowlist = load_bot_allowlist()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    authors_by_id: dict[int, dict[str, Any]] = {}
    unresolved: list[str] = []
    page = 1

    while True:
        response = requests.get(
            f"{GH}/repos/{repo}/pulls/{pr_no}/commits",
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=30,
        )
        response.raise_for_status()
        commits = response.json()
        if not commits:
            break

        for commit in commits:
            author = commit.get("author")
            if author is None:
                git_author = commit["commit"]["author"]
                unresolved.append(f"{git_author.get('name')} <{git_author.get('email')}>")
                continue

            if is_allowlisted_bot(author, allowlist):
                continue

            authors_by_id[author["id"]] = {"login": author["login"], "id": author["id"]}

        page += 1

    return list(authors_by_id.values()), unresolved
