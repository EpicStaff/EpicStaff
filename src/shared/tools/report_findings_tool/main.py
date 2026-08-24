# Report Findings Tool
#
# A "typed findings channel" for review/report agents. Instead of dumping a
# review/audit result as plain text, an agent calls this tool with a
# structured `findings` array; the normalized payload is returned to the
# agent as JSON (a concise textual observation) AND is recognized crew-side
# (src/crew/callbacks/session_callback_factory.py, `_publish_agent_action`)
# by the `FINDINGS_MARKER_KEY` below, which republishes it as a distinct
# GraphSessionMessage(message_type="findings") for the frontend to render
# natively (table/cards) instead of as plain agent text.
#
# CONTRACT (keep in sync with session_callback_factory.py):
#   - This tool's successful return value is a dict containing the key
#     FINDINGS_MARKER_KEY = "__epicstaff_message_type__" set to "findings".
#   - The crew callback strips that marker key and republishes the rest of
#     the dict as message_data, with "message_type": "findings" added.
#   - This file has no imports from the rest of the codebase (per sandbox
#     tool convention: only main.py's source text is uploaded/executed), so
#     the marker key string is intentionally duplicated on both sides.

FINDINGS_MARKER_KEY = "__epicstaff_message_type__"

MAX_FINDINGS = 50
MAX_TITLE_LEN = 200
MAX_SHORT_FIELD_LEN = 200
MAX_DETAIL_LEN = 2000
MAX_SUMMARY_LEN = 2000
MAX_WARNINGS_SHOWN = 5

VALID_SEVERITIES = {"info", "low", "medium", "high", "critical"}
DEFAULT_SEVERITY = "info"


def _truncate(value, max_len: int):
    if not isinstance(value, str):
        return value
    if len(value) > max_len:
        return value[:max_len] + "... (truncated)"
    return value


def _normalize_severity(raw) -> tuple[str, str | None]:
    """Returns (severity, warning_or_None)."""
    if isinstance(raw, str) and raw.strip().lower() in VALID_SEVERITIES:
        return raw.strip().lower(), None
    warning = (
        f"invalid severity '{raw}', defaulted to '{DEFAULT_SEVERITY}'. "
        f"Valid values: {', '.join(sorted(VALID_SEVERITIES))}."
    )
    return DEFAULT_SEVERITY, warning


def _normalize_line(raw):
    """Returns (line_or_None, warning_or_None)."""
    if raw is None:
        return None, None
    try:
        return int(raw), None
    except (TypeError, ValueError):
        return None, f"non-integer 'line' value '{raw}' dropped."


def main(
    findings: list | None = None,
    title: str | None = None,
    summary: str | None = None,
) -> str | dict:
    """
    Report a structured list of findings (e.g. from a code review, audit, or
    QA pass). Never raises: all failures are returned as readable error
    strings. On success, returns a JSON-serializable dict carrying the
    normalized, capped findings payload plus a concise confirmation message.
    """
    try:
        if findings is None:
            return "Error: 'findings' is required and must be a non-empty list of finding objects."
        if not isinstance(findings, list):
            return "Error: 'findings' must be a list of finding objects."
        if len(findings) == 0:
            return "Error: 'findings' must contain at least one finding."

        total_submitted = len(findings)
        raw_findings = findings
        count_truncated = total_submitted > MAX_FINDINGS
        if count_truncated:
            raw_findings = findings[:MAX_FINDINGS]

        normalized = []
        warnings = []

        for idx, finding in enumerate(raw_findings):
            if not isinstance(finding, dict):
                warnings.append(f"finding[{idx}] is not an object, skipped.")
                continue

            finding_title = finding.get("title")
            if not finding_title or not isinstance(finding_title, str):
                warnings.append(f"finding[{idx}] missing required 'title', skipped.")
                continue

            severity, severity_warning = _normalize_severity(
                finding.get("severity", DEFAULT_SEVERITY)
            )
            if severity_warning:
                warnings.append(f"finding[{idx}]: {severity_warning}")

            line, line_warning = _normalize_line(finding.get("line"))
            if line_warning:
                warnings.append(f"finding[{idx}]: {line_warning}")

            category = finding.get("category")
            file_path = finding.get("file")
            detail = finding.get("detail")

            normalized.append(
                {
                    "title": _truncate(finding_title, MAX_TITLE_LEN),
                    "severity": severity,
                    "category": _truncate(category, MAX_SHORT_FIELD_LEN)
                    if isinstance(category, str)
                    else None,
                    "file": _truncate(file_path, MAX_SHORT_FIELD_LEN)
                    if isinstance(file_path, str)
                    else None,
                    "line": line,
                    "detail": _truncate(detail, MAX_DETAIL_LEN)
                    if isinstance(detail, str)
                    else None,
                }
            )

        if not normalized:
            reason = " ".join(warnings) or "no valid finding objects were provided."
            return f"Error: no valid findings could be parsed. {reason}"

        truncated = count_truncated or len(normalized) < total_submitted

        payload = {
            FINDINGS_MARKER_KEY: "findings",
            "title": _truncate(title, MAX_TITLE_LEN)
            if isinstance(title, str)
            else None,
            "summary": _truncate(summary, MAX_SUMMARY_LEN)
            if isinstance(summary, str)
            else None,
            "findings": normalized,
            "total_submitted": total_submitted,
            "total_returned": len(normalized),
            "truncated": truncated,
        }

        message = f"Reported {len(normalized)} finding(s)."
        if count_truncated:
            message += (
                f" (input truncated from {total_submitted} to {MAX_FINDINGS} findings)"
            )
        if warnings:
            shown = warnings[:MAX_WARNINGS_SHOWN]
            message += " Warnings: " + " | ".join(shown)
            if len(warnings) > MAX_WARNINGS_SHOWN:
                message += f" (+{len(warnings) - MAX_WARNINGS_SHOWN} more)"

        payload["message"] = message
        return payload
    except Exception as e:
        return f"Error: failed to report findings. Unexpected exception: {e}"
