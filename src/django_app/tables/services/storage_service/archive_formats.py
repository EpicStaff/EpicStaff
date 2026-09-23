import os
import tarfile
import zipfile

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
    low = filename.lower()
    if any(low.endswith(doc) for doc in DOCUMENT_EXTENSIONS):
        return False
    return any(low.endswith(sfx) for sfx in ARCHIVE_SUFFIXES)


def is_archive_content(file_object, filename: str = "") -> bool:
    """Whether the bytes really are an extractable archive, restoring the file position.

    The name-based check decides the route before the body arrives; this one runs
    once the bytes are buffered, so a plain file carrying an archive suffix is
    still stored as a file instead of failing extraction.
    """
    if os.path.splitext(filename)[1].lower() in DOCUMENT_EXTENSIONS:
        return False
    pos = file_object.tell()
    result = zipfile.is_zipfile(file_object)
    if not result:
        file_object.seek(pos)
        try:
            result = tarfile.is_tarfile(file_object)
        except Exception:
            result = False
    file_object.seek(pos)
    return result
