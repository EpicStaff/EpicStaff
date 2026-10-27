"""Reading a control file the child could have tampered with.

The child has write access to its execution dir and the worker reads these files as
root, so a symlink, a FIFO or a huge file must be refused, never followed or waited on.
Real files, links and FIFOs on disk; nothing is faked.
"""

import os
import threading

import pytest

from worker.infrastructure.execution.control_files import (
    UnsafeControlFileError,
    read_control_file,
)

SECRET = "root-only secret"
MAX_BYTES = 1024


def test_a_regular_file_is_read(tmp_path):
    path = tmp_path / "output.txt"
    path.write_text('{"echo": "x"}', encoding="utf-8")

    assert read_control_file(path, max_bytes=MAX_BYTES) == '{"echo": "x"}'


def test_a_missing_file_reads_as_none(tmp_path):
    assert read_control_file(tmp_path / "output.txt", max_bytes=MAX_BYTES) is None


@pytest.mark.parametrize("target_exists", [True, False], ids=["to-a-file", "dangling"])
def test_a_symlink_is_refused_and_its_target_never_read(tmp_path, target_exists):
    outside = tmp_path / "outside" / "secret.txt"
    if target_exists:
        outside.parent.mkdir()
        outside.write_text(SECRET, encoding="utf-8")
    exec_dir = tmp_path / "exec"
    exec_dir.mkdir()
    (exec_dir / "output.txt").symlink_to(outside)

    with pytest.raises(UnsafeControlFileError) as raised:
        read_control_file(exec_dir / "output.txt", max_bytes=MAX_BYTES)

    assert SECRET not in str(raised.value)
    assert str(outside) not in str(raised.value)


def test_a_fifo_is_refused_without_blocking(tmp_path):
    path = tmp_path / "output.txt"
    os.mkfifo(path)
    outcome = {}

    def read():
        try:
            outcome["value"] = read_control_file(path, max_bytes=MAX_BYTES)
        except UnsafeControlFileError as error:
            outcome["error"] = error

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    reader.join(timeout=5)
    if reader.is_alive():
        # Release the blocked open so the thread can finish, then fail the test.
        os.close(os.open(path, os.O_WRONLY | os.O_NONBLOCK))
        reader.join(timeout=5)
        pytest.fail("Reading a FIFO blocked")

    assert "error" in outcome, outcome


@pytest.mark.parametrize(
    ("size", "refused"), [(10, False), (11, True)], ids=["at-the-limit", "one-over"]
)
def test_a_file_over_the_size_limit_is_refused(tmp_path, size, refused):
    path = tmp_path / "output.txt"
    path.write_text("x" * size, encoding="utf-8")

    if refused:
        with pytest.raises(UnsafeControlFileError):
            read_control_file(path, max_bytes=10)
    else:
        assert read_control_file(path, max_bytes=10) == "x" * size
