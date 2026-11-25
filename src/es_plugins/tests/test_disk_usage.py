import contextlib
import ctypes
import mmap
import os
from pathlib import Path

import pytest

from es_plugins import disk_usage
from es_plugins.disk_usage import DiskUsage, measure_plugin_data
from tests.helpers import OwnProcessTable

MIB = 1024 * 1024
LIMITS = {"max_bytes": 10**12, "max_files": 10**9}


@pytest.fixture
def no_processes(tmp_path):
    """A /proc with no process: only the directory tree is measured."""
    proc_root = tmp_path / "proc"
    proc_root.mkdir()
    return {"proc_root": proc_root}


def measure(home, **options):
    return measure_plugin_data(home, os.getuid(), **{**LIMITS, **options})


def write_file(path, size):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as file:
        file.write(b"\x01" * size)


def test_every_entry_counts_as_a_file_and_its_allocated_blocks_as_bytes(tmp_path, no_processes):
    home = tmp_path / "home"
    write_file(home / "data.bin", 3 * MIB)
    write_file(home / "cache" / "a" / "small", 10)

    usage = measure(home, **no_processes)

    # home, data.bin, cache, cache/a, cache/a/small
    assert usage.files == 5
    assert 3 * MIB <= usage.bytes < 4 * MIB
    assert usage.problem is None


def test_a_sparse_file_counts_what_it_takes_not_its_size(tmp_path, no_processes):
    home = tmp_path / "home"
    home.mkdir()
    with open(home / "sparse", "wb") as file:
        file.truncate(500 * MIB)

    assert measure(home, **no_processes).bytes < MIB


def test_symlinks_are_counted_as_links_and_never_followed(tmp_path, no_processes):
    outside = tmp_path / "outside"
    write_file(outside / "big", 4 * MIB)
    for number in range(20):
        write_file(outside / "many" / str(number), 1)
    home = tmp_path / "home"
    home.mkdir()
    (home / "to-a-file").symlink_to(outside / "big")
    (home / "to-a-directory").symlink_to(outside / "many")

    usage = measure(home, **no_processes)

    assert usage.files == 3
    assert usage.bytes < MIB


def test_a_hard_linked_file_counts_once(tmp_path, no_processes):
    home = tmp_path / "home"
    write_file(home / "original", 2 * MIB)
    for number in range(5):
        os.link(home / "original", home / f"link-{number}")

    usage = measure(home, **no_processes)

    assert usage.files == 2
    assert usage.bytes < 3 * MIB


def test_the_scan_stops_once_a_limit_is_passed(tmp_path, no_processes):
    home = tmp_path / "home"
    for number in range(200):
        write_file(home / f"file-{number}", 1)

    usage = measure(home, max_files=10, **no_processes)

    assert usage.files == 11
    assert usage.problem is None


def test_a_missing_directory_uses_nothing(tmp_path, no_processes):
    assert measure(tmp_path / "never-created", **no_processes) == DiskUsage(0, 0)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads every directory; the helper reads as the plugin")
def test_a_directory_the_plugin_made_unreadable_makes_it_unmeasurable(tmp_path, no_processes):
    home = tmp_path / "home"
    write_file(home / "hidden" / "data", MIB)
    os.chmod(home / "hidden", 0o000)
    try:
        usage = measure(home, **no_processes)
    finally:
        os.chmod(home / "hidden", 0o700)

    assert usage.problem == "hidden cannot be read"


def test_nesting_deeper_than_the_scan_goes_makes_it_unmeasurable(
    tmp_path, no_processes, monkeypatch
):
    monkeypatch.setattr(disk_usage, "MAX_DEPTH", 3)
    home = tmp_path / "home"
    (home / "a" / "b" / "c" / "d").mkdir(parents=True)

    usage = measure(home, **no_processes)

    assert usage.problem == "a/b/c is nested deeper than 3 directories"


def test_a_directory_name_that_is_not_utf8_shows_its_bytes_in_the_problem(
    tmp_path, no_processes, monkeypatch
):
    monkeypatch.setattr(disk_usage, "MAX_DEPTH", 2)
    home = tmp_path / "home"
    home.mkdir()
    os.makedirs(os.path.join(os.fsencode(home), b"caf\xe9", b"\xff", b"deeper"))

    usage = measure(home, **no_processes)

    assert usage.problem == "caf\\xe9/\\xff is nested deeper than 2 directories"


@pytest.mark.linux
def test_a_deleted_file_a_process_of_the_uid_holds_open_counts(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    held = open(home / "deleted-but-open", "wb")  # noqa: SIM115
    try:
        held.write(b"\x01" * (5 * MIB))
        held.flush()
        os.fsync(held.fileno())
        os.unlink(home / "deleted-but-open")

        usage = measure(home, process_table=OwnProcessTable())
    finally:
        held.close()

    assert usage.files == 1
    assert usage.bytes >= 5 * MIB


_libc = ctypes.CDLL(None, use_errno=True)
_libc.mmap.restype = ctypes.c_void_p
_libc.mmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_long]
_libc.munmap.argtypes = [ctypes.c_void_p, ctypes.c_size_t]


