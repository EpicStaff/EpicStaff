from tables.services.storage_service.manager import _DOCUMENT_EXTENSIONS

ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tgz",
    ".taz",
    ".tar.gz",
    ".tar.bz2",
    ".tbz",
    ".tbz2",
    ".tar.xz",
    ".txz",
)


def is_archive_name(filename: str) -> bool:
    low = filename.lower()
    if any(low.endswith(doc) for doc in _DOCUMENT_EXTENSIONS):
        return False
    return any(low.endswith(sfx) for sfx in ARCHIVE_SUFFIXES)
