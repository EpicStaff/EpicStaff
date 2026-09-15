"""Upload a dependency-scan report to the private Google Shared Drive."""

from __future__ import annotations

import json
import os
import sys

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def drive_service(raw_key: str):
    credentials = Credentials.from_service_account_info(
        json.loads(raw_key), scopes=DRIVE_SCOPES
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _accessible_shared_drives(svc) -> list[str]:
    try:
        drives = svc.drives().list(pageSize=100, fields="drives(id, name)").execute()
        return [f"{d['name']} ({d['id']})" for d in drives.get("drives", [])]
    except HttpError:
        return []


def preflight(svc, root_id: str, client_email: str) -> int:
    try:
        folder = (
            svc.files()
            .get(fileId=root_id, fields="id, name, mimeType, driveId, trashed",
                 supportsAllDrives=True)
            .execute()
        )
    except HttpError as exc:
        if exc.resp.status not in (403, 404):
            raise
        visible = _accessible_shared_drives(svc)
        print(f"::error::Drive folder {root_id} is not visible to the service "
              f"account {client_email}.", file=sys.stderr)
        if visible:
            print(f"That account IS a member of: {'; '.join(visible)}. So it "
                  f"authenticates fine -- the folder is either in a different "
                  f"Shared Drive or not shared with this account.", file=sys.stderr)
        else:
            print("That account is a member of NO Shared Drive. Folder-level "
                  "sharing is often blocked for service accounts by the Shared "
                  "Drive's external-sharing setting -- add it as a MEMBER of the "
                  "Shared Drive itself (Content manager), not just to the folder.",
                  file=sys.stderr)
        return 1

    if folder.get("trashed"):
        print(f"::error::Folder {folder.get('name')!r} is in the trash.",
              file=sys.stderr)
        return 1
    if folder.get("mimeType") != FOLDER_MIME_TYPE:
        print(f"::error::SECURITY_GDRIVE_ROOT_ID points at "
              f"{folder.get('mimeType')!r}, not a folder.", file=sys.stderr)
        return 1
    if not folder.get("driveId"):
        print(f"::error::Folder {folder.get('name')!r} is not in a Shared Drive. A "
              f"service account has no storage quota, so uploads here fail.",
              file=sys.stderr)
        return 1

    print(f"Destination: {folder.get('name')!r} (Shared Drive {folder['driveId']})")
    return 0


def get_or_create_folder(svc, parent_id: str, name: str) -> str:
    """Return the id of `name` under parent_id, creating it if absent."""
    query = (
        f"name = '{name}' and '{parent_id}' in parents "
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
                "name": name,
                "mimeType": FOLDER_MIME_TYPE,
                "parents": [parent_id],
            },
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    return created["id"]


def main() -> int:
    root_id = os.environ.get("SECURITY_GDRIVE_ROOT_ID", "").strip()
    raw_key = os.environ.get("SECURITY_GDRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    report_path = os.environ["REPORT_PATH"]
    report_name = os.environ["REPORT_NAME"]

    # A missing destination must fail loudly. It must never read as "clean".
    if not root_id:
        print(
            "::error::SECURITY_GDRIVE_ROOT_ID is not set -- the scan report was "
            "NOT stored. Configure it (see docs/security-scan-reports.md).",
            file=sys.stderr,
        )
        return 1

    if not raw_key:
        print(
            "::error::SECURITY_GDRIVE_SERVICE_ACCOUNT_JSON is not set -- the scan "
            "report was NOT stored.",
            file=sys.stderr,
        )
        return 1

    if not os.path.isfile(report_path):
        print(f"::error::report file {report_path!r} does not exist", file=sys.stderr)
        return 1

    svc = drive_service(raw_key)

    client_email = json.loads(raw_key).get("client_email", "<unknown>")
    failed = preflight(svc, root_id, client_email)
    if failed:
        return failed

    month_folder = get_or_create_folder(svc, root_id, report_name[:7])

    media = MediaFileUpload(report_path, mimetype="text/plain", resumable=False)
    created = (
        svc.files()
        .create(
            body={"name": report_name, "parents": [month_folder]},
            media_body=media,
            fields="id, webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )

    print(f"Uploaded {report_name} -> {created.get('webViewLink')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
