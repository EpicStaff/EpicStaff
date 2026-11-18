"""Executable extensions are refused as write targets, whatever the env vars say."""

import pytest

from epicstaff_storage import StoragePermissionError

from conftest import allow_paths, restrict_actions

BLOCKED_NAMES = [
    "tool.exe",
    "tool.EXE",
    "run.CoMmAnD",
    "scripts/deploy.sh",
    "a.exe.sh",
    "lib.dylib",
    "app.jar",
]

WRITE_TARGETS = [
    ("write", lambda s, name: s.write(name, "x")),
    ("write_bytes", lambda s, name: s.write_bytes(name, b"x")),
    ("copy_dst", lambda s, name: s.copy("docs/source.txt", name)),
    ("move_dst", lambda s, name: s.move("docs/source.txt", name)),
    ("append_text", lambda s, name: s.append_text(name, "x")),
    ("insert_lines", lambda s, name: s.insert_lines(name, 1, "x")),
]


@pytest.mark.parametrize("name", BLOCKED_NAMES)
@pytest.mark.parametrize(("operation", "call"), WRITE_TARGETS, ids=[op[0] for op in WRITE_TARGETS])
def test_blocked_extension_is_refused_and_nothing_is_stored(
    storage, fake_client, name, operation, call
):
    fake_client.put_object(Bucket="b", Key="docs/source.txt", Body=b"data")

    with pytest.raises(StoragePermissionError, match="executable"):
        call(storage, name)

    assert set(fake_client.objects) == {"docs/source.txt"}


def test_edit_line_on_an_existing_blocked_file_is_refused(storage, fake_client):
    fake_client.put_object(Bucket="b", Key="old.sh", Body=b"echo hi")

    with pytest.raises(StoragePermissionError, match="'.sh'"):
        storage.edit_line("old.sh", 1, "echo hi", "echo bye")

    assert fake_client.objects["old.sh"]["Body"] == b"echo hi"


@pytest.mark.parametrize("name", ["notes.exe.txt", "exe", "shell.sh.md", "archive.zip", "a.EXEC"])
def test_names_whose_last_extension_is_not_blocked_are_written(storage, fake_client, name):
    storage.write(name, "x")

    assert name in fake_client.objects


def test_blocked_extension_is_refused_with_actions_and_paths_that_would_allow_the_write(
    monkeypatch, storage
):
    allow_paths(monkeypatch, ["sessions/7/"])
    restrict_actions(monkeypatch, ["read", "write", "delete"], own_paths=["sessions/7/"])

    with pytest.raises(StoragePermissionError, match="'.exe'"):
        storage.write("sessions/7/payload.exe", "x")


def test_reading_and_deleting_an_existing_blocked_file_is_still_allowed(storage, fake_client):
    fake_client.put_object(Bucket="b", Key="old.sh", Body=b"echo hi")

    assert storage.read("old.sh") == "echo hi"
    storage.delete("old.sh")

    assert "old.sh" not in fake_client.objects
