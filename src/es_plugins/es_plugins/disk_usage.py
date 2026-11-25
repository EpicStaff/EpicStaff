"""How much disk a plugin's data directory uses: bytes allocated and files.

The scan runs in the launcher's measuring helper (see `es_plugins.launcher.disk_measurement`),
with the plugin's filesystem identity; the agent gets the result as JSON. It never follows a
symlink: entries are examined with `lstat` semantics and directories are opened one level at a
time below an open directory, with `O_NOFOLLOW`.

What it counts:

- every entry under the directory, files, directories and links alike, as one file each (a
  hard-linked file once): each takes an inode;
- their allocated blocks (`st_blocks`, so a sparse file counts what it really takes), a
  hard-linked file once, as the bytes;
- regular files on the same file system that a process of the plugin's UID still holds open
  after deleting them, from `/proc/<pid>/fd`: they take space a directory scan cannot see.

A deleted file in the directory that a process of the UID keeps only mapped, with no descriptor
open on it, makes the plugin unmeasurable. `/proc/<pid>/maps` shows such a file but not its size
(`/proc/<pid>/map_files`, which would, needs a capability the node does not hold), and a mapping
of one page keeps a file of any size allocated. Code rarely does it: Python's `mmap` keeps a
descriptor of its own, so its files count through `/proc/<pid>/fd`, once, by their blocks.
`maps` names a file's device as its mount does (`/proc/self/mountinfo`), which on btrfs is not
what `stat` reports, so the mount is matched.

The scan costs at most about the limits it checks: it stops as soon as one is passed (the
totals are then lower bounds, already over the limit). It also stops when it cannot see
everything: a directory the plugin made unreadable, nesting deeper than `MAX_DEPTH`, a process
whose open files it may not inspect, a deleted file kept only mapped. The result then names the
problem; the agent treats a plugin it cannot measure like one over its limit, so hiding data does
not pay.
"""

import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from es_plugins.process_table import ProcessTable

MAX_DEPTH = 128
_BLOCK_BYTES = 512
_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@dataclass(frozen=True)
class DiskUsage:
    bytes: int
    files: int
    problem: str | None = None
    """Why the plugin's disk use could not be measured completely, or None."""

    def to_json(self) -> bytes:
        return json.dumps(asdict(self)).encode()

    @classmethod
    def from_json(cls, data: bytes) -> "DiskUsage":
        document = json.loads(data)
        return cls(
            bytes=int(document["bytes"]),
            files=int(document["files"]),
            problem=document.get("problem"),
        )


class _LimitPassedError(Exception):
    pass


class _UnmeasurableError(Exception):
    pass


class _Tally:
    def __init__(self, max_bytes: int, max_files: int):
        self._max_bytes = max_bytes
        self._max_files = max_files
        self._hard_linked: set[tuple[int, int]] = set()
        self.bytes = 0
        self.files = 0

    def add_entry(self, info: os.stat_result) -> None:
        if not self._first_time(info):
            return
        self.files += 1
        self.bytes += info.st_blocks * _BLOCK_BYTES
        self._check()

    def add_unlinked(self, info: os.stat_result) -> None:
        if not self._first_time(info):
            return
        self.bytes += info.st_blocks * _BLOCK_BYTES
        self._check()

    def counted(self, file: tuple[int, int]) -> bool:
        """Whether the file with this (device, inode), deleted or hard-linked, was counted."""
        return file in self._hard_linked

    def _first_time(self, info: os.stat_result) -> bool:
        if stat.S_ISDIR(info.st_mode) or info.st_nlink == 1:
            return True
        key = (info.st_dev, info.st_ino)
        if key in self._hard_linked:
            return False
        self._hard_linked.add(key)
        return True

    def _check(self) -> None:
        if self.bytes > self._max_bytes or self.files > self._max_files:
            raise _LimitPassedError


def measure_plugin_data(
    directory: Path,
    uid: int,
    *,
    max_bytes: int,
    max_files: int,
    process_table: ProcessTable | None = None,
    proc_root: Path = Path("/proc"),
) -> DiskUsage:
    """Measure `directory`, and the deleted files on its disk the UID's processes hold open.

    A directory that does not exist (yet) uses nothing.
    """
    tally = _Tally(max_bytes, max_files)
    try:
        root = os.open(directory, _DIRECTORY_FLAGS)
    except FileNotFoundError:
        return DiskUsage(bytes=0, files=0)
    except OSError as error:
        return DiskUsage(0, 0, problem=f"its data directory cannot be opened: {error.strerror}")
    try:
        info = os.fstat(root)
        tally.add_entry(info)
        _walk(root, ".", 0, tally)
        table = process_table or ProcessTable(proc_root)
        # Open files first: a deleted file also mapped is then counted, by its blocks.
        _add_unlinked_open_files(uid, info.st_dev, tally, table, proc_root)
        _refuse_files_kept_only_mapped(uid, directory, tally, table, proc_root)
    except _LimitPassedError:
        pass
    except _UnmeasurableError as unmeasurable:
        return DiskUsage(tally.bytes, tally.files, problem=str(unmeasurable))
    finally:
        os.close(root)
    return DiskUsage(tally.bytes, tally.files)


