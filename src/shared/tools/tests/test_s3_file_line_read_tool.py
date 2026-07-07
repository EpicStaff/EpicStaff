from conftest import load_tool, seed

tool = load_tool("s3_file_line_read_tool")


def test_read_default_offset_and_limit(patched_storage, fake_client):
    seed(fake_client, "notes.txt", "a\nb\nc")

    result = tool.main(file_path="notes.txt")

    assert result == "     1\ta\n     2\tb\n     3\tc"


def test_read_with_offset_and_limit(patched_storage, fake_client):
    seed(fake_client, "notes.txt", "a\nb\nc\nd")

    result = tool.main(file_path="notes.txt", offset=2, limit=2)

    assert result == "     2\tb\n     3\tc"


def test_read_file_not_found(patched_storage, fake_client):
    result = tool.main(file_path="missing.txt")

    assert "not found" in result.lower()


def test_read_offset_out_of_range(patched_storage, fake_client):
    seed(fake_client, "notes.txt", "a\nb")

    result = tool.main(file_path="notes.txt", offset=10)

    assert "out of range" in result


def test_read_invalid_offset(patched_storage, fake_client):
    result = tool.main(file_path="notes.txt", offset=0)

    assert "offset must be >= 1" in result


def test_read_invalid_limit(patched_storage, fake_client):
    result = tool.main(file_path="notes.txt", limit=0)

    assert "limit must be >= 1" in result


def test_read_refuses_oversized_file(patched_storage, fake_client, monkeypatch):
    import sys

    storage_module = sys.modules["epicstaff_storage.storage"]
    monkeypatch.setattr(storage_module, "MAX_LINE_READ_BYTES", 5)
    seed(fake_client, "big.txt", "0123456789")

    result = tool.main(file_path="big.txt")

    assert "MB read limit" in result
