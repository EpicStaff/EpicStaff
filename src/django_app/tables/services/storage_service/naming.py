"""Free names for storage files and folders, in the same "#N" style copies use."""

from collections.abc import Iterable

from tables.import_export.utils import clean_base_name

# Kept whole when renaming, so "a.tar.gz" becomes "a #2.tar.gz", not "a.tar #2.gz".
_COMPOUND_EXTENSIONS = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")


def split_file_name(name: str) -> tuple[str, str]:
    """Split a file name into stem and extension.

    "report.pdf" -> ("report", ".pdf"), "a.tar.gz" -> ("a", ".tar.gz"),
    ".env" -> (".env", ""), "Makefile" -> ("Makefile", ""), "notes." -> ("notes.", "").
    """
    lowered = name.lower()
    for extension in _COMPOUND_EXTENSIONS:
        if lowered.endswith(extension) and len(name) > len(extension):
            return name[: -len(extension)], name[-len(extension) :]
    dot_index = name.rfind(".")
    if dot_index <= 0 or dot_index == len(name) - 1:
        return name, ""
    return name[:dot_index], name[dot_index:]


def ensure_unique_file_name(path: str, existing_paths: Iterable[str]) -> str:
    """Return `path`, or the same path with a "#N" suffix on its name if a sibling has that name.

    Only paths in the same parent folder count, and a file and a folder with
    the same name clash ("docs" vs "docs/"). The suffix goes before the
    extension: "docs/report.pdf" -> "docs/report #2.pdf". Folders keep any dots:
    "v1.2/" -> "v1.2 #2/". Like ensure_unique_identifier, an existing "#N" is
    stripped first and the lowest free number from 2 is used.
    """
    is_folder = path.endswith("/")
    parent, _, name = path.rstrip("/").rpartition("/")
    taken_names = set()
    for existing in existing_paths:
        existing_parent, _, existing_name = existing.rstrip("/").rpartition("/")
        if existing_parent == parent:
            taken_names.add(existing_name)
    if name not in taken_names:
        return path

    stem, extension = (name, "") if is_folder else split_file_name(name)
    clean_stem = clean_base_name(stem)
    number = 2
    while f"{clean_stem} #{number}{extension}" in taken_names:
        number += 1
    parent_prefix = f"{parent}/" if parent else ""
    return f"{parent_prefix}{clean_stem} #{number}{extension}{'/' if is_folder else ''}"
