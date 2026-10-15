"""Shared helpers for the CLA sign/check GitHub Actions scripts.

Signatures are stored as one JSON file per contributor per CLA version, inside a
Google Drive Shared Drive folder (one subfolder per CLA version, e.g. ``v1.0.0``).
"""

from __future__ import annotations

import io
import json
import os
import re
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
# Each new co-author costs one GitHub API call, and the workflow token's rate limit
# is shared by the whole repository. A PR could otherwise list hundreds of fake
# co-authors and use up that limit on every push.
MAX_CO_AUTHOR_LOOKUPS_PER_RUN = 2

PARAGRAPH_SEPARATOR_RE = re.compile(r"\n[ \t]*\n")
CO_AUTHOR_TRAILER_RE = re.compile(r"^\s*co-authored-by\s*:(?P<value>.*)$", re.IGNORECASE)
NAME_AND_EMAIL_RE = re.compile(r"(?P<name>[^<>]*?)\s*<\s*(?P<email>[^<>\s]+)\s*>")
# GitHub logins: letters, digits and hyphens, at most 39 characters; app bots end in "[bot]".
# Keeping to this charset also stops a crafted email from changing the lookup URL path.
GITHUB_LOGIN_PATTERN = r"[A-Za-z0-9][A-Za-z0-9-]{0,38}(?:\[bot\])?"
NOREPLY_EMAIL_WITH_ID_RE = re.compile(
    rf"(?P<id>[0-9]{{1,20}})\+(?P<login>{GITHUB_LOGIN_PATTERN})@users\.noreply\.github\.com",
    re.IGNORECASE,
)
NOREPLY_EMAIL_LOGIN_ONLY_RE = re.compile(
    rf"(?P<login>{GITHUB_LOGIN_PATTERN})@users\.noreply\.github\.com", re.IGNORECASE
)


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


def parse_co_authors(message: str) -> list[str]:
    """Return the values of the ``Co-authored-by:`` trailers in a commit message.

    Only the last paragraph of the message is read as trailers, so a
    ``Co-authored-by:`` line quoted in the body is ignored. Unlike git, a
    message whose only paragraph is a trailer also counts — stricter on purpose.
    The key is matched loosely: any case (``Co-Authored-By``) and spaces before
    the colon. A line that starts with whitespace right after a trailer is a
    folded continuation of it. Each value is returned with its whitespace
    collapsed to single spaces, and is not validated here.
    """
    paragraphs = PARAGRAPH_SEPARATOR_RE.split(message.replace("\r\n", "\n").strip())
    last_paragraph = paragraphs[-1]

    values: list[str] = []
    is_inside_trailer = False
    for line in last_paragraph.split("\n"):
        if is_inside_trailer and line[:1].isspace() and line.strip():
            values[-1] = f"{values[-1]} {line}"
            continue

        match = CO_AUTHOR_TRAILER_RE.match(line)
        is_inside_trailer = match is not None
        if match:
            values.append(match.group("value"))

    return [" ".join(value.split()) for value in values]


def parse_name_and_email(trailer_value: str) -> tuple[str, str] | None:
    """Split a ``Name <email>`` trailer value into (name, email); None if it is malformed."""
    match = NAME_AND_EMAIL_RE.fullmatch(trailer_value.strip())
    if match is None:
        return None

    return match.group("name"), match.group("email")


def parse_noreply_email(email: str) -> int | str | None:
    """Return what a GitHub noreply email identifies an account by.

    ``<id>+<login>@users.noreply.github.com`` returns the numeric id: the id
    never changes, while the login in the email is stale after a rename. The
    older ``<login>@users.noreply.github.com`` form returns the login. Any other
    email returns None, because it cannot be tied to an account reliably.
    """
    match = NOREPLY_EMAIL_WITH_ID_RE.fullmatch(email)
    if match:
        return int(match.group("id"))

    match = NOREPLY_EMAIL_LOGIN_ONLY_RE.fullmatch(email)
    if match:
        return match.group("login")

    return None


