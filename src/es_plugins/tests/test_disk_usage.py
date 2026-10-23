import os

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


def test_the_result_travels_as_json():
    usage = DiskUsage(bytes=123, files=4, problem="hidden cannot be read")

    assert DiskUsage.from_json(usage.to_json()) == usage
