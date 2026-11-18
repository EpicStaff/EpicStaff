"""Email the licence scan report through Gmail when the daily scan finds a problem.

A service account has no mailbox of its own: it sends as LICENSE_ALERT_SENDER
through domain-wide delegation, which a Google Workspace admin grants to the
account's client ID for the https://www.googleapis.com/auth/gmail.send scope.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from email.message import EmailMessage
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def build_message(sender: str, recipients: list[str], subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    return message


def main() -> int:
    raw_key = os.environ.get("LICENSE_ALERT_GMAIL_SERVICE_ACCOUNT_JSON", "").strip()
    sender = os.environ.get("LICENSE_ALERT_SENDER", "").strip()
    recipients = [
        address.strip()
        for address in os.environ.get("LICENSE_ALERT_RECIPIENTS", "").split(",")
        if address.strip()
    ]
    report_path = os.environ["REPORT_PATH"]
    run_url = os.environ["RUN_URL"]

    # A missing setting must fail loudly: a silent skip would read as "no problem found".
    # Names only: the job log is public, and the values are secrets the runner masks.
    missing = [
        name
        for name, value in (
            ("LICENSE_ALERT_GMAIL_SERVICE_ACCOUNT_JSON", raw_key),
            ("LICENSE_ALERT_SENDER", sender),
            ("LICENSE_ALERT_RECIPIENTS", recipients),
        )
        if not value
    ]
    if missing:
        print(
            f"::error::Licence alert NOT sent -- not configured: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 1

    report = (
        Path(report_path).read_text(encoding="utf-8").strip() if os.path.isfile(report_path) else ""
    )
    body = (
        f"The daily licence scan of main found a problem.\n\nRun: {run_url}\n\n"
        + (report or "The scan did not finish, so no package list was produced. See the run log.")
        + "\n"
    )
    message = build_message(
        sender, recipients, "[EpicStaff] Licence scan found a problem on main", body
    )

    credentials = Credentials.from_service_account_info(
        json.loads(raw_key), scopes=GMAIL_SCOPES, subject=sender
    )
    gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    try:
        gmail.users().messages().send(
            userId="me", body={"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}
        ).execute()
    except RefreshError as error:
        print(
            "::error::Licence alert NOT sent -- Google refused to let the service account send as "
            "LICENSE_ALERT_SENDER. A Workspace admin must grant its client ID domain-wide delegation "
            f"for {GMAIL_SCOPES[0]}. ({error})",
            file=sys.stderr,
        )
        return 1

    print(f"Licence alert sent to {len(recipients)} recipient(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
