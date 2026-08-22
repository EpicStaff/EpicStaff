import pytest

from storage import StoragePermissionError, get_mutations

from conftest import allow_paths


def test_mkdir_writes_keep_marker(storage, fake_client):
    storage.mkdir("newfolder")

    assert "newfolder/.keep" in fake_client.objects
    assert fake_client.objects["newfolder/.keep"]["Body"] == b""


def test_mkdir_records_write_mutation_for_keep_key(storage, fake_client):
    storage.mkdir("newfolder")

    mutations = get_mutations()
    assert mutations == [{"op": "write", "path": "newfolder/.keep"}]


def test_mkdir_mutation_uses_normalized_key_with_org_prefix(
    monkeypatch, storage, fake_client
):
    monkeypatch.setenv("STORAGE_ORG_PREFIX", "org_3")

    storage.mkdir("newfolder")

    mutations = get_mutations()
    assert mutations == [{"op": "write", "path": "org_3/newfolder/.keep"}]


def test_mkdir_permission_denied(monkeypatch, storage, fake_client):
    allow_paths(monkeypatch, ["allowed_folder/"])

    with pytest.raises(StoragePermissionError):
        storage.mkdir("blocked_folder")

    assert fake_client.objects == {}
    assert get_mutations() == []
