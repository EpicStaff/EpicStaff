"""Shared helpers for the CLA sign/check GitHub Actions scripts.

Signatures are stored as one JSON file per contributor per CLA version, inside a
Google Drive Shared Drive folder (one subfolder per CLA version, e.g. ``v1.0.0``).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
from typing import Any

import requests
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload, MediaIoBaseDownload

GH = "https://api.github.com"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
DEFAULT_ALLOWLIST = "dependabot[bot]"

_VERSION_RE = re.compile(r"VERSION\s+(\d+\.\d+\.\d+)")


def parse_cla_version(path: str = "CLA.md") -> str:
    """Extract the CLA version (e.g. "1.0.0") from the CLA.md heading."""
    with open(path, "r", encoding="utf-8") as cla_file:
        first_line = cla_file.readline()

    match = _VERSION_RE.search(first_line)
    if not match:
        raise ValueError(
            f"Could not find CLA version in first line of {path!r}: {first_line!r}"
        )

    return match.group(1)


def cla_sha256(path: str = "CLA.md") -> str:
    """Return the sha256 hex digest of CLA.md with line endings normalized to \\n."""
    with open(path, "rb") as cla_file:
        raw_bytes = cla_file.read()

    text = raw_bytes.decode("utf-8")
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")

    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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


def resolve_pr_authors(
    repo: str, pr_no: int, token: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve the distinct GitHub authors of a PR's commits.

    Returns (authors, unresolved) where authors is a de-duplicated list of
    {"login": str, "id": int} dicts (bots and allowlisted logins excluded), and
    unresolved is a list of git author "name <email>" strings for commits whose
    author could not be linked to a GitHub account.
    """
    allowlist = {
        login.strip()
        for login in os.environ.get("CLA_ALLOWLIST", DEFAULT_ALLOWLIST).split(",")
        if login.strip()
    }

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
                unresolved.append(
                    f"{git_author.get('name')} <{git_author.get('email')}>"
                )
                continue

            if author.get("type") == "Bot":
                continue

            if author["login"] in allowlist:
                continue

            authors_by_id[author["id"]] = {"login": author["login"], "id": author["id"]}

        page += 1

    return list(authors_by_id.values()), unresolved
