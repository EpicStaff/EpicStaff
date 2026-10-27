"""Reads a control file the child left in its execution dir, without trusting it.

The child can write to its own execution dir, so it can replace a control file
(output.txt, storage_mutations.json) with a symlink or a FIFO. The worker reads these
files as root: a plain read would follow the link to any file in the container, or
block forever on the FIFO.
"""

import errno
import os
import stat
from pathlib import Path

__all__ = ["UnsafeControlFileError", "read_control_file"]


class UnsafeControlFileError(Exception):
    """The control file is a symlink, not a regular file, or too large to read."""


def read_control_file(path: Path, *, max_bytes: int) -> str | None:
    """Return the UTF-8 text of a regular file the child wrote, or None if it is missing.

    Raises:
        UnsafeControlFileError: The file is a symlink, not a regular file, or larger
            than ``max_bytes``. The message never names where a link points.
    """
    try:
        # O_NONBLOCK: opening a FIFO with no writer would otherwise block forever.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as error:
        if error.errno == errno.ELOOP:
            raise UnsafeControlFileError("the file is a symbolic link") from None
        raise

    with os.fdopen(fd, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise UnsafeControlFileError("the file is not a regular file")
        data = file.read(max_bytes + 1)

    if len(data) > max_bytes:
        raise UnsafeControlFileError(f"the file is larger than {max_bytes} bytes")
    return data.decode("utf-8")
