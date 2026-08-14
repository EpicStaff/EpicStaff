import pytest

from storage import StoragePermissionError, get_mutations

from conftest import allow_paths


def _seed(fake_client, keys: list[str]) -> None:
    for key in keys:
        fake_client.put_object(Bucket="test-bucket", Key=key, Body=b"x")


def test_walk_returns_nested_entries_with_relative_paths(storage, fake_client):
    _seed(
        fake_client,
        [
            "folder1/file1.txt",
            "folder1/sub/file2.txt",
            "folder1/sub/deep/file3.txt",
            "other/file4.txt",
        ],
    )

    entries = storage.walk("folder1")

    paths = {e["path"] for e in entries}
    assert paths == {
        "folder1/file1.txt",
        "folder1/sub/file2.txt",
        "folder1/sub/deep/file3.txt",
    }
    for entry in entries:
        assert set(entry.keys()) == {"path", "size", "modified"}
        assert entry["size"] == 1


def test_walk_skips_keep_markers(storage, fake_client):
    _seed(fake_client, ["folder1/.keep", "folder1/sub/.keep", "folder1/file1.txt"])

    entries = storage.walk("folder1")

    paths = {e["path"] for e in entries}
    assert paths == {"folder1/file1.txt"}


def test_walk_empty_folder_returns_empty_list(storage, fake_client):
    _seed(fake_client, ["folder1/.keep"])

    entries = storage.walk("folder1")

    assert entries == []


def test_walk_strips_org_prefix(monkeypatch, storage, fake_client):
    monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_7")
    _seed(fake_client, ["org_7/folder1/file1.txt"])

    entries = storage.walk("folder1")

    assert entries == [
        {
            "path": "folder1/file1.txt",
            "size": 1,
            "modified": entries[0]["modified"],
        }
    ]


def test_walk_paginates_across_multiple_pages(monkeypatch, storage, fake_client):
    fake_client.page_size = 1
    _seed(
        fake_client,
        [f"folder1/file{i}.txt" for i in range(5)],
    )

    entries = storage.walk("folder1")

    assert len(entries) == 5
    assert {e["path"] for e in entries} == {
        f"folder1/file{i}.txt" for i in range(5)
    }


def test_walk_does_not_leak_sibling_prefix(storage, fake_client):
    _seed(fake_client, ["folder1/file.txt", "folder10/file.txt"])

    entries = storage.walk("folder1")

    assert {e["path"] for e in entries} == {"folder1/file.txt"}


def test_walk_permission_denied(monkeypatch, storage, fake_client):
    allow_paths(monkeypatch, ["allowed_folder/"])

    with pytest.raises(StoragePermissionError):
        storage.walk("blocked_folder")


def test_walk_permission_allowed(monkeypatch, storage, fake_client):
    allow_paths(monkeypatch, ["allowed_folder/"])
    _seed(fake_client, ["allowed_folder/file.txt"])

    entries = storage.walk("allowed_folder")

    assert {e["path"] for e in entries} == {"allowed_folder/file.txt"}


def test_walk_does_not_record_mutations(storage, fake_client):
    _seed(fake_client, ["folder1/file.txt"])

    storage.walk("folder1")

    assert get_mutations() == []
