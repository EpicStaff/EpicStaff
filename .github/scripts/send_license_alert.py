"""Check the licence-alert mailbox login every day; email the report when the scan failed.

It sends through the company mail server over SMTP with SSL, logged in as the
alert mailbox. The login runs on every run, failed scan or not, so a changed
password or a server that stopped accepting the runner shows up the same day
instead of on the day an alert is needed.
"""

from __future__ import annotations

import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

SMTP_PORT = 465  # SSL; the server also offers 587 with STARTTLS


def build_message(sender: str, recipients: list[str], subject: str, body: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)
    return message


def main() -> int:
    host = os.environ.get("LICENSE_ALERT_SMTP_HOST", "").strip()
    user = os.environ.get("LICENSE_ALERT_SMTP_USER", "").strip()
    password = os.environ.get("LICENSE_ALERT_SMTP_PASSWORD", "")
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
            ("LICENSE_ALERT_SMTP_HOST", host),
            ("LICENSE_ALERT_SMTP_USER", user),
            ("LICENSE_ALERT_SMTP_PASSWORD", password),
            ("LICENSE_ALERT_RECIPIENTS", recipients),
        )
        if not value
    ]
    if missing:
        print(f"::error::Licence alerting is not configured: {', '.join(missing)}", file=sys.stderr)
        return 1

    # Connection and send errors are left uncaught on purpose: each fails the job,
    # which is what opens the "alerting is broken" issue.
    with smtplib.SMTP_SSL(
        host, SMTP_PORT, context=ssl.create_default_context(), timeout=30
    ) as server:
        try:
            server.login(user, password)
        except smtplib.SMTPAuthenticationError as error:
            print(
                "::error::The alert mailbox login was refused, so alerts cannot be sent. Usually its "
                "password changed: update LICENSE_ALERT_SMTP_PASSWORD in the license-alerts "
                f"environment. ({error.smtp_code})",
                file=sys.stderr,
            )
            return 1

        if scan_result == "success":
            print("Scan passed; alert mailbox login works, nothing to send.")
            return 0

        report = (
            Path(report_path).read_text(encoding="utf-8").strip()
            if os.path.isfile(report_path)
            else ""
        )
        body = (
            f"The daily licence scan of main found a problem.\n\nRun: {run_url}\n\n"
            + (
                report
                or "The scan did not finish, so no package list was produced. See the run log."
            )
            + "\n"
        )
        server.send_message(
            build_message(
                user, recipients, "[EpicStaff] Licence scan found a problem on main", body
            )
        )
    print(f"Licence alert sent to {len(recipients)} recipient(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
