import io
import posixpath
import tarfile
import zipfile
from datetime import UTC, datetime

# Every format's archive extension is the format name itself: "tar.gz" -> ".tar.gz".
_TAR_WRITE_MODES = {
    "tar": "w",
    "tar.gz": "w:gz",
    "tar.bz2": "w:bz2",
    "tar.xz": "w:xz",
}
_ARCHIVE_FORMATS = ("zip", *_TAR_WRITE_MODES)

# Every file is one sequential storage read, so a folder of many small files can outlast the
# sandbox timeout long before it reaches the byte limit.
_MAX_FILES = 1000


def _resolve_members(storage, input_path: str, normalized_input: str) -> tuple[list[dict], bool]:
    """Return the files to archive and whether the input is a folder.

    Each member is ``{"path": <storage path>, "name": <path relative to the input folder, or
    the file's base name>, "size": int, "modified": <ISO-8601 string or None>}``.
    An existing but empty folder yields no members; a missing input raises FileNotFoundError.
    """
    entries = storage.walk(input_path)
    if entries:
        prefix = normalized_input + "/"
        members = [
            {
                "path": entry["path"],
                "name": entry["path"][len(prefix) :],
                "size": entry["size"],
                "modified": entry["modified"],
            }
            for entry in sorted(entries, key=lambda entry: entry["path"])
        ]
        return members, True

    try:
        file_info = storage.info(input_path)
    except FileNotFoundError:
        # An empty folder holds only its hidden ".keep" marker, which walk() skips.
        if storage.exists(input_path):
            return [], True
        raise

    member = {
        "path": normalized_input,
        "name": posixpath.basename(normalized_input),
        "size": file_info["size"],
        "modified": file_info["modified"],
    }
    return [member], False


def _default_output_path(normalized_input: str, is_folder: bool, extension: str) -> str:
    parent, name = posixpath.split(normalized_input)
    if not is_folder:
        name = posixpath.splitext(name)[0] or name
    return posixpath.join(parent, name + extension)


def _modified_time(member: dict) -> datetime:
    """The member's stored modified time in UTC, or now when it is missing or unparseable."""
    try:
        modified = datetime.fromisoformat(member["modified"])
    except (TypeError, ValueError):
        return datetime.now(UTC)
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=UTC)
    return modified.astimezone(UTC)


def _build_archive(storage, members: list[dict], archive_format: str, tar_root: str) -> bytes:
    """Pack the members into an archive of ``archive_format``.

    Tar members sit under ``tar_root`` when it is set; zip members always use their own name.
    """
    buffer = io.BytesIO()
    if archive_format == "zip":
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for member in members:
                zip_member = zipfile.ZipInfo(
                    member["name"], date_time=_modified_time(member).timetuple()[:6]
                )
                zip_member.compress_type = zipfile.ZIP_DEFLATED
                # The permissions writestr() gives a member it creates from a plain name.
                zip_member.external_attr = 0o600 << 16
                archive.writestr(zip_member, storage.read_bytes(member["path"]))
    else:
        with tarfile.open(fileobj=buffer, mode=_TAR_WRITE_MODES[archive_format]) as archive:
            for member in members:
                content = storage.read_bytes(member["path"])
                tar_member = tarfile.TarInfo(posixpath.join(tar_root, member["name"]))
                tar_member.size = len(content)
                tar_member.mtime = int(_modified_time(member).timestamp())
                archive.addfile(tar_member, io.BytesIO(content))
    # CPython hands back the buffer's own bytes object here rather than copying it.
    return buffer.getvalue()


def main(
    input_path: str,
    output_path: str | None = None,
    overwrite: bool = False,
    format: str = "zip",
) -> str:
    from epicstaff_storage import EpicStaffStorage
    from epicstaff_storage.path_safety import sanitize_storage_path
    from epicstaff_storage.storage import MAX_LINE_READ_BYTES

    if format not in _ARCHIVE_FORMATS:
        return (
            f"Format '{format}' is not supported. Allowed formats: {', '.join(_ARCHIVE_FORMATS)}."
        )
    extension = f".{format}"

    storage = EpicStaffStorage()
    try:
        normalized_input = sanitize_storage_path(
            input_path, allow_empty=True, allow_leading_slash=True
        )
        if normalized_input == "":
            return "input_path must name a file or folder; the storage root cannot be compressed."

        members, is_folder = _resolve_members(storage, input_path, normalized_input)

        output_path_was_defaulted = not output_path
        if output_path_was_defaulted:
            output_path = _default_output_path(normalized_input, is_folder, extension)
        if not output_path.endswith(extension):
            return (
                f"output_path '{output_path}' must end with '{extension}' for the "
                f"'{format}' format."
            )

        # A previous archive saved inside the input folder must not be packed into the new one.
        normalized_output = sanitize_storage_path(
            output_path, allow_empty=True, allow_leading_slash=True
        )
        if not is_folder and normalized_output == normalized_input:
            if output_path_was_defaulted:
                return (
                    f"The default output path '{output_path}' is the input file itself. "
                    "Pass an explicit output_path that differs from input_path."
                )
            return "output_path must differ from input_path."
        members = [member for member in members if member["path"] != normalized_output]
        if not members:
            return f"Folder '{input_path}' contains no files to compress."

        if len(members) > _MAX_FILES:
            return (
                f"Input '{input_path}' holds {len(members)} files, over the {_MAX_FILES}-file "
                "compression limit. Narrow input_path to a subfolder with fewer files."
            )

        total_size = sum(member["size"] for member in members)
        if total_size > MAX_LINE_READ_BYTES:
            return (
                f"Input '{input_path}' totals {total_size} bytes, over the "
                f"{MAX_LINE_READ_BYTES // (1024 * 1024)} MB compression limit. "
                "Compress a smaller folder or a single file instead."
            )

        if not overwrite and storage.exists(output_path):
            return (
                f"Output '{output_path}' already exists and overwrite is false. "
                "Set overwrite=true to replace it, or choose another output_path."
            )

        # Like the local-filesystem compressor this replaces: tar formats keep a folder's files
        # under a top-level directory named after it, zip puts them at the archive root.
        tar_root = posixpath.basename(normalized_input) if is_folder else ""
        archive = _build_archive(storage, members, format, tar_root)
        storage.write_bytes(output_path, archive)
    except FileNotFoundError:
        return f"Input not found: {input_path}."
    except PermissionError as e:
        return str(e)
    except ValueError as e:
        return str(e)
    except RuntimeError as e:
        return str(e)

    return (
        f"Compressed {len(members)} file(s) from '{input_path}' into "
        f"'{output_path}' ({len(archive)} bytes)."
    )
