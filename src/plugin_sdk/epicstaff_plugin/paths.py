"""The rules every path inside a plugin package follows, and every path a manifest names."""

import re
import unicodedata

MAX_PATH_BYTES = 1024

_DRIVE_LETTER = re.compile(r"^[A-Za-z]:")


def path_problem(path: str) -> str | None:
    """Return why `path` may not appear in a package, or None when it may.

    A package path is UTF-8 in NFC form, relative, `/`-separated, without `.` or `..`
    segments, empty segments, backslashes, drive letters or control characters.
    """
    if not path:
        return "is empty"
    if len(path.encode("utf-8")) > MAX_PATH_BYTES:
        return f"is longer than {MAX_PATH_BYTES} bytes"
    if unicodedata.normalize("NFC", path) != path:
        return "is not in Unicode NFC form"
    if any(unicodedata.category(character) == "Cc" for character in path):
        return "contains a control character"
    if "\\" in path:
        return "contains a backslash"
    if path.startswith("/"):
        return "is absolute"
    if _DRIVE_LETTER.match(path):
        return "starts with a drive letter"
    if any(segment in ("", ".", "..") for segment in path.split("/")):
        return "has an empty, '.' or '..' segment"
    return None
