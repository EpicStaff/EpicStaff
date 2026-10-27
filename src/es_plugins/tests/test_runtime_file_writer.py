import os
import stat

import pytest

from es_plugins.runtime.runtime_file_writer import (
    MAX_RUNTIME_FILE_BYTES,
    RuntimeFileError,
    read_content_descriptor,
    write_runtime_file,
)


@pytest.fixture
def run_directory(tmp_path):
    directory = tmp_path / "weather"
    directory.mkdir(mode=0o711)
    return directory


def test_the_file_is_0400_owned_by_the_uid_and_holds_the_content(run_directory):
    path = write_runtime_file(run_directory, os.getuid(), os.getgid(), b'{"format":1}')

    info = os.stat(path)
    assert stat.S_IMODE(info.st_mode) == 0o400
    assert (info.st_uid, info.st_gid) == (os.getuid(), os.getgid())
    os.chmod(path, 0o600)
    assert path.read_bytes() == b'{"format":1}'
    assert sorted(entry.name for entry in run_directory.iterdir()) == ["runtime.json"]


def test_a_rewrite_replaces_the_file_by_rename(run_directory):
    path = write_runtime_file(run_directory, os.getuid(), os.getgid(), b"old")
    os.chmod(path, 0o600)
    with open(path, "rb") as reader_of_the_old_file:
        old_inode = os.fstat(reader_of_the_old_file.fileno()).st_ino

        write_runtime_file(run_directory, os.getuid(), os.getgid(), b"new")

        # A reader that opened the file before keeps the whole old version.
        assert reader_of_the_old_file.read() == b"old"
    assert os.stat(path).st_ino != old_inode
    os.chmod(path, 0o600)
    assert path.read_bytes() == b"new"
    assert sorted(entry.name for entry in run_directory.iterdir()) == ["runtime.json"]


def test_content_above_the_cap_is_refused_and_nothing_is_written(run_directory):
    with pytest.raises(RuntimeFileError):
        write_runtime_file(
            run_directory, os.getuid(), os.getgid(), b"x" * (MAX_RUNTIME_FILE_BYTES + 1)
        )

    assert list(run_directory.iterdir()) == []


def test_a_symlink_in_place_of_the_directory_is_not_followed(tmp_path, run_directory):
    link = tmp_path / "link"
    link.symlink_to(run_directory)

    with pytest.raises(OSError):
        write_runtime_file(link, os.getuid(), os.getgid(), b"{}")

    assert list(run_directory.iterdir()) == []


@pytest.mark.linux
def test_the_content_is_read_from_a_memfd_from_its_start():
    memory_file = os.memfd_create("runtime-file")
    try:
        os.write(memory_file, b'{"settings":{}}')

        assert read_content_descriptor(memory_file) == b'{"settings":{}}'
    finally:
        os.close(memory_file)


def test_a_pipe_is_refused_as_the_content_source():
    read_end, write_end = os.pipe()
    try:
        with pytest.raises(RuntimeFileError, match="memfd"):
            read_content_descriptor(read_end)
    finally:
        os.close(read_end)
        os.close(write_end)


@pytest.mark.root
def test_root_writes_the_file_for_a_plugin_uid(run_directory):
    os.chown(run_directory, 0, 0)

    path = write_runtime_file(run_directory, 20001, 20001, b'{"format":1}')

    info = os.stat(path)
    assert (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) == (20001, 20001, 0o400)
