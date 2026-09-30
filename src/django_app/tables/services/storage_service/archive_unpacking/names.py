DOCUMENT_EXTENSIONS = frozenset(
    {
        # Microsoft Office (OOXML)
        ".xlsx",
        ".xlsm",
        ".xltx",
        ".docx",
        ".docm",
        ".dotx",
        ".pptx",
        ".pptm",
        ".ppsx",
        ".potx",
        # OpenDocument
        ".ods",
        ".odt",
        ".odp",
        ".odg",
        ".odf",
        ".ots",
        ".ott",
        ".otp",
        # Other ZIP-based formats that should not be extracted
        ".epub",
        ".apk",
        ".jar",
        ".war",
        ".xpi",
    }
)


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
    """Whether the name says "archive to unpack" (office/epub/jar files do not)."""
    low = filename.lower()
    if any(low.endswith(doc) for doc in DOCUMENT_EXTENSIONS):
        return False
    return any(low.endswith(sfx) for sfx in ARCHIVE_SUFFIXES)


def strip_archive_suffix(filename: str) -> str:
    """ "bundle.tar.gz" -> "bundle": the name of the folder an archive unpacks into."""
    low = filename.lower()
    for suffix in sorted(ARCHIVE_SUFFIXES, key=len, reverse=True):
        if low.endswith(suffix):
            return filename[: -len(suffix)]
    return filename
