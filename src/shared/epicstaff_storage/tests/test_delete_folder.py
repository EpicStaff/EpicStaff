import pytest

from storage import StoragePermissionError, get_mutations

from conftest import allow_paths


def _seed(fake_client, keys: list[str]) -> None:
    for key in keys:
        fake_client.put_object(Bucket="test-bucket", Key=key, Body=b"x")


@pytest.mark.parametrize("bad_path", ["", "/", "."])
def test_delete_folder_refuses_root_or_empty(storage, fake_client, bad_path):
    _seed(fake_client, ["folder1/file.txt"])

    with pytest.raises(ValueError):
        storage.delete_folder(bad_path)

    # nothing was touched
    assert "folder1/file.txt" in fake_client.objects
    assert get_mutations() == []


def test_delete_folder_raises_when_prefix_matches_nothing(storage, fake_client):
    with pytest.raises(FileNotFoundError):
        storage.delete_folder("does-not-exist")


def test_delete_folder_deletes_every_object_including_keep(storage, fake_client):
    _seed(
        fake_client,
        [
            "folder1/.keep",
            "folder1/file1.txt",
            "folder1/sub/file2.txt",
        ],
    )

    storage.delete_folder("folder1")

    assert fake_client.objects == {}


def test_delete_folder_records_one_mutation_per_object(storage, fake_client):
    _seed(
        fake_client,
        [
            "folder1/.keep",
            "folder1/file1.txt",
            "folder1/sub/file2.txt",
        ],
    )

    storage.delete_folder("folder1")

    mutations = get_mutations()
    assert len(mutations) == 3
    recorded_paths = {m["path"] for m in mutations}
    assert recorded_paths == {
        "folder1/.keep",
        "folder1/file1.txt",
        "folder1/sub/file2.txt",
    }
    assert all(m["op"] == "delete" for m in mutations)


def test_delete_folder_does_not_touch_sibling_prefix(storage, fake_client):
    _seed(fake_client, ["folder1/file.txt", "folder10/file.txt"])

    storage.delete_folder("folder1")

    assert "folder10/file.txt" in fake_client.objects
    assert "folder1/file.txt" not in fake_client.objects


def test_delete_folder_batches_delete_objects_calls(storage, fake_client):
    keys = [f"folder1/file{i}.txt" for i in range(1500)]
    _seed(fake_client, keys)

    storage.delete_folder("folder1")

    assert fake_client.objects == {}
    assert len(get_mutations()) == 1500
    # 1500 keys batched at <=1000/call -> 2 delete_objects calls
    assert len(fake_client.delete_objects_calls) == 2
    assert len(fake_client.delete_objects_calls[0]) == 1000
    assert len(fake_client.delete_objects_calls[1]) == 500


def test_delete_folder_permission_denied(monkeypatch, storage, fake_client):
    allow_paths(monkeypatch, ["allowed_folder/"])
    _seed(fake_client, ["blocked_folder/file.txt"])

    with pytest.raises(StoragePermissionError):
        storage.delete_folder("blocked_folder")

    # nothing was touched
    assert "blocked_folder/file.txt" in fake_client.objects
    assert get_mutations() == []
