"""Write a plugin's runtime file: mode 0400, owned by the plugin's UID, replaced atomically.

The file holds the plugin's secret settings, so only its UID may read it (the agent cannot
either). The launcher writes it into `/run/es_plugins/<id>/`, a directory root owns, as a
temporary file that it fills, `fchmod`s, `fchown`s and syncs before renaming it over the old
one. A plugin that reads the file sees either the old content or the new, never a part, and
an SDK that watches the file's mtime picks the new one up.
"""

import os
import secrets
import stat
from pathlib import Path

from es_plugins.descriptors import write_all
from es_plugins.layout import RUNTIME_FILE_NAME

MAX_RUNTIME_FILE_BYTES = 1024 * 1024


class RuntimeFileError(Exception):
    """The runtime file's content could not be read or written."""


def read_content_descriptor(descriptor: int) -> bytes:
    """Read the whole content of a memfd (or any regular file) from its start.

    Raises:
        RuntimeFileError: The descriptor is not a regular file, or holds more than
            `MAX_RUNTIME_FILE_BYTES`.
    """
    if not stat.S_ISREG(os.fstat(descriptor).st_mode):
        raise RuntimeFileError("the runtime file content must come in a memfd")
    content = bytearray()
    offset = 0
    while chunk := os.pread(descriptor, 64 * 1024, offset):
        content += chunk
        offset += len(chunk)
        if len(content) > MAX_RUNTIME_FILE_BYTES:
            raise RuntimeFileError(
                f"the runtime file is larger than {MAX_RUNTIME_FILE_BYTES} bytes"
            )
    return bytes(content)


def write_runtime_file(directory: Path, uid: int, gid: int, content: bytes) -> Path:
    """Replace `directory/runtime.json` with `content`, readable only by `uid`.

    `directory` must be owned by the caller, so the temporary file can be created and renamed
    there and nobody else can interfere in between.
    """
    if len(content) > MAX_RUNTIME_FILE_BYTES:
        raise RuntimeFileError(f"the runtime file is larger than {MAX_RUNTIME_FILE_BYTES} bytes")
    directory_descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        temporary_name = f".{RUNTIME_FILE_NAME}.{secrets.token_hex(8)}"
        descriptor = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o400,
            dir_fd=directory_descriptor,
        )
        try:
            write_all(descriptor, content)
            os.fchmod(descriptor, 0o400)
            os.fchown(descriptor, uid, gid)
            os.fsync(descriptor)
        except BaseException:
            os.unlink(temporary_name, dir_fd=directory_descriptor)
            raise
        finally:
            os.close(descriptor)
        os.rename(
            temporary_name,
            RUNTIME_FILE_NAME,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
    return directory / RUNTIME_FILE_NAME
