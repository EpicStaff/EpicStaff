import posixpath


def sanitize_storage_path(path: str, *, allow_empty: bool) -> str:
    """Normalize a caller-provided path and raise ValueError if it can escape the target folder."""
    if not path:
        if allow_empty:
            return ""
        raise ValueError("Path must not be empty")

    if "\x00" in path:
        raise ValueError(f"Path contains a null byte: {path!r}")

    normalized = posixpath.normpath(path.replace("\\", "/"))

    if normalized == "." or normalized.strip("/") == "":
        if allow_empty:
            return ""
        raise ValueError("Path must not be empty")

    if (
        posixpath.isabs(normalized)
        or normalized == ".."
        or normalized.startswith("../")
    ):
        raise ValueError(f"Path escapes the target folder: {path!r}")

    return normalized
