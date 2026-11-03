"""Matchers for the fixed texts a user sees when the sandbox itself fails."""

import re

SERVER_ERROR = re.compile(
    r"The code couldn't run because of a server error\. Try again or contact your "
    r"administrator \(reference: (?P<reference>[0-9a-f]{12})\)\."
)
UNSAFE_TO_RUN = re.compile(
    r"This server can't run code safely right now, so the code wasn't run\. Contact your "
    r"administrator \(reference: (?P<reference>[0-9a-f]{12})\)\."
)


def reference_in(pattern: re.Pattern, text: str) -> str:
    """Return the reference ``text`` cites, failing unless it is exactly ``pattern``."""
    match = pattern.fullmatch(text)
    assert match is not None, f"unexpected text: {text!r}"
    return match["reference"]


def logged_with(reference: str, error_logs: list[str]) -> str:
    """Return the one error log line citing ``reference``."""
    lines = [line for line in error_logs if f"(reference: {reference})" in line]
    assert len(lines) == 1, f"expected one log line citing {reference}, got {lines}"
    return lines[0]
