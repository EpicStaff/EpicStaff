"""Flows never reach the recycle-bin folder Django keeps deleted files in,
whatever their allowed paths say."""

import pytest

from epicstaff_storage import StoragePermissionError

from conftest import allow_paths

TRASH_FILE = ".recycle-bin/batch/docs/a.txt"


def _seed(fake_client, keys: list[str]) -> None:
    for key in keys:
        fake_client.put_object(Bucket="test-bucket", Key=key, Body=b"x")


def _as_local(storage, path):
    with storage.as_local(path):
        pass


OPERATIONS = {
    "read": lambda storage, path: storage.read(path),
    "write": lambda storage, path: storage.write(path, "planted"),
    "delete": lambda storage, path: storage.delete(path),
    "delete_folder": lambda storage, path: storage.delete_folder(path),
    "list": lambda storage, path: storage.list(path),
    "walk": lambda storage, path: storage.walk(path),
    "exists": lambda storage, path: storage.exists(path),
    "info": lambda storage, path: storage.info(path),
    "mkdir": lambda storage, path: storage.mkdir(path),
    "copy_from": lambda storage, path: storage.copy(path, "out.txt"),
    "copy_to": lambda storage, path: storage.copy("a.txt", path),
    "move_from": lambda storage, path: storage.move(path, "out.txt"),
    "move_to": lambda storage, path: storage.move("a.txt", path),
    "as_local": _as_local,
}


@pytest.mark.parametrize("allowed", [None, ["/"], [".recycle-bin/"]], ids=["unset", "whole-org", "the-trash-itself"])
@pytest.mark.parametrize(
    "path", [TRASH_FILE, "/.recycle-bin/batch/a.txt", "./.recycle-bin/x", "docs/../.recycle-bin/x", ".recycle-bin"]
)
@pytest.mark.parametrize("operation", OPERATIONS.values(), ids=OPERATIONS.keys())
def test_every_operation_on_the_trash_is_refused(monkeypatch, storage, fake_client, allowed, path, operation):
    _seed(fake_client, [TRASH_FILE, "a.txt"])
    if allowed is not None:
        allow_paths(monkeypatch, allowed + ["a.txt", "out.txt"])

    with pytest.raises(StoragePermissionError):
        operation(storage, path)

    assert fake_client.get_object(Bucket="test-bucket", Key=TRASH_FILE)["Body"].read() == b"x"


def test_root_list_and_walk_hide_the_trash(storage, fake_client):
    _seed(fake_client, [TRASH_FILE, "a.txt"])

    assert [entry["name"] for entry in storage.list("")] == ["a.txt"]
    assert [entry["path"] for entry in storage.walk("")] == ["a.txt"]


def test_a_folder_merely_named_like_it_deeper_down_is_not_reserved(storage, fake_client):
    _seed(fake_client, ["docs/.recycle-bin/a.txt"])

    assert storage.read("docs/.recycle-bin/a.txt") == "x"
