import posixpath


def sanitize_storage_path(
    path: str, *, allow_empty: bool, allow_leading_slash: bool = False
) -> str:
    """Normalize a caller-provided path and raise ValueError if it can escape the target folder.

    ``allow_leading_slash`` controls how a leading ``/`` is treated:

    - ``False`` (default) — an absolute-looking path is rejected as an escape
      attempt. Use this for inputs where an absolute path is never legitimate,
      e.g. archive member names (a zip/tar entry named ``/etc/passwd`` is the
      classic zip-slip attack).
    - ``True`` — a leading ``/`` is stripped and the path is treated as
      root-relative, matching the API's documented convention of storage
      paths like ``/reports/`` (see ``StoragePathQuerySerializer.path``
      help text). Traversal segments (``..``) are still rejected after the
      slash is stripped, so this does not weaken escape protection.
    """
    if not path:
        if allow_empty:
            return ""
        raise ValueError("Path must not be empty")

    if "\x00" in path:
        raise ValueError(f"Path contains a null byte: {path!r}")

    normalized_input = path.replace("\\", "/")
    if allow_leading_slash:
        normalized_input = normalized_input.lstrip("/")

    normalized = posixpath.normpath(normalized_input)

    if normalized == "." or normalized.strip("/") == "":
        if allow_empty:
            return ""
        raise ValueError("Path must not be empty")

    if posixpath.isabs(normalized) or normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"Path escapes the target folder: {path!r}")

    return normalized


def check_new_name(path: str) -> None:
    """ValueError for a name that stores fine but breaks later: a control character
    (a download can't put it in Content-Disposition) or a blank segment. Only for
    names being created, so objects that already have such names stay reachable."""
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
        raise ValueError(f"Name contains a control character: {path!r}")
    if any(not segment.strip() for segment in path.split("/")):
        raise ValueError(f"Name must not be blank: {path!r}")
