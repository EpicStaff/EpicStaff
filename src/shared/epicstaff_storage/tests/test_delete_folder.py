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


def test_delete_folder_batch_raises_still_records_earlier_batch_mutations(
    storage, fake_client
):
    """>1000 keys -> 2 batches; batch 2 raises outright.

    Batch 1's successfully-deleted keys must still be recorded as
    mutations, and the exception must still propagate (S3-side objects
    from batch 1 really are gone, so the index must be told about them
    even though the overall call fails).
    """
    keys = [f"folder1/file{i}.txt" for i in range(1500)]
    _seed(fake_client, keys)
    fake_client.fail_delete_objects_on_call = 2

    with pytest.raises(RuntimeError):
        storage.delete_folder("folder1")

    assert len(fake_client.delete_objects_calls) == 2

    # batch 1 (the first 1000 keys) was actually deleted from S3 before
    # batch 2 raised, and every one of those deletions must be recorded.
    batch_1_keys = set(fake_client.delete_objects_calls[0])
    mutations = get_mutations()
    recorded_paths = {m["path"] for m in mutations}
    assert batch_1_keys == recorded_paths
    assert len(mutations) == 1000
    for key in batch_1_keys:
        assert key not in fake_client.objects

    # batch 2's keys were never attempted (the call raised) -> still present
    batch_2_keys = set(keys) - batch_1_keys
    for key in batch_2_keys:
        assert key in fake_client.objects


def test_delete_folder_per_key_errors_excluded_from_mutations_and_raises(
    storage, fake_client
):
    _seed(
        fake_client,
        [
            "folder1/ok1.txt",
            "folder1/bad.txt",
            "folder1/ok2.txt",
        ],
    )
    fake_client.delete_objects_error_keys = {"folder1/bad.txt"}

    with pytest.raises(RuntimeError, match="folder1/bad.txt"):
        storage.delete_folder("folder1")

    # the failed key was not deleted, and excluded from mutations
    assert "folder1/bad.txt" in fake_client.objects
    mutations = get_mutations()
    recorded_paths = {m["path"] for m in mutations}
    assert "folder1/bad.txt" not in recorded_paths

    # the two keys S3 confirmed as deleted are gone and recorded
    assert "folder1/ok1.txt" not in fake_client.objects
    assert "folder1/ok2.txt" not in fake_client.objects
    assert recorded_paths == {"folder1/ok1.txt", "folder1/ok2.txt"}


def test_delete_folder_per_key_errors_across_multiple_batches(storage, fake_client):
    keys = [f"folder1/file{i}.txt" for i in range(1500)]
    _seed(fake_client, keys)
    failing_key = "folder1/file0.txt"  # lands in batch 1 (sorted order)
    fake_client.delete_objects_error_keys = {failing_key}

    with pytest.raises(RuntimeError, match="1 object"):
        storage.delete_folder("folder1")

    # both batches still ran (per-key errors don't abort the loop)
    assert len(fake_client.delete_objects_calls) == 2

    mutations = get_mutations()
    recorded_paths = {m["path"] for m in mutations}
    assert failing_key not in recorded_paths
    assert len(mutations) == 1499
    assert failing_key in fake_client.objects
    for key in keys:
        if key != failing_key:
            assert key not in fake_client.objects
