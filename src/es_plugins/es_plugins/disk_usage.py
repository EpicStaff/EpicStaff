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

The scan costs at most about the limits it checks: it stops as soon as one is passed (the
totals are then lower bounds, already over the limit). It also stops when it cannot see
everything: a directory the plugin made unreadable, nesting deeper than `MAX_DEPTH`, a process
whose open files it may not inspect. The result then names the problem; the agent treats a
plugin it cannot measure like one over its limit, so hiding data does not pay.
"""

import json
import os
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
    """Measure `directory` and the deleted files the UID's processes hold open on its disk.

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
        _add_unlinked_open_files(
            uid, info.st_dev, tally, process_table or ProcessTable(proc_root), proc_root
        )
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