def _walk(directory: int, relative: str, depth: int, tally: _Tally) -> None:
    if depth >= MAX_DEPTH:
        raise _UnmeasurableError(f"{relative} is nested deeper than {MAX_DEPTH} directories")
    subdirectories = []
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                except FileNotFoundError:
                    continue  # removed while being scanned
                tally.add_entry(info)
                if stat.S_ISDIR(info.st_mode):
                    subdirectories.append(entry.name)
    except PermissionError:
        raise _UnmeasurableError(f"{relative} cannot be read") from None
    for name in subdirectories:
        path = f"{relative}/{name}" if relative != "." else name
        try:
            child = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory)
        except (FileNotFoundError, NotADirectoryError):
            continue  # removed, or replaced by a file, while being scanned
        except PermissionError:
            raise _UnmeasurableError(f"{path} cannot be read") from None
        except OSError:
            continue  # replaced by a symlink (ELOOP): not followed
        try:
            _walk(child, path, depth + 1, tally)
        finally:
            os.close(child)


def _add_unlinked_open_files(
    uid: int, device: int, tally: _Tally, process_table: ProcessTable, proc_root: Path
) -> None:
    for pid in process_table.living_pids_of_uid(uid):
        descriptors = proc_root / str(pid) / "fd"
        try:
            names = os.listdir(descriptors)
        except FileNotFoundError:
            continue  # exited meanwhile
        except PermissionError:
            raise _UnmeasurableError(
                f"process {pid} does not let the node see its open files"
            ) from None
        for name in names:
            try:
                info = os.stat(descriptors / name)
            except OSError:
                continue  # closed meanwhile, or not a file
            if stat.S_ISREG(info.st_mode) and info.st_nlink == 0 and info.st_dev == device:
                tally.add_unlinked(info)


def _refuse_files_kept_only_mapped(
    uid: int, directory: Path, tally: _Tally, process_table: ProcessTable, proc_root: Path
) -> None:
    pids = process_table.living_pids_of_uid(uid)
    if not pids:
        return
    device = _mount_device(directory, proc_root / "self" / "mountinfo")
    inside = os.fsencode(directory) + b"/"
    for pid in pids:
        try:
            with open(proc_root / str(pid) / "maps", "rb") as maps:
                kept_only_mapped = any(
                    file is not None and not tally.counted(file)
                    for file in (_deleted_file_mapped(line, device, inside) for line in maps)
                )
        except (FileNotFoundError, ProcessLookupError):
            continue  # exited meanwhile
        except PermissionError:
            raise _UnmeasurableError(
                f"process {pid} does not let the node see its mapped files"
            ) from None
        if kept_only_mapped:
            raise _UnmeasurableError(
                f"process {pid} keeps a deleted file mapped without an open descriptor, "
                "so its size cannot be measured"
            )


def _deleted_file_mapped(line: bytes, device: int, inside: bytes) -> tuple[int, int] | None:
    """The (device, inode) a line of `/proc/<pid>/maps` maps, if it is a deleted file on `device`
    whose path began with `inside`; None for any other line."""
    fields = line.split(maxsplit=5)
    if len(fields) < 6:
        return None
    name = fields[5].rstrip(b"\n")
    if not name.endswith(b" (deleted)") or not name.startswith(inside):
        return None
    major, _, minor = fields[3].partition(b":")
    if os.makedev(int(major, 16), int(minor, 16)) != device:
        return None
    return device, int(fields[4])


def _mount_device(directory: Path, mountinfo: Path) -> int:
    """The device of the mount `directory` is on, as `/proc/self/mountinfo` shows it."""
    path = str(directory)
    deepest, device = "", ""
    for line in mountinfo.read_text().splitlines():
        fields = line.split()
        mount_point = _unescape_mount_path(fields[4])
        holds = mount_point in ("/", path) or path.startswith(mount_point + "/")
        # Every mount holding it is a prefix of its path, so the longest is the deepest; of mounts
        # on the same point, the last listed is the one on top.
        if holds and len(mount_point) >= len(deepest):
            deepest, device = mount_point, fields[2]
    major, _, minor = device.partition(":")
    return os.makedev(int(major), int(minor))


def _unescape_mount_path(text: str) -> str:
    # mountinfo writes a space, tab, newline and backslash in a path as `\ooo`, in octal.
    return re.sub(r"\\([0-7]{3})", lambda escaped: chr(int(escaped.group(1), 8)), text)
