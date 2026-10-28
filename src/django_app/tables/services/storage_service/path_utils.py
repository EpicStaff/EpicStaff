# TRASH_DIRECTORY is reserved: storage_key() refuses it, so no API call can reach it.
# Runtime code (agents, sandbox) gets credentials whose policy denies it
# (storage_credentials.policies.build_temporary_policy).
from src.shared.epicstaff_storage.path_safety import sanitize_storage_path
from storage_credentials.resource_names import TRASH_DIRECTORY, org_storage_prefix


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
    """Storage key of path in the org's root ("" gives "org_<id>/").

    Raises:
        ValueError: the path escapes the org root, or is inside the reserved
            recycle-bin folder (every API path is built here).
    """
    safe_path = sanitize_storage_path(path, allow_empty=True, allow_leading_slash=True)
    if is_trash_path(safe_path):
        raise ValueError(f"'{TRASH_DIRECTORY}' is a reserved folder name.")
    return f"{org_storage_prefix(org_id)}/{safe_path}"


def trash_storage_key(org_id: int, batch, path: str) -> str:
    """Key a recycle-bin batch keeps `path` under: org_<id>/.recycle-bin/<batch>/<path>."""
    safe_path = sanitize_storage_path(path, allow_empty=False, allow_leading_slash=True)
    return f"{org_storage_prefix(org_id)}/{TRASH_DIRECTORY}/{batch}/{safe_path}"


def trash_batch_prefix(org_id: int, batch) -> str:
    """Prefix holding every object of one recycle-bin batch."""
    return f"{org_storage_prefix(org_id)}/{TRASH_DIRECTORY}/{batch}/"


def is_trash_path(relative_path: str) -> bool:
    """True for the reserved recycle-bin folder and anything under it (org-relative path)."""
    first_segment = relative_path.lstrip("/").split("/", 1)[0]
    return first_segment == TRASH_DIRECTORY
