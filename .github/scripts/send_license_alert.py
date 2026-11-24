"""Check the licence-alert Gmail credential every day; email the report when the scan failed.

It sends as the alert mailbox through OAuth: a refresh token that mailbox granted
once for the https://www.googleapis.com/auth/gmail.send scope, plus the OAuth
client it was granted to. The token is refreshed on every run, failed scan or not:
Google expires a refresh token left unused for six months, and refreshing daily
also proves the credential still works on the days nothing needs sending.
"""

from __future__ import annotations

import base64
import os
import sys
from email.message import EmailMessage
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
TOKEN_URI = "https://oauth2.googleapis.com/token"


def build_message(recipients: list[str], subject: str, body: str) -> EmailMessage:
    # No From header: Gmail fills in the mailbox the token belongs to.
    message = EmailMessage()
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    return message


def main() -> int:
    client_id = os.environ.get("LICENSE_ALERT_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.environ.get("LICENSE_ALERT_OAUTH_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("LICENSE_ALERT_OAUTH_REFRESH_TOKEN", "").strip()
    recipients = [
        address.strip()
        for address in os.environ.get("LICENSE_ALERT_RECIPIENTS", "").split(",")
        if address.strip()
    ]
    scan_result = os.environ["SCAN_RESULT"]
    report_path = os.environ["REPORT_PATH"]
    run_url = os.environ["RUN_URL"]

    # Checked every day, not only when sending: a setting that goes missing must show up
    # before the day an alert is needed. Names only: the job log is public, and the
    # values are secrets the runner masks.
    missing = [
        name
        for name, value in (
            ("LICENSE_ALERT_OAUTH_CLIENT_ID", client_id),
            ("LICENSE_ALERT_OAUTH_CLIENT_SECRET", client_secret),
            ("LICENSE_ALERT_OAUTH_REFRESH_TOKEN", refresh_token),
            ("LICENSE_ALERT_RECIPIENTS", recipients),
        )
        if not value
    ]
    if missing:
        print(f"::error::Licence alerting is not configured: {', '.join(missing)}", file=sys.stderr)
        return 1

    credentials = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri=TOKEN_URI,
        client_id=client_id,
        client_secret=client_secret,
        scopes=GMAIL_SCOPES,
    )
    try:
        credentials.refresh(Request())
    except RefreshError as error:
        print(
            "::error::The licence-alert Gmail credential no longer works, so alerts cannot be sent. "
            "Usual causes: the alert mailbox's password changed, its access was revoked, or the "
            "OAuth client was deleted. Sign in as the alert mailbox again and replace "
            f"LICENSE_ALERT_OAUTH_REFRESH_TOKEN. ({error})",
            file=sys.stderr,
        )
        return 1

    if scan_result == "success":
        print("Scan passed; Gmail credential refreshed, nothing to send.")
        return 0

    report = (
        Path(report_path).read_text(encoding="utf-8").strip() if os.path.isfile(report_path) else ""
    )
    body = (
        f"The daily licence scan of main found a problem.\n\nRun: {run_url}\n\n"
        + (report or "The scan did not finish, so no package list was produced. See the run log.")
        + "\n"
    )
    message = build_message(recipients, "[EpicStaff] Licence scan found a problem on main", body)
    gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    gmail.users().messages().send(
        userId="me", body={"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
    ).execute()
    print(f"Licence alert sent to {len(recipients)} recipient(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
