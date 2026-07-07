import pytest

from storage import StoragePermissionError

from conftest import allow_paths


def test_no_allowlist_permits_everything(storage, fake_client):
    # STORAGE_ALLOWED_PATHS unset -> __get_allowed_paths() returns None ->
    # check_storage_permission is a no-op for any path.
    storage.write("anything/goes.txt", "hello")
    assert storage.read("anything/goes.txt") == "hello"


def test_allowlist_blocks_path_outside_allowlist(monkeypatch, storage, fake_client):
    allow_paths(monkeypatch, ["allowed/"])

    with pytest.raises(StoragePermissionError):
        storage.write("blocked/file.txt", "nope")


def test_allowlist_permits_exact_file_match(monkeypatch, storage, fake_client):
    allow_paths(monkeypatch, ["allowed/file.txt"])

    storage.write("allowed/file.txt", "ok")
    assert storage.read("allowed/file.txt") == "ok"


def test_allowlist_blocks_sibling_file_not_listed(monkeypatch, storage, fake_client):
    allow_paths(monkeypatch, ["allowed/file.txt"])

    with pytest.raises(StoragePermissionError):
        storage.write("allowed/other.txt", "nope")


def test_path_traversal_rejected_when_allowlist_set(monkeypatch, storage, fake_client):
    allow_paths(monkeypatch, ["allowed/"])

    with pytest.raises(StoragePermissionError):
        storage.read("allowed/../../etc/passwd")