def user_cache_key(identifier: int | str) -> int | str:
    """Return the cache key for a user id or login; logins are case-insensitive on GitHub."""
    if isinstance(identifier, str):
        return identifier.lower()

    return identifier


def fetch_github_user(
    identifier: int | str,
    headers: dict[str, str],
    cache: dict[int | str, dict[str, Any] | None],
) -> dict[str, Any] | None:
    """Return the GitHub account for an id (int) or login (str), or None if it does not exist.

    Results, including "not found", are stored in ``cache`` under
    ``user_cache_key`` so a co-author named on many commits costs one API call
    per run.
    """
    identifier = user_cache_key(identifier)

    if identifier in cache:
        return cache[identifier]

    if isinstance(identifier, int):
        url = f"{GH}/user/{identifier}"
    else:
        url = f"{GH}/users/{identifier}"

    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 404:
        user = None
    else:
        response.raise_for_status()
        user = response.json()

    cache[identifier] = user
    return user


def resolve_pr_authors(repo: str, pr_no: int, token: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Resolve the distinct GitHub authors and co-authors of a PR's commits.

    Returns (authors, unresolved). authors is a de-duplicated list of
    {"login": str, "id": int} dicts: every commit author linked to a GitHub
    account, plus every person named in a ``Co-authored-by:`` trailer whose
    email is a GitHub noreply address. unresolved lists, once each, the people
    who could not be linked to a GitHub account: commit authors as
    "name <email>", co-authors as "<trailer value> (Co-authored-by trailer)".
    A trailer value that is not ``Name <email>`` is unresolved too.

    At most ``MAX_CO_AUTHOR_LOOKUPS_PER_RUN`` distinct co-authors are looked up;
    any further co-author is unresolved without an API call, so the check still
    fails.

    A co-author is looked up by the id (or, for the older email form, the login)
    in their noreply email, and the account's current login is used. Any other
    co-author email is unresolved — including the emails AI tools add, which is
    deliberate: such a trailer has to be removed.

    Only allow-listed bots (see ``is_allowlisted_bot``) are left out of authors.
    Any other bot is returned as a normal author, so it fails the check because
    it has no signature. Commit emails and trailers are free text that the
    committer controls and can add or omit, so this list alone does not prove
    who wrote the code — callers must also check the PR opener.
    """
    allowlist = load_bot_allowlist()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }

    authors_by_id: dict[int, dict[str, Any]] = {}
    unresolved: dict[str, None] = {}
    user_cache: dict[int | str, dict[str, Any] | None] = {}

    def add_author(user: dict[str, Any]) -> None:
        if is_allowlisted_bot(user, allowlist):
            return
        authors_by_id[user["id"]] = {"login": user["login"], "id": user["id"]}

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
                unresolved[f"{git_author.get('name')} <{git_author.get('email')}>"] = None
            else:
                add_author(author)

            for trailer_value in parse_co_authors(commit["commit"].get("message") or ""):
                co_author = None
                name_and_email = parse_name_and_email(trailer_value)
                identifier = None
                if name_and_email is not None:
                    identifier = parse_noreply_email(name_and_email[1])

                if identifier is not None:
                    is_new_lookup = user_cache_key(identifier) not in user_cache
                    if is_new_lookup and len(user_cache) >= MAX_CO_AUTHOR_LOOKUPS_PER_RUN:
                        unresolved[
                            f"{trailer_value} (Co-authored-by trailer, not checked: more than "
                            f"{MAX_CO_AUTHOR_LOOKUPS_PER_RUN} co-authors on this PR)"
                        ] = None
                        continue
                    co_author = fetch_github_user(identifier, headers, user_cache)

                if co_author is None:
                    unresolved[f"{trailer_value} (Co-authored-by trailer)"] = None
                else:
                    add_author(co_author)

        page += 1

    return list(authors_by_id.values()), list(unresolved)