@contextlib.contextmanager
def deleted_and_mapped(path, size, *, mapped=None, keep_open=False):
    """A file of `size` bytes, mapped (its first `mapped` bytes), deleted, and its descriptor closed
    unless `keep_open`: only the mapping keeps it. Python's own mmap would keep a descriptor."""
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    os.write(descriptor, b"\x01" * size)
    os.fsync(descriptor)
    length = mapped or size
    address = _libc.mmap(None, length, mmap.PROT_READ, mmap.MAP_SHARED, descriptor, 0)
    assert address not in (None, ctypes.c_void_p(-1).value), os.strerror(ctypes.get_errno())
    os.unlink(path)
    if not keep_open:
        os.close(descriptor)
    try:
        yield
    finally:
        _libc.munmap(address, length)
        if keep_open:
            os.close(descriptor)


MAPPED_ONLY = "keeps a deleted file mapped without an open descriptor"


@pytest.mark.linux
@pytest.mark.parametrize("mapped", [None, 4096])
def test_a_deleted_file_kept_only_by_a_mapping_makes_the_use_unmeasurable(tmp_path, mapped):
    # Its size cannot be read, and a mapping of one page could keep a file of any size.
    home = tmp_path / "home"
    home.mkdir()

    with deleted_and_mapped(home / "kept", 5 * MIB, mapped=mapped):
        usage = measure(home, process_table=OwnProcessTable())

    assert usage.problem == f"process {os.getpid()} {MAPPED_ONLY}, so its size cannot be measured"


@pytest.mark.linux
def test_a_deleted_file_held_open_and_mapped_counts_once_by_its_blocks(tmp_path):
    home = tmp_path / "home"
    home.mkdir()

    with deleted_and_mapped(home / "both", 5 * MIB, mapped=4096, keep_open=True):
        usage = measure(home, process_table=OwnProcessTable())

    assert usage.problem is None
    assert 5 * MIB <= usage.bytes < 6 * MIB


@pytest.mark.linux
def test_pythons_mmap_keeps_a_descriptor_so_its_deleted_file_counts_by_its_blocks(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    with open(home / "mapped", "wb+") as file:
        file.write(b"\x01" * (5 * MIB))
        file.flush()
        mapped = mmap.mmap(file.fileno(), 5 * MIB)
    os.unlink(home / "mapped")
    try:
        usage = measure(home, process_table=OwnProcessTable())
    finally:
        mapped.close()

    assert usage.problem is None
    assert 5 * MIB <= usage.bytes < 6 * MIB


@pytest.mark.linux
def test_a_mapped_file_that_is_not_deleted_counts_by_its_blocks_alone(tmp_path):
    home = tmp_path / "home"
    write_file(home / "live", 5 * MIB)
    descriptor = os.open(home / "live", os.O_RDONLY)
    address = _libc.mmap(None, 5 * MIB, mmap.PROT_READ, mmap.MAP_SHARED, descriptor, 0)
    os.close(descriptor)
    try:
        usage = measure(home, process_table=OwnProcessTable())
    finally:
        _libc.munmap(address, 5 * MIB)

    assert usage.problem is None
    assert 5 * MIB <= usage.bytes < 6 * MIB


@pytest.mark.linux
def test_a_deleted_file_mapped_outside_the_data_directory_is_not_its_concern(tmp_path):
    # The node's own files on the same volume (a plugin's code and venv) are not the plugin's data.
    home = tmp_path / "home"
    home.mkdir()

    with deleted_and_mapped(tmp_path / "beside-home", 5 * MIB):
        usage = measure(home, process_table=OwnProcessTable())

    assert usage.problem is None
    assert usage.bytes < MIB


@pytest.mark.linux
def test_a_mapped_deleted_file_on_another_file_system_does_not_count(tmp_path):
    other = Path("/dev/shm")
    if not os.access(other, os.W_OK) or other.stat().st_dev == tmp_path.stat().st_dev:
        pytest.skip("needs a writable /dev/shm on a file system of its own")
    home = tmp_path / "home"
    home.mkdir()

    with deleted_and_mapped(other / f"elsewhere-{os.getpid()}", 5 * MIB):
        usage = measure(home, process_table=OwnProcessTable())

    assert usage.problem is None
    assert usage.bytes < MIB


def test_a_mapped_deleted_file_is_matched_by_the_device_its_mount_shows_not_by_stat(tmp_path):
    # As on a btrfs subvolume: stat() gives files an anonymous device of the subvolume, while
    # /proc/<pid>/maps and /proc/self/mountinfo name the file system's own (here 0:45, 2d in hex).
    home = tmp_path / "home"
    home.mkdir()
    proc_root = tmp_path / "proc"
    (proc_root / "self").mkdir(parents=True)
    (proc_root / "self" / "mountinfo").write_text(
        "21 1 8:1 / / rw - ext4 /dev/sda1 rw\n"
        f"35 21 0:45 /@data {tmp_path} rw,relatime - btrfs /dev/sdb rw\n"
    )
    process = proc_root / "4242"
    (process / "fd").mkdir(parents=True)
    (process / "status").write_text(f"Name:\tpython\nState:\tS (sleeping)\nUid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n")
    (process / "maps").write_text(
        f"7f0000000000-7f0000001000 r--s 00000000 00:2d 1234 {home}/kept (deleted)\n"
        "7f0000600000-7f0000700000 r--s 00000000 08:01 99 /usr/lib/libc.so.6 (deleted)\n"
    )

    usage = measure(home, proc_root=proc_root)

    assert usage.problem == f"process 4242 {MAPPED_ONLY}, so its size cannot be measured"


def test_the_result_travels_as_json():
    usage = DiskUsage(bytes=123, files=4, problem="hidden cannot be read")

    assert DiskUsage.from_json(usage.to_json()) == usage
