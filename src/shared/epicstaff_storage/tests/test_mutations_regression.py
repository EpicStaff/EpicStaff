import pytest

from storage import get_mutations


def test_write_bytes_records_write_mutation(storage, fake_client):
    storage.write_bytes("a/b.txt", b"hello")

    assert get_mutations() == [{"op": "write", "path": "a/b.txt"}]
    assert fake_client.objects["a/b.txt"]["Body"] == b"hello"


def test_write_records_write_mutation(storage, fake_client):
    storage.write("a/b.txt", "hello")

    assert get_mutations() == [{"op": "write", "path": "a/b.txt"}]


def test_delete_records_delete_mutation(storage, fake_client):
    storage.write_bytes("a/b.txt", b"hello")

    storage.delete("a/b.txt")

    mutations = get_mutations()
    assert {"op": "delete", "path": "a/b.txt"} in mutations
    assert "a/b.txt" not in fake_client.objects


def test_copy_records_write_mutation_for_destination(storage, fake_client):
    storage.write_bytes("a/src.txt", b"hello")

    storage.copy("a/src.txt", "a/dst.txt")

    mutations = get_mutations()
    assert {"op": "write", "path": "a/dst.txt"} in mutations
    assert fake_client.objects["a/dst.txt"]["Body"] == b"hello"


def test_move_records_write_then_delete(storage, fake_client):
    storage.write_bytes("a/src.txt", b"hello")

    storage.move("a/src.txt", "a/dst.txt")

    mutations = get_mutations()
    assert {"op": "write", "path": "a/dst.txt"} in mutations
    assert {"op": "delete", "path": "a/src.txt"} in mutations
    assert "a/src.txt" not in fake_client.objects
    assert fake_client.objects["a/dst.txt"]["Body"] == b"hello"


def test_read_bytes_missing_key_raises_file_not_found(storage, fake_client):
    with pytest.raises(FileNotFoundError):
        storage.read_bytes("does/not/exist.txt")


def test_read_and_write_roundtrip_no_extra_mutations(storage, fake_client):
    storage.write("a/b.txt", "hello")
    storage.read("a/b.txt")

    # only the write recorded a mutation; reads never mutate
    assert get_mutations() == [{"op": "write", "path": "a/b.txt"}]
