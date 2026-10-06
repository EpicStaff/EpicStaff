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


# S3's key limit, and a segment limit since RustFS stores each segment on disk (NAME_MAX).
MAX_KEY_BYTES = 1024
MAX_SEGMENT_BYTES = 255
# StorageFile.path is varchar(1000), counted in characters.
MAX_PATH_CHARS = 1000


def check_new_name(path: str) -> None:
    """Reject a new name with a control character, a blank segment or an over-long segment."""
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in path):
        raise ValueError(f"Name contains a control character: {path!r}")
    segments = path.split("/")
    if any(not segment.strip() for segment in segments):
        raise ValueError(f"Name must not be blank: {path!r}")
    if any(len(segment.encode()) > MAX_SEGMENT_BYTES for segment in segments):
        raise ValueError(f"Name is longer than {MAX_SEGMENT_BYTES} bytes: {path!r}")


def check_path_length(org_id: int, path: str, *, is_folder: bool = False) -> None:
    """Reject a new path too long for its storage key (bytes) or StorageFile row (characters)."""
    marker = 1 if is_folder else 0
    if len(path) + marker > MAX_PATH_CHARS:
        raise ValueError(f"Path is longer than {MAX_PATH_CHARS} characters: {path!r}")
    if len(storage_key(org_id, path).encode()) + marker > MAX_KEY_BYTES:
        raise ValueError(f"Path is longer than {MAX_KEY_BYTES} bytes: {path!r}")


def storage_key(org_id: int, path: str) -> str:
    """Storage key of path in the org's root ("" gives "org_<id>/"); ValueError if it escapes."""
    safe_path = sanitize_storage_path(path, allow_empty=True, allow_leading_slash=True)
    return f"org_{org_id}/{safe_path}"


# Org-root folder holding recycle-bin objects: org_<id>/.recycle-bin/<batch>/<path>.
# Reserved: users and runtime code can't create, read or list anything under it.
TRASH_DIRECTORY = ".recycle-bin"


def is_trash_path(relative_path: str) -> bool:
    """True for the reserved recycle-bin folder and anything under it (org-relative path)."""
    first_segment = relative_path.lstrip("/").split("/", 1)[0]
    return first_segment == TRASH_DIRECTORY
