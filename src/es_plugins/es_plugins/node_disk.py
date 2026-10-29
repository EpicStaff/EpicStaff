"""The free space of the node's data volume, `es_plugins_data`, and the two thresholds on it.

- **Install reserve** (2 GiB, 100,000 inodes): below it the agent downloads no package and builds
  no venv; the placement that needed one fails until it is restarted. A package is at most
  `PLUGINS_MAX_PACKAGE_MB` (300 MB by default) and its venv a few times that, so the reserve
  fits the largest install with room to spare, and installing never takes the volume to the
  floor by itself.
- **Floor** (512 MiB, 20,000 inodes): below it the disk watchdog stops the running plugin that
  uses the most. On a default install the volume shares the host's file system with the
  database and Docker's own data, which must keep working; 512 MiB is room for their writes
  while an operator frees space.

A file system without an inode limit (`f_files` of 0, as btrfs reports) is checked for bytes only.
"""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

_MIB = 1024 * 1024
INSTALL_RESERVE_BYTES = 2048 * _MIB
INSTALL_RESERVE_FILES = 100_000
FLOOR_BYTES = 512 * _MIB
FLOOR_FILES = 20_000


class NodeDiskFullError(Exception):
    """The volume is below the install reserve; the message is the placement's last error."""


@dataclass(frozen=True)
class FreeSpace:
    bytes: int
    files: int | None
    """Free inodes, or None on a file system without an inode limit."""


@dataclass(frozen=True)
class FloorBreach:
    by_files: bool
    """True when inodes, not bytes, ran short: the plugin with the most files is stopped."""

    description: str
    free: int
    """What is left of the one that ran short, bytes or inodes."""


class NodeDisk:
    def __init__(
        self,
        path: Path,
        *,
        statvfs: Callable[[Path], os.statvfs_result] = os.statvfs,
    ):
        self._path = path
        self._statvfs = statvfs

    def free(self) -> FreeSpace:
        """What an unprivileged process may still use (`f_bavail`, `f_favail`)."""
        info = self._statvfs(self._path)
        files = info.f_favail if info.f_files else None
        return FreeSpace(bytes=info.f_bavail * info.f_frsize, files=files)

    def check_room_for_install(self) -> None:
        """Raise unless the volume has the install reserve free.

        Raises:
            NodeDiskFullError: It has not; the message says how much is free and needed.
        """
        free = self.free()
        if free.bytes < INSTALL_RESERVE_BYTES:
            raise NodeDiskFullError(
                f"the node's disk has only {_megabytes(free.bytes)} MB free, and installing "
                f"needs {_megabytes(INSTALL_RESERVE_BYTES)} MB: free space on es_plugins_data, "
                "then restart the plugin"
            )
        if free.files is not None and free.files < INSTALL_RESERVE_FILES:
            raise NodeDiskFullError(
                f"the node's disk has only {free.files} free inodes, and installing needs "
                f"{INSTALL_RESERVE_FILES}: free files on es_plugins_data, then restart the plugin"
            )

    def below_floor(self) -> FloorBreach | None:
        free = self.free()
        if free.bytes < FLOOR_BYTES:
            return FloorBreach(False, f"only {_megabytes(free.bytes)} MB free", free.bytes)
        if free.files is not None and free.files < FLOOR_FILES:
            return FloorBreach(True, f"only {free.files} free inodes", free.files)
        return None


def _megabytes(byte_count: int) -> int:
    return byte_count // _MIB
