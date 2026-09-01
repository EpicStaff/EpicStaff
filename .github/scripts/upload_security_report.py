"""Upload a dependency-scan report to the private Google Shared Drive."""

from __future__ import annotations

import json
import os
import sys

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def drive_service(raw_key: str):
    credentials = Credentials.from_service_account_info(
        json.loads(raw_key), scopes=DRIVE_SCOPES
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


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
